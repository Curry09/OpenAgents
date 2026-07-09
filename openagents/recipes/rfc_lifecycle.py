"""# Spec-0062/T1: recipes.rfc_lifecycle —— RFC 生命周期五入口（纯控制流，零业务判断）。

把旧 `orchestrator.py` 的 `start_rfc / backfill_rfc / refine_rfc / implement / iterate` 五条 RFC
生命周期按既定分界线（**判断走 agent、机械留确定性 recipe/utils/engine**）重立为新栈 recipe。
additive——旧 orchestrator 零改动，本模块是其等价新栈实现，后续批次 CLI 改接后再删旧。

每个入口只做「组占位符 → 调 `engine.run_agent(drafter, ...)` 出结构化裁决 → 按裁决走确定性兜底
动作」：
- 判断（RFC 正文怎么写 / 反推成什么 spec / 按评论怎么精炼 / 获批后怎么实现 / 据反馈怎么迭代 +
  交付/解冲突）下放 `agents.drafter`；
- 机械（认领标签 / 建·复用 worktree / 开·转正 draft PR / 贴公告评论 / 落 run 状态）留 recipe，经
  `utils.github` / `utils.identity` / `utils.git` 落地；
- 三道确定性硬闸（`runtime.gates`）兜底 drafter 自述：交付前基点由 recipe 经 `gates.snapshot_head`
  **确定性记录**（不信 agent 自述），交付后 `assert_head_advanced` 断言 head 真前移、
  `assert_evidence_stamp` 断言 drafter 自报 head_sha 与实际 HEAD 一致（防 #140 空转/张冠李戴）。

依赖注入（hermetic 可测）：`backend` / `state` / `work_dir` / `agent_id` 由调用方（CLI 单一接线点）
传入；`github` / `identity` / `git` / `gates` / `engine` 以模块属性访问，测试 monkeypatch 即可喂
canned 裁决、不触真实 LLM/网络/仓库。worktree 建/拉走模块级 `prepare_worktree` / `ensure_worktree`
（默认经 utils.git.Workspace，测试可 monkeypatch 替免真 git）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from openagents.agents import drafter
from openagents.runtime import engine, gates
from openagents.utils import git, github, identity

# Spec-0062/T1: 分支命名前缀——单 issue → 单分支（与旧 orchestrator / recipes.vigil 逐字一致）。
_BRANCH_PREFIX = "openagents/issue-"
# Spec-0062/T1: brownfield 反推的分支前缀——输入是代码 path（无 issue 号），用 path slug 定址。
_BACKFILL_BRANCH_PREFIX = "openagents/backfill-"

# Spec-0062/T1: 分支基线默认锁定 main（承旧 orchestrator DEFAULT_BASE / Spec-0023 test 退役）。
DEFAULT_BASE = "main"

# Spec-0062/T1: drafter 的五种工作模式（同 agent 骨架 + mode 占位符分化，见 agents.drafter）。
_MODE_DRAFT = "draft"
_MODE_BACKFILL = "backfill"
_MODE_REFINE = "refine"
_MODE_IMPLEMENT = "implement"
_MODE_ITERATE = "iterate"

# Spec-0062/T1: run 状态字面量（承旧 orchestrator STATUS_*，落新栈 RuntimeState 独立命名空间）。
_STATUS_SOLVING = "solving"
_STATUS_RFC_REVIEW = "rfc-review"
_STATUS_PR_OPEN = "pr-open"
_STATUS_ITERATING = "iterating"

# Spec-0062/T1: refine 后回贴 PR 的公告评论模板（承旧 _REFINE_COMMENT，决策 6：让人类知 spec 已据评审更新）。
_REFINE_COMMENT = "🤖 已根据评审意见更新 spec：\n\n{summary}"


class RfcLifecycleError(Exception):
    """# Spec-0062/T1: RFC 生命周期编排无法继续时抛出（承旧 orchestrator.OrchestratorError 语义）。

    典型：refine/implement/iterate 找不到 PR 对应的 run；backfill 反推草稿未过 validate（drafter
    自述未交付）故不开 PR。是普通 Exception，由上层守候段/CLI 的 per-issue 错误隔离兜住。
    """


def prepare_worktree(*, work_dir: Path, issue_number: Any, branch: str, base: str) -> Path:
    """默认建全新隔离 worktree（fresh，draft/backfill 用）——经 utils.git.Workspace（可 monkeypatch）。

    issue_number 允许是 int（issue 号）或 str（backfill 的 path slug），与旧 workspace.prepare 同签名。
    """
    return git.Workspace(work_dir=Path(work_dir)).prepare(
        issue_number=issue_number, branch=branch, base=base
    )


def ensure_worktree(*, work_dir: Path, issue_number: Any, branch: str) -> Path:
    """默认复用某 issue 既有 worktree（refine/implement/iterate 用）——经 utils.git.Workspace。"""
    return git.Workspace(work_dir=Path(work_dir)).ensure(issue_number=issue_number, branch=branch)


def draft_rfc(
    *,
    issue_number: int,
    backend: Any,
    state: Any,
    work_dir: Path,
    agent_id: str,
    base: str = DEFAULT_BASE,
) -> dict:
    """据 issue 起草 spec → 派 drafter（draft 模式）交付 → 开 draft PR，落 rfc-review。承旧 start_rfc。

    机械序：拉 issue → 建 worktree → 记 solving checkpoint → 认领（标签 + 署名便签）→（快照基点）
    派 drafter → head 前移 + 证据戳硬闸 → 开 draft PR → 记 rfc-review（含 pr 号）→ 摘认领标签。
    判断（spec 正文怎么写、如何交付）全在 drafter；本函数零业务判断。返回本轮事件（含 pr 号/摘要）。
    """
    issue = github.get_issue(number=issue_number)
    branch = f"{_BRANCH_PREFIX}{issue_number}"
    worktree = prepare_worktree(
        work_dir=work_dir, issue_number=issue_number, branch=branch, base=base
    )
    # 进入即记 run（PR 尚未开）——崩溃后可据此恢复定位（承旧 begin_run checkpoint）。
    state.set_run(issue_number=issue_number, status=_STATUS_SOLVING, branch=branch, pr_number=None)
    _claim(issue_number=issue_number, agent_id=agent_id)

    verdict = _run_drafter(
        backend=backend,
        worktree=worktree,
        mode=_MODE_DRAFT,
        target=f"issue #{issue.number}「{issue.title}」",
        branch=branch,
        detail=issue.body,
        context=issue.body,
        require_delivered=False,
    )

    pr = github.create_pr(
        branch=branch,
        base=base,
        title=f"docs: spec for issue #{issue.number} {issue.title}".strip(),
        body=f"Closes #{issue.number}\n\nspec 草稿待评审。",
        draft=True,
    )
    # 一次写成带 pr 的 rfc-review（承旧 record_run，消除瞬态 pr-open 窗口）。
    state.set_run(
        issue_number=issue_number, status=_STATUS_RFC_REVIEW, branch=branch, pr_number=pr.number
    )
    # draft PR 开出后摘认领标签——远端分支 + draft PR 已是去重信号，清理尽力而为、不阻断已开出的 PR。
    _release_claim(issue_number=issue_number)
    _log(message=f"▶ issue #{issue_number}：起草完成，开 draft PR #{pr.number}")
    return {"pr_number": pr.number, "reason": "drafted", "summary": verdict["summary"]}


def backfill_rfc(
    *,
    path: str,
    backend: Any,
    state: Any,
    work_dir: Path,
    agent_id: str,
    base: str = DEFAULT_BASE,
) -> dict:
    """据存量代码反推 spec → 派 drafter（backfill 模式）交付 → 开 draft PR。承旧 backfill_rfc。

    与 draft_rfc 同构，只替换两端：输入端「拉 issue」换成「以 path slug 定址」，任务端「据 issue 起草」
    换成「据代码反推」。**validate 门控**（承旧 backfill 决策）在新栈由 drafter 的 backfill 模式自跑
    `spec validate`——未过则 delivered=false，recipe 据此**不开 PR**、抛 RfcLifecycleError（保证开出的
    draft PR 必已过质量门槛）；此判定读的是 agent 自述 delivered（agent 已在 worktree 真跑校验），
    recipe 只按裁决路由、自身不重跑 validate（无 validate 原语在 utils，见返回说明的 reconcile 项）。
    """
    slug = _slug_for(path=path)
    branch = f"{_BACKFILL_BRANCH_PREFIX}{slug}"
    worktree = prepare_worktree(work_dir=work_dir, issue_number=slug, branch=branch, base=base)

    verdict = _run_drafter(
        backend=backend,
        worktree=worktree,
        mode=_MODE_BACKFILL,
        target=f"代码路径 `{path}`",
        branch=branch,
        detail=path,
        context=path,
        require_delivered=True,
    )

    pr = github.create_pr(
        branch=branch,
        base=base,
        title=f"docs: backfill spec for {path}",
        body=(
            f"🤖 反向补全：扫 `{path}` 反推出的 spec 草稿，待评审。\n\n"
            "必填四段据实回填；标「待人工补全」的段请在评审中补全后再转正（不自动 merge）。"
        ),
        draft=True,
    )
    _log(message=f"▶ 反推 `{path}` 完成，开 draft PR #{pr.number}")
    return {"pr_number": pr.number, "reason": "backfilled", "summary": verdict["summary"]}


def refine_rfc(
    *,
    pr_number: int,
    detail: str,
    backend: Any,
    state: Any,
    work_dir: Path,
    agent_id: str,
    announce: bool = True,
) -> dict:
    """按评审意见精炼 spec → 派 drafter（refine 模式）交付 → 回贴公告评论，维持 rfc-review。承旧 refine_rfc。

    announce=True（reviewer 驱动路径）回贴泛化「已据评审更新 spec」公告；announce=False 抑制广播
    （人类解挂路径由 poll_comments/replier 引用原评论统一回应，见 Spec-0061，不在此叠加第二条评论）。
    """
    record = _require_run(state=state, pr_number=pr_number)
    worktree = ensure_worktree(
        work_dir=work_dir, issue_number=record["issue_number"], branch=record["branch"]
    )

    verdict = _run_drafter(
        backend=backend,
        worktree=worktree,
        mode=_MODE_REFINE,
        target=f"PR #{pr_number}",
        branch=record["branch"],
        detail=detail,
        context=detail,
        require_delivered=False,
    )

    if announce:
        identity.post_signed_comment(
            pr_number=pr_number,
            body=_REFINE_COMMENT.format(summary=verdict["summary"] or "（无摘要）"),
            agent_id=agent_id,
        )
    state.set_run(
        issue_number=record["issue_number"],
        status=_STATUS_RFC_REVIEW,
        branch=record["branch"],
        pr_number=pr_number,
    )
    _log(message=f"▶ PR #{pr_number}：已据评审精炼 spec")
    return {"pr_number": pr_number, "reason": "refined", "summary": verdict["summary"]}


def implement(
    *,
    pr_number: int,
    backend: Any,
    state: Any,
    work_dir: Path,
    agent_id: str,
) -> dict:
    """RFC 获批后据 spec 实现代码 → 派 drafter（implement 模式）交付 → 把 draft PR 转正，落 pr-open。承旧 implement。"""
    record = _require_run(state=state, pr_number=pr_number)
    worktree = ensure_worktree(
        work_dir=work_dir, issue_number=record["issue_number"], branch=record["branch"]
    )

    verdict = _run_drafter(
        backend=backend,
        worktree=worktree,
        mode=_MODE_IMPLEMENT,
        target=f"issue #{record['issue_number']} / PR #{pr_number}",
        branch=record["branch"],
        detail="",
        context="",
        require_delivered=False,
    )

    github.mark_ready(pr_number=pr_number)
    state.set_run(
        issue_number=record["issue_number"],
        status=_STATUS_PR_OPEN,
        branch=record["branch"],
        pr_number=pr_number,
    )
    _log(message=f"▶ PR #{pr_number}：实现完成，draft 转正")
    return {
        "pr_number": pr_number,
        "reason": "implemented",
        "summary": verdict["summary"] or "（无摘要）",
    }


def iterate(
    *,
    pr_number: int,
    reason: str,
    detail: str,
    backend: Any,
    state: Any,
    work_dir: Path,
    agent_id: str,
) -> dict:
    """coding 阶段据 CI/评论/评审/e2e 反馈迭代 → 派 drafter（iterate 模式）追加 commit，落 iterating。承旧 iterate。

    reason ∈ {"comment","ci","review","e2e"}：作为反馈来源标注拼进 detail。旧 orchestrator 的
    reason="human"（人解挂正面回应）在新栈已由 recipes.poll_comments + agents.replier 承接
    （Spec-0061），不再走本入口（见返回说明的 reconcile 项）。
    """
    record = _require_run(state=state, pr_number=pr_number)
    worktree = ensure_worktree(
        work_dir=work_dir, issue_number=record["issue_number"], branch=record["branch"]
    )

    verdict = _run_drafter(
        backend=backend,
        worktree=worktree,
        mode=_MODE_ITERATE,
        target=f"PR #{pr_number}",
        branch=record["branch"],
        detail=f"{reason}反馈：\n{detail}",
        context=detail,
        require_delivered=False,
    )

    state.set_run(
        issue_number=record["issue_number"],
        status=_STATUS_ITERATING,
        branch=record["branch"],
        pr_number=pr_number,
    )
    _log(message=f"▶ PR #{pr_number}：据{reason}反馈迭代完成")
    return {"pr_number": pr_number, "reason": "iterated", "summary": verdict["summary"]}


def _run_drafter(
    *,
    backend: Any,
    worktree: Path,
    mode: str,
    target: str,
    branch: str,
    detail: str,
    context: str,
    require_delivered: bool,
) -> dict:
    """派 drafter 出结构化裁决 + 三道确定性硬闸兜底交付——五入口共用的交付骨架（承旧 _assert_delivered_or_fail）。

    交付前基点由 recipe 经 `gates.snapshot_head` **确定性记录**（不取 agent 自述，防 #140 报假基点让闸
    恒放行）；派 drafter 后 `assert_head_advanced` 断言 head 真前移、`assert_evidence_stamp` 断言 drafter
    自报 head_sha 与实际 HEAD 一致。`require_delivered=True`（backfill validate 门控）时先据 agent 自述
    `delivered` 短路——未过 validate/未交付即抛 RfcLifecycleError、不进硬闸（不开 PR）。
    """
    before = gates.snapshot_head(workspace=worktree)
    verdict = engine.run_agent(
        drafter,
        backend=backend,
        work_dir=worktree,
        context=context,
        mode=mode,
        target=target,
        branch=branch,
        detail=detail,
    )
    if require_delivered and not verdict["delivered"]:
        raise RfcLifecycleError(
            f"drafter（mode={mode}）自述未交付（疑未过 spec validate 或 rebase 未落地），不开 PR"
        )
    after = gates.assert_head_advanced(before=before, workspace=worktree)
    gates.assert_evidence_stamp(head_sha=after, claimed=verdict["head_sha"])
    return verdict


def _claim(*, issue_number: int, agent_id: str) -> None:
    """认领 issue = 幂等 add DISPATCH_LABEL + 追加署名认领便签（承旧 _claim_issue 的写侧）。

    幂等 add 是 no-op 不产生 labeled 事件（根除无差别 remove 撕标签）；署名便签作归属凭证。
    旧 read-after-write 二次确认（ClaimLost 退让）属多后端认领竞争，归 vigil 认领归属（Spec-0062/T3），
    本入口不含（见返回说明的 reconcile 项）。gh 故障不吞——上抛交守候段 per-issue 隔离兜住。
    """
    github.issue_add_label(number=issue_number, name=github.DISPATCH_LABEL)
    github.issue_comment(number=issue_number, body=identity.build_claim_note(agent_id=agent_id))


def _release_claim(*, issue_number: int) -> None:
    """draft PR 开出后摘认领标签——尽力而为，任何 gh 故障只记进度并吞掉（残留标签无害）。承旧 _release_claim。"""
    try:
        github.issue_remove_label(number=issue_number, name=github.DISPATCH_LABEL)
    except github.GithubError as error:
        _log(message=f"⚠ 摘认领标签失败（已忽略，残留标签无害）：{error}")


def _require_run(*, state: Any, pr_number: int) -> dict:
    """按 PR number 定位 run；找不到即抛 RfcLifecycleError（refine/implement/iterate 复用）。承旧 _require_run。

    经注入的 `state.find_run(pr_number=...)`——返回含 `issue_number` / `branch` 的 run 记录 dict。
    （新栈 RuntimeState 目前按 issue_number 索引、尚无 by-pr 查询，接线时需补 find_run，见返回说明 reconcile 项。）
    """
    record = state.find_run(pr_number=pr_number)
    if record is None:
        raise RfcLifecycleError(f"找不到 PR #{pr_number} 对应的 run")
    return record


def _slug_for(*, path: str) -> str:
    """把代码 path 派生成分支安全的 slug（非字母数字折成单个连字符）——backfill 无 issue 号，用它定址。"""
    raw = "".join(ch if ch.isalnum() else "-" for ch in str(path).strip("/"))
    slug = "-".join(seg for seg in raw.split("-") if seg)
    return slug or "root"


def _log(*, message: str) -> None:
    """RFC 生命周期进度打到 stderr，保证全程有可观测轨迹（与 recipes.vigil / poll_comments 同通道）。"""
    print(message, file=sys.stderr, flush=True)
