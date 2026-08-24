"""# Spec-0060/T3: runtime.gates —— 最小硬闸（只验客观事实，不含业务判断）。

「兜底 agent 自述、防撒谎/死循环」的最后一道确定性防线。分界线严格等于 agent 分工：
**需要判断 → agent；客观机械 → 确定性代码。** 本模块只验四类客观事实，绝不判 PASS/REWORK、
不判「代码对不对」「冲突怎么解」——那些是 agent 的活。

- `assert_head_advanced`：head 有没有前移（真交付了？）——#140 的 `assert_delivered` 一般化。
- `assert_merge_allowed`：合并红线（CI 全绿 + review-approved:<head sha7>@head）——Spec-0017 兜底不可逆合并。
- `round_cap`：循环轮次上限（防死循环）——reviewer 恒 REWORK 时兜底 raise。
- `assert_pr_exists`：PR 号存在性。
- `assert_evidence_stamp`：证据溯源戳（`head_sha` 匹配）——Spec-0055 沿用。
- `assert_writes_owned`：越权写硬闸（changeset ⊆ 本组声明 files ∪ 生成物）——Spec-0071 把「单一
  writer」从设计期声明推到运行期拒绝。

经 `utils.git` / `utils.github` 读客观事实（确定性层）、`spec.ownership` 读单一 writer 声明，自身
不直接碰 subprocess/gh。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openagents.spec import model as spec_model
from openagents.spec import ownership
from openagents.spec.model import Group
from openagents.spec.render import render as render_specs
from openagents.spec.validate import validate as validate_specs

# Spec-0074/T1: alias-import 换轨——平台操作经 forge 分发层按配置委托 github/gitea driver，调用点零改动。
from openagents.utils import forge as github
from openagents.utils import git

# Spec-0060/T3: 评审循环默认轮次上限——超此仍未 PASS 视作死循环，兜底 raise（可由调用方覆盖）。
DEFAULT_MAX_ROUNDS = 10


def assert_repository_integrity(*, workspace: Path) -> None:
    """Reject a merge candidate whose complete Spec snapshot is inconsistent."""
    specs_root = Path(workspace) / "docs" / "specs"
    report = validate_specs(specs_root=specs_root)
    errors = [f"{item.where}: {item.message}" for item in report.issues if item.level == "error"]
    if errors:
        raise GateError("仓库级 Spec 完整性失败：" + "; ".join(errors))
    overview = specs_root / "OVERVIEW.md"
    actual = overview.read_text(encoding="utf-8") if overview.exists() else ""
    if actual != render_specs(specs_root=specs_root):
        raise GateError("仓库级 Spec 完整性失败：OVERVIEW.md 与候选树不一致")


def assert_design_approved(*, workspace: Path, issue_number: int, approved_digest: str) -> None:
    """Reject implementation or merge after approved design semantics changed."""
    groups = [
        group
        for group in spec_model.load_all(specs_root=Path(workspace) / "docs" / "specs")
        if group.metadata.issue == issue_number
    ]
    if len(groups) != 1:
        raise GateError(f"issue #{issue_number} 无唯一 Spec，设计批准不可验证")
    current = spec_model.design_digest(group=groups[0])
    if current != approved_digest:
        raise GateError(
            f"issue #{issue_number} 的设计已变化：approved={approved_digest[:12]} current={current[:12]}"
        )


# Spec-0062/T2: 合并流水线（recipes.merge_pr）的确定性判读原语——只**读客观事实分类**、不判「能不能合」。
# 复活窗口默认阈值：对齐旧 messages.REOPEN_REVIVE_WINDOW_SECONDS（7 天）——closed run 超此即硬化真终态。
REVIVE_WINDOW_SECONDS = 7 * 24 * 3600

# Spec-0062/T2: hold/skip 两组闸名白名单——对称短路判读只认这些闸名，未知闸名判 GateError（防拼写漂移）。
_HOLD_GATES = ("spec", "merge")
_SKIP_GATES = ("ci", "code", "evidence", "spec")

# Spec-0017/T3: 合并硬闸的两条客观判据——CI 全绿 + `review-approved:<head sha7>` label 且 sha 匹配当前 head。
# label 前缀与 recipes.vigil `_LABEL_REVIEW_APPROVED_PREFIX` 同字面（裁决落处的单一约定），sha7 长度与 git 短
# sha 一致。gates 不 import vigil（避免 recipe→runtime 反向依赖），故在此就地立常量。
_REVIEW_APPROVED_LABEL_PREFIX = "review-approved:"
_SHA_LABEL_LEN = 7


class GateError(Exception):
    """# Spec-0060/T3: 最小硬闸判定客观事实不成立（未交付 / 死循环 / PR 不存在 / 戳不匹配）时抛出。"""


