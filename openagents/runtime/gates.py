"""# Spec-0060/T3: runtime.gates —— 最小硬闸（只验客观事实，不含业务判断）。

「兜底 agent 自述、防撒谎/死循环」的最后一道确定性防线。分界线严格等于 agent 分工：
**需要判断 → agent；客观机械 → 确定性代码。** 本模块只验四类客观事实，绝不判 PASS/REWORK、
不判「代码对不对」「冲突怎么解」——那些是 agent 的活。

- `assert_head_advanced`：head 有没有前移（真交付了？）——#140 的 `assert_delivered` 一般化。
- `round_cap`：循环轮次上限（防死循环）——reviewer 恒 REWORK 时兜底 raise。
- `assert_pr_exists`：PR 号存在性。
- `assert_evidence_stamp`：证据溯源戳（`head_sha` 匹配）——Spec-0055 沿用。

经 `utils.git` / `utils.github` 读客观事实（确定性层），自身不直接碰 subprocess/gh。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from openagents.utils import git, github

# Spec-0060/T3: 评审循环默认轮次上限——超此仍未 PASS 视作死循环，兜底 raise（可由调用方覆盖）。
DEFAULT_MAX_ROUNDS = 10


class GateError(Exception):
    """# Spec-0060/T3: 最小硬闸判定客观事实不成立（未交付 / 死循环 / PR 不存在 / 戳不匹配）时抛出。"""


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