@dataclass(frozen=True)
class IntegrationStamp:
    """The exact repository/design versions covered by an integration check."""

    base_sha: str
    head_sha: str
    design_digest: str


def assert_integration_stamp(*, approved: IntegrationStamp, current: IntegrationStamp) -> None:
    """Reject reuse of an integration result after any observed input changed."""
    if not all((current.base_sha, current.head_sha, current.design_digest)):
        raise GateError("集成校验戳不完整")
    if current != approved:
        raise GateError("集成校验已失效：base、head 或 design digest 在校验后发生变化")


class MergeNotReady(Exception):
    """Spec-0074 实证：合并前 CI 仍在跑（pending）——**不是红线，是「还没好」**。

    与 `GateError`（客观违规：CI 失败 / 零 check / 裁决作废 → 真挡、该交人）严格区分：pending 是**暂态**，
    下一 tick CI 绿了就能合。故本异常由 `_run_claimed` 当「干净收工」处理（删行、**不累计 attempts**），
    等生产者下轮重判——与 `_classify` ⑦ awaiting-ci 的 QUIET 语义一致。若并入 GateError 走回队重试，会在
    CI 的 pending→success 窗口内烧光 `_MAX_ATTEMPTS` → 误挂 needs-human（GitHub check-runs 翻转快躲过，
    Gitea Actions 落得慢才暴露；这是所有平台的潜伏问题）。
    """


def snapshot_head(*, workspace: Path) -> str:
    """确定性记录 worktree 当前 HEAD SHA——**由 harness 侧调用**，作交付前的客观基点。

    #140 的教训：head 前移硬闸的「基点」绝不能取自 agent 自述（`report["base_sha"]` 由 agent 掌控
    事实源，报一个 ≠ 当前 HEAD 的值就能让闸恒放行、哪怕一个 commit 都没落地）。故派 deliver **之前**
    由 recipe 经本函数确定性记下 `before`，交给 `assert_head_advanced` 比对——与 `assert_delivered`
    「harness 派 agent 前自记基点」同源。经 utils.git 读，recipe 自身不碰 git/subprocess。
    """
    return git.head_sha(work_dir=Path(workspace))


def assert_head_advanced(*, before: str, workspace: Path) -> str:
    """head 前移硬闸：断言交付后 worktree 的 HEAD 已越过交付前基点 `before`，不动即抛；返回实际 after。

    兜底 #140 空转（干净工作区被 agent 当成「已交付」而 head 其实没动）：`before` 是 harness 侧经
    `snapshot_head` 确定性记录的基点（**不信 agent 自述**），本闸读**当前** HEAD（经 utils.git.head_sha）
    比对——相等 / 读不到 HEAD → 判「未交付/空转」→ raise GateError。纯读客观事实，不判交付内容对不对
    （那归 reviewer）。返回实际 after SHA，供上层接证据溯源戳（`assert_evidence_stamp`）复用、免二次读。
    """
    after = git.head_sha(work_dir=Path(workspace))
    if not after:
        raise GateError(f"未交付：工作区 {workspace} 读不到 HEAD（疑似空仓/未提交）")
    if after == before:
        raise GateError(
            f"head 未前移、疑似未交付：交付前后 HEAD 同为 {after[:12]}"
            f"（agent 自判完成却没落地新提交）"
        )
    return after


def assert_merge_allowed(*, pr_number: int, head_sha: str, require_ci: bool = True) -> None:
    """合并红线硬闸（Spec-0017/T3）：**实时复读** CI + labels，非「全绿 ∧ review-approved:<head sha7>@head」即抛。

    合并**不可逆**——当初把 `merge_pr` 留在确定性层，就是防「觉得可以合了」就合掉一份没审过的代码。把合并
    动作下放 merger agent 后，「可不可以合」这条红线仍由本闸把守：agent 只能在本闸放行后才被派上来落合并
    动作，且本闸**绑 head sha**。它补两个洞：
    - **误派**：merger agent 若被错误路由/手动触发，闸不放行就抛，agent 决不合并未审代码；
    - **TOCTOU**：`_sense`（读到 approved@head）与 `_act`（落合并）之间 head 可能又前移（有人 push 了新
      提交），本闸在落合并前**实时**再读一次 CI + label，head 一动 `review-approved:<旧 sha7>` 就对不上
      当前 head → 抛，裁决自动作废，绝不合并未审的新代码。

    纯读客观事实、零业务判断（承 gates 分层锚点）：CI 全绿 = `check_snapshot` state==pass 且 count>0（零个
    check 不算绿，比照 vigil `_ci_state`——防合并一份没跑过 CI 的代码）；review-approved = `pr_snapshot`
    的 labels 里存在 `review-approved:<当前 head 的 sha7>`。任一不满足 → GateError（合并不发生）。
    """
    if require_ci:
        checks = github.check_snapshot(pr_number=pr_number)
        # 零 check = 没跑过 CI → 硬挡（决不合未过 CI 的代码）；顺序在 pending 之前。
        if checks.count == 0:
            raise GateError(
                f"合并硬闸未放行：PR #{pr_number} 当前 head 零个 check——决不合并未过 CI 的代码"
            )
        if checks.state == "pending":
            raise MergeNotReady(
                f"PR #{pr_number} 当前 head CI 仍在跑（pending）——非红线，等下一 tick 重判"
            )
        if checks.state != "pass":
            raise GateError(
                f"合并硬闸未放行：PR #{pr_number} 当前 head CI 非全绿"
                f"（state={checks.state}、check 数={checks.count}）——决不合并未过 CI 的代码"
            )
    labels = github.pr_snapshot(pr_number=pr_number).labels
    expected = f"{_REVIEW_APPROVED_LABEL_PREFIX}{head_sha[:_SHA_LABEL_LEN]}"
    if expected not in labels:
        raise GateError(
            f"合并硬闸未放行：PR #{pr_number} 无匹配当前 head 的 {expected!r} label"
            f"（现有 {sorted(labels)}）——决不合并未审代码或裁决已因 head 前移作废"
        )


def round_cap(*, max_rounds: int | None = None) -> Iterator[int]:
    """轮次上限生成器：逐轮 yield 轮号（从 1 起）；耗尽 max_rounds 仍被继续取用 → raise。

    用法 `for _ in round_cap(): ...`——调用方在满足条件（如评审 PASS）时 break，生成器随之丢弃、
    永不 raise；若调用方跑满 max_rounds 轮仍未 break，下一次取值会走到循环体之外 raise GateError，
    兜底「reviewer 恒 REWORK」的死循环。max_rounds=None 时**在调用时**读模块级
    `DEFAULT_MAX_ROUNDS`（而非绑死在默认参数上），便于按需覆盖/测试。
    """
    limit = DEFAULT_MAX_ROUNDS if max_rounds is None else max_rounds
    yield from range(1, limit + 1)  # 逐轮 yield 轮号（1..limit）；break 则丢弃、永不 raise。
    raise GateError(f"评审循环超过 {limit} 轮上限仍未收敛，疑似死循环（reviewer 恒 REWORK）")


def assert_pr_exists(*, pr_number: int) -> None:
    """PR 存在性硬闸：探测 PR 号对应的真实 PR，不存在即抛。

    经 utils.github.pr_head_branch（`gh pr view`）探针——PR 不存在时 github 抛 GithubError，
    在此转成 GateError（携 PR 号）。只验「PR 号指向一个真 PR」，不判其状态/内容。
    """
    try:
        github.pr_head_branch(pr_number=pr_number)
    except github.GithubError as exc:
        raise GateError(f"PR #{pr_number} 不存在或不可读：{exc}") from exc


def assert_evidence_stamp(*, head_sha: str, claimed: str) -> None:
    """证据溯源戳硬闸（Spec-0055）：断言证据自述的 head_sha 与实际 head 一致，不匹配即抛。

    纯值比对、零 IO：agent/executor 交付证据时盖上「这份证据对应哪个 head」的戳（`claimed`），
    本闸用实际 `head_sha` 对照——不等 = 证据陈旧/张冠李戴 → raise GateError。
    """
    if head_sha != claimed:
        raise GateError(
            f"证据溯源戳不匹配：实际 head={head_sha[:12] or '（空）'} ≠ "
            f"证据自述 head={claimed[:12] or '（空）'}（证据陈旧或张冠李戴）"
        )


def assert_writes_owned(
    *,
    group: Group,
    changed_paths: list[str],
    specs_root: Path = Path("docs/specs"),
) -> None:
    """越权写硬闸（Spec-0071/T3）：断言 changeset 里没有落在无主文件上的写，有则抛。

    借鉴 Rust「所有权唯一 + `&mut` 独占」：一个 spec 组内每个文件至多一个 owner Task（`spec
    validate` 的同组 files 不重叠 error 已在设计期保证唯一性），本闸把这份声明推到**运行期**——
    agent 交付后由 harness 读实际改动文件集，凡落在「本组任何 Task 都没声明、且非生成物（spec md
    / OVERVIEW / ARCHITECTURE）」的文件上的写即判越权 → raise GateError，而非靠 reviewer 肉眼逮
    （issue #71 验收：只读 agent 的越权写被 harness 拦截）。纯读客观事实（文件路径集合）、零业务
    判断（承 gates 分层锚点），经 `spec.ownership` 做集合判定。

    Args:
        group: 本次交付所属的 spec 组（提供 `tasks[].files` 单一 writer 声明）。
        changed_paths: 实际改动的文件路径（仓库相对，harness 由 `git diff --name-only` 得到）。
        specs_root: specs 根目录（默认 docs/specs），透传给 ownership 判定生成物路径。

    Raises:
        GateError: 存在无主写（越权写）时抛，消息列出全部越权文件与其应有的归属提示。
    """
    offenders = ownership.unowned_writes(
        group=group, changed_paths=changed_paths, specs_root=specs_root
    )
    if offenders:
        raise GateError(
            f"越权写被拒：改动了本组（{group.number}）任何 Task 都未声明、且非生成物的文件 "
            f"{offenders}——按理念 6「每个 Task 占一组互斥 files」，写前须在 spec 里声明归属"
        )


# --------------------------------------------------------------------------------------------------
# Spec-0062/T2: 合并流水线判读闸——把旧 messages.poll 里散落的「读 GitHub 客观事实做分类」抽成纯函数。
# 全部**读客观事实、返布尔/分类**，绝不判「这版能不能合」（那是 reviewer agent 的活）、也不判「冲突怎么
# 解」（那是 git delivery agent 的活）。recipes.merge_pr 据这些判读路由。均为纯逻辑，零 IO、hermetic 可测
# （入参是调用方已从 utils.github 读到手的 Mergeability / CheckStatus 快照，本层不再触网）。
# --------------------------------------------------------------------------------------------------


def is_conflicting(*, mergeability: github.Mergeability) -> bool:
    """可合并性预检：DIRTY 或 CONFLICTING 即判有文本冲突（取「或」更稳，对齐旧 messages.poll）。

    冲突场景 DIRTY 与 CONFLICTING 常同时出现（旧 poll 实例 PR #61），任一命中即需 git delivery
    agent 去 rebase 解——本函数只读 GitHub 给的两个原值判「有没有冲突」，不判「怎么解」。
    """
    return mergeability.merge_state_status == "DIRTY" or mergeability.mergeable == "CONFLICTING"


def is_mergeable_unknown(*, mergeability: github.Mergeability) -> bool:
    """GitHub 异步尚未算完（刚 push 常见）——UNKNOWN 是合法中间态：本轮不推进、下轮重查。"""
    return mergeability.mergeable == "UNKNOWN"


def is_behind(*, mergeability: github.Mergeability) -> bool:
    """落后 base 但无文本冲突——BEHIND：需拉最新 base 进来触发 CI 在集成态重跑（拉式同步）。"""
    return mergeability.merge_state_status == "BEHIND"


def ci_failed(*, check_status: github.CheckStatus) -> bool:
    """CI 结论判读：任一 check 失败（对齐旧 poll 的 `status.state == "fail"`）。"""
    return check_status.state == "fail"


def ci_pending(*, check_status: github.CheckStatus) -> bool:
    """CI 结论判读：仍有 check 进行中（本轮不评审、下轮重查）。"""
    return check_status.state == "pending"


def evidence_stamp_ok(*, head_sha: str, claimed: str) -> bool:
    """e2e 证据溯源戳判读——`assert_evidence_stamp` 的**布尔版**（不 raise，供 merge_pr 路由）。

    与 `assert_evidence_stamp` 同口径：claimed 非空且 == 实际 head → 证据对得上当前 head、放行；
    否则（缺证据 / 陈旧 / 张冠李戴）→ 未就绪。区别在于——solve_issue 里证据戳不符是「agent 撒谎」
    硬 raise，而 merge_pr 里只表示「本轮该回去补 e2e」（返 "e2e" 事件、非硬失败），故用布尔判读。
    """
    return bool(claimed) and claimed == head_sha


def revive_eligible(*, closed_at: str, now: datetime, window_seconds: int | None = None) -> bool:
    """closed-run 复活窗口判读（对齐旧 messages._revive_eligible）：closed_at 在窗口内 → 复活候选。

    只有候选才值得每轮花一次 gh 查 PR 是否被 reopen；空 closed_at / 无法解析 / 超窗口 → False
    （硬化成真终态、不再发 gh，成本有界）。`now` 由调用方传入（**不读系统时钟**，hermetic 可测）；
    window_seconds=None 时用模块级 `REVIVE_WINDOW_SECONDS`（而非绑死默认参数，便于按需覆盖/测试）。
    """
    if not closed_at:
        return False
    try:
        closed = datetime.fromisoformat(closed_at)
    except ValueError:
        return False
    window = REVIVE_WINDOW_SECONDS if window_seconds is None else window_seconds
    return (now - closed).total_seconds() <= window


def hold_hits(*, hold: object, gate: str) -> bool:
    """hold 短路判读：`gate` 闸是否被 `--hold` 夯住（停在闸门等人批）。gate ∈ _HOLD_GATES。

    读 Hold 值对象的 `at_<gate>` 布尔位——纯读意图、零判断。与 `skip_hits` 对称（hold=停下等人、
    skip=当 PASS 放行，语义相反）。未知闸名 raise GateError，防调用方拼错闸名静默漏短路。
    """
    if gate not in _HOLD_GATES:
        raise GateError(f"未知 hold 闸名 {gate!r}（合法：{_HOLD_GATES}）")
    return bool(getattr(hold, f"at_{gate}"))


def skip_hits(*, skip: object, gate: str) -> bool:
    """skip 短路判读（与 `hold_hits` 对称）：`gate` 闸是否被 `--skip` 当 PASS 放行。gate ∈ _SKIP_GATES。"""
    if gate not in _SKIP_GATES:
        raise GateError(f"未知 skip 闸名 {gate!r}（合法：{_SKIP_GATES}）")
    return bool(getattr(skip, f"at_{gate}"))
