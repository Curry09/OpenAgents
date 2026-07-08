"""Spec-0028/T2：merge 冲突派 coding agent 语义解冲突。

本模块负责在 PR 分支合入最新 base 撞冲突时做**语义解冲突**：在 PR 分支的临时 worktree 里把
base 并入，撞冲突时把冲突文件清单喂给注入的 coding 后端 agent，让它读 `<<<<<<<` 标记、语义
解决、跑 ruff+pytest 自测、续 commit、push。其中对生成式索引 `docs/specs/OVERVIEW.md`
（由 `spec render` 整表生成）走**确定性重渲**（issue #48 的确定性路径）——按合并后的 spec 源
整表重渲即得并集；其余真实代码/文档冲突逐个语义解决。解不了（仍有残留冲突标记 / 任何异常）才
`merge --abort` 回落人工。

纯决策 `resolve_branch` 与 IO 解耦（理念 10）——git 走注入的 `run`、语义解决走注入的
`backend`，便于 hermetic 单测；IO 工厂 `make_resolver` 负责临时 detached worktree 的建/清理。
Spec-0056/T5：**交付（commit+push）下放 agent**——冲突路径由 agent 自己 `git add -A && commit`
并 `git push` 上远端本分支，`resolve_branch` 只做只读校验（残留标记 + head 前移 + 推送落地）；
唯有**干净自动合并**（无 agent turn、合并 commit 是 harness 自著）才由 `make_resolver` 普通 push。
安全降级（关键）：任何异常都吞成 False——解冲突只是优化，失败即退回「留言等人」的现状，
绝不解错后静默 push、也绝不「自判解决却没推上去」（同 issue #140 冻结类兜底）。
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from openagents import github
from openagents.backends.base import AgentBackend

# 解冲突用的临时 worktree 根（.openagents/ 已被 .gitignore 忽略），按 agent + 分支名隔离、用后即删。
_RESOLVE_SUBDIR = Path(".openagents") / "resolve"

# 冲突标记前缀——agent 解完后据此 grep 残留，二次确认无未消解冲突（与 --diff-filter=U 双保险）。
_CONFLICT_MARKER = "<<<<<<<"

# 喂给 coding 后端的语义解冲突 + 自测指令模板。强调：解完必须跑 ruff+pytest 自测，解不了就别
# 留残标——自测门控是「宁可不解、不可解错」的根（Spec-0028 Drawbacks：正确性风险缓解）。
# 关键：先判断冲突文件的性质再动手——生成式索引（docs/specs/OVERVIEW.md，由 `spec render` 整表
# 生成）是纯机械冲突，必须用 `spec render` 按合并后的 spec 源重渲确定性消解，禁止逐行手工合并
# 一张生成表（手工合并正是「机械式报错」与残留标记的来源，对齐 issue #48 的确定性重渲路径）。
_RESOLVE_TASK = (
    "本分支正在 `git merge` base，出现合并冲突。**先逐个判断冲突文件的性质，再决定怎么解**：\n"
    "1) 生成式索引 `docs/specs/OVERVIEW.md`（由 `spec render` 整表生成）——**不要逐行手工合并**，"
    "直接跑 `spec render` 按合并后的 spec 源重渲整张表以确定性消解，再 `git add` 该文件清除其冲突标记；\n"
    "2) 其余真实代码/文档冲突——逐个打开，读 `<<<<<<<` / `=======` / `>>>>>>>` 标记，**语义化**"
    "解决（保留双方真实意图，而非机械取一边），清除冲突标记；\n"
    "全部清完后跑 `ruff check . && ruff format --check . && pytest -q` 自测。\n"
    # Spec-0056/T5：解冲突的 git 交付也下放 agent（原「不要自行 commit，外层统一提交」翻转为「自己
    # commit + push」）——本 merge 是把 base 快进叠加到本分支、结果是本分支 tip 的后代，**普通 push
    # 即可、无需 force**（与四条派单/迭代路径的 force-with-lease 分叉场景不同）。外层只保留残留标记
    # 检查 + head 前移/推送落地校验（宁可不解、不可解错，且不可自判解决却没推上去）。
    "自测通过后**由你自己交付**：`git add -A && git commit --no-edit`（沿用 merge 默认信息），再 "
    "`git push origin HEAD:refs/heads/{branch}` 把解冲突结果推上远端本分支 `{branch}`"
    "（此 merge 为快进叠加，普通 push 即可、**无需** force）；`git rev-parse origin/{branch}` 等于本地 "
    "`HEAD` 即交付完成。若无法解决或自测不过，请保持文件现状、**不要 commit / push**、不要清除冲突"
    "标记（外层会据残留标记回落人工）。\n\n冲突文件：\n{files}"
)

# Spec-0036/T3：人类对本次解冲突的指导段（guidance 非空时拼到 _RESOLVE_TASK 之后）。人在被 merge
# 冲突挂起的 PR 下回的评论（如「先解 X 再动 Y」）经此喂给解冲突 agent——补齐「merge 闸也听人话」。
_GUIDANCE_SECTION = "\n\n人类对本次解冲突的指导（请据此优先处理）：\n{guidance}"

# 回评论工具段（guidance 非空且已知 pr_number 时追加）：让解冲突 agent 自己回人类评论，但**必须**走
# 带签名的 `openagents reply-comment` 命令、严禁裸 gh——无签名的回复会被下一轮 poll 当成新人类评论、
# 触发无限自我循环。这是 merge 闸「牛头不对马嘴」的根治：回复由 agent 针对评论亲自发（带签名防自循环）。
_REPLY_TOOL_SECTION = (
    "\n\n回复要求：上面这条指导若是人类留的（PR 评论里**无 OpenAgents 签名**的才算人类）且与你这次"
    "解冲突直接相关，完成后请回复它——**必须用命令 "
    '`openagents reply-comment --pr {pr_number} --body "<你的回应>"` 来回**'
    "（它会以你 agent 的身份自动盖签名）；**绝不要用 `gh pr comment` 等裸命令回**——那样发的评论没"
    "签名，会被下一轮识别成新的人类评论、让你陷入无限自我触发的循环。与你无关的评论不必回。"
)


@dataclass
class ResolveOutcome:
    """解冲突结果：是否解开。`__bool__` 返回 resolved，兼容既有 `if resolve(...)` 真值判断。

    Spec-0056/T5：`delivered` 标记「解冲突结果是否已由 agent 自己 commit+push 上远端」——
    冲突路径由 agent 交付（resolve_branch 已校验 head 前移 + origin/<branch>==HEAD）→ delivered=True，
    make_resolver 不再代 push；干净自动合并路径（无 agent turn）delivered=False，仍由 make_resolver
    普通 push（harness 自著合并、非「agent 执行完的 git」，留 harness 合规）。
    """

    resolved: bool
    delivered: bool = False

    def __bool__(self) -> bool:
        return self.resolved


class ConflictResolveError(Exception):
    """解冲突过程中的 git 操作失败（IO 层 / resolve_branch 据此降级为 resolved=False）。"""


def resolve_branch(
    *,
    worktree: Path,
    base: str,
    branch: str,
    backend: AgentBackend,
    run: Callable[..., subprocess.CompletedProcess[str]],
    guidance: str = "",
    pr_number: int | None = None,
) -> ResolveOutcome:
    """在 worktree 内把 `origin/<base>` 并入当前分支并尝试语义解冲突，返回 ResolveOutcome。

    - 干净合并 → ResolveOutcome(resolved=True, delivered=False)（无 agent turn，交付留 make_resolver 普通 push）。
    - 冲突 → 把冲突文件清单喂给 backend.run 让 agent 语义解决 + 自测 + **自己 `git add -A && commit`
      并 `push` 上远端本分支**（Spec-0056/T5 交付下放）；解完**无残留冲突标记**、且校验 head 前移
      （HEAD ≠ 合并前的 pre）+ 推送落地（`origin/<branch>` == HEAD）→ ResolveOutcome(resolved=True, delivered=True)。
    - 仍有残留冲突标记 / agent 没 commit（HEAD 未前移）/ 没 push 上去（origin≠HEAD）/ 自测失败 /
      非冲突类失败 / 任何异常 → `merge --abort` → resolved=False（安全降级，回落人工）。

    Spec-0036/T3：guidance 为人类对本次解冲突的指导（merge 闸解挂时的评论正文）。非空时拼进
    「人类对本次解冲突的指导」段；再带 pr_number 时追加「回评论工具段」——让 agent 完事后**自己**用
    `openagents reply-comment` 回那条评论（带签名防自循环），框架不再代发（根治「牛头不对马嘴」）。

    任何异常都吞成 resolved=False（安全降级）：解冲突是优化，失败即退回人工，绝不解错后静默 push，
    也绝不「自判解决却没推上去」（Spec-0056/T5 head 前移 + 推送落地双校验，同 issue #140 兜底精神）。
    """
    try:
        merged = run(args=["merge", f"origin/{base}", "--no-edit"], cwd=worktree, check=False)
        if merged.returncode == 0:
            return ResolveOutcome(resolved=True)
        conflicts = _conflicted(worktree=worktree, run=run)
        if not conflicts:
            # 合并失败但无 U 文件（非冲突类错误，如 base 不存在）：无从下手，abort 交人工。
            run(args=["merge", "--abort"], cwd=worktree, check=False)
            return ResolveOutcome(resolved=False)
        # Spec-0056/T5：记合并前 HEAD（此刻 merge 冲突中、HEAD 仍在本分支 tip）——agent 交付后据它判 head 是否前移。
        pre = run(args=["rev-parse", "HEAD"], cwd=worktree, check=False).stdout.strip()
        backend.run(
            work_dir=worktree,
            task=_resolve_task(
                conflicts=conflicts, guidance=guidance, branch=branch, pr_number=pr_number
            ),
            context="\n".join(str(path) for path in conflicts),
        )
        if _has_residual_conflict(worktree=worktree, run=run, files=conflicts):
            run(args=["merge", "--abort"], cwd=worktree, check=False)
            return ResolveOutcome(resolved=False)
        # Spec-0056/T5：交付下放 agent 后，外层不再 `add -A`/`commit`/`push`，改为**校验** agent 真的交付了：
        # ① head 前移（HEAD ≠ pre）——解了标记却没 commit（merge 半途）则 HEAD 未动，判未交付、abort 回落人工；
        # ② 推送落地（fetch 后 origin/<branch> == HEAD）——commit 了却没 push（正是 issue #140 的冻结类）判未交付。
        # 两道都是只读「检查」（符合用户「除检查外 git 全下放 agent」的划线），任一不过即安全降级 resolved=False。
        post = run(args=["rev-parse", "HEAD"], cwd=worktree, check=False).stdout.strip()
        if not post or post == pre:
            run(args=["merge", "--abort"], cwd=worktree, check=False)
            return ResolveOutcome(resolved=False)
        run(args=["fetch", "origin", branch], cwd=worktree, check=False)
        remote = run(args=["rev-parse", f"origin/{branch}"], cwd=worktree, check=False)
        if remote.returncode != 0 or remote.stdout.strip() != post:
            return ResolveOutcome(resolved=False)
        return ResolveOutcome(resolved=True, delivered=True)
    except Exception:  # noqa: BLE001 — 安全降级：任何异常都吞成 resolved=False，回落人工
        # best-effort 收尾：尝试 abort 让 worktree 回到干净态（abort 自身异常也忽略）。
        try:
            run(args=["merge", "--abort"], cwd=worktree, check=False)
        except Exception:  # noqa: BLE001 — 收尾尽力而为，不掩盖原始降级结果
            pass
        return ResolveOutcome(resolved=False)


def make_resolver(
    *, work_dir: Path, base: str, backend: AgentBackend, agent_id: str
) -> Callable[..., ResolveOutcome]:
    """构造 messages 用的 resolve 回调 `(*, pr_number, guidance="") -> ResolveOutcome`。

    取 PR head 分支 → 建临时 detached worktree（`.openagents/` 下、按 agent_id + 分支名隔离，避免并发
    agent 相撞）→ `resolve_branch` → 解开则 push 回该分支 → `finally` 幂等清理 worktree。返回
    ResolveOutcome（resolved + agent 回应文案 reply）；任何环节失败吞成 resolved=False（安全降级）。
    """
    root = Path(work_dir)
    # agent_id 进 worktree 路径：多 agent 并发解同一/不同 PR 时按身份隔离临时工作区（理念 6）。
    bucket = _RESOLVE_SUBDIR / agent_id.replace("/", "-")

    def resolve(*, pr_number: int, guidance: str = "") -> ResolveOutcome:
        # Spec-0036/T3：guidance 透传给 resolve_branch（merge 闸解挂时人类评论正文当解冲突指导）。
        try:
            branch = github.pr_head_branch(pr_number=pr_number)
        except github.GithubError:
            return ResolveOutcome(resolved=False)
        path = root / bucket / branch.replace("/", "-")
        try:
            _git(args=["fetch", "origin", base, branch], cwd=root, check=True)
            _cleanup(root=root, path=path)
            _git(
                args=["worktree", "add", "--force", "--detach", str(path), f"origin/{branch}"],
                cwd=root,
                check=True,
            )
            outcome = resolve_branch(
                worktree=path,
                base=base,
                branch=branch,
                backend=backend,
                run=_git,
                guidance=guidance,
                pr_number=pr_number,
            )
            if not outcome.resolved:
                return outcome
            # Spec-0056/T5：冲突路径（delivered=True）由 agent 自己 push 且 resolve_branch 已校验推送落地，
            # harness 不再代 push（git 下放 agent）。仅**干净自动合并**路径（delivered=False、无 agent turn，
            # 合并 commit 是 harness 自著）才由 harness 普通 push——它不是「agent 执行完的 git」，留 harness 合规。
            if not outcome.delivered:
                _git(args=["push", "origin", f"HEAD:refs/heads/{branch}"], cwd=path, check=True)
            return outcome
        except ConflictResolveError:
            return ResolveOutcome(resolved=False)
        finally:
            _cleanup(root=root, path=path)

    return resolve


def _resolve_task(
    *, conflicts: list[Path], guidance: str, branch: str, pr_number: int | None = None
) -> str:
    """拼解冲突任务 prompt——基础 _RESOLVE_TASK，guidance 非空时追加人类指导段 + 回评论工具段。

    guidance=""（缺省）即只返回基础模板；非空时追加「人类对本次解冲突的指导」段；再带 pr_number 时
    追加「回评论工具段」（要求 agent 用带签名的 `openagents reply-comment --pr <n>` 亲自回评论）。
    Spec-0056/T5：`branch` 填进交付指令的 `git push origin HEAD:refs/heads/<branch>` 目标。私有纯函数，
    调用方显式传参（缺省值仅 guidance/pr_number 两个可选项，branch 必传）。
    """
    task = _RESOLVE_TASK.format(files="\n".join(str(path) for path in conflicts), branch=branch)
    if guidance.strip():
        task += _GUIDANCE_SECTION.format(guidance=guidance)
        if pr_number is not None:
            task += _REPLY_TOOL_SECTION.format(pr_number=pr_number)
    return task


def _conflicted(
    *, worktree: Path, run: Callable[..., subprocess.CompletedProcess[str]]
) -> list[Path]:
    """当前合并的未消解（unmerged）文件清单（`git diff --name-only --diff-filter=U`）。"""
    out = run(args=["diff", "--name-only", "--diff-filter=U"], cwd=worktree, check=True).stdout
    return [Path(line) for line in out.splitlines() if line.strip()]


def _has_residual_conflict(
    *,
    worktree: Path,
    run: Callable[..., subprocess.CompletedProcess[str]],
    files: list[Path],
) -> bool:
    """agent 解完后是否仍有残留冲突：① 还有 unmerged 文件，或 ② 任一原冲突文件仍含 `<<<<<<<`。

    双保险（理念 8 证据驱动）：`--diff-filter=U` 抓未 `add` 的残留，grep 抓「agent 清了 index
    但文件里仍留标记」的漏网；任一命中即判未解决，回落人工（宁可不解、不可解错）。
    """
    if _conflicted(worktree=worktree, run=run):
        return True
    for path in files:
        full = worktree / path
        try:
            if _CONFLICT_MARKER in full.read_text(encoding="utf-8"):
                return True
        except OSError:
            # 读不到（被删/改名）不算残留标记——交给上面的 unmerged 检查与后续 add/commit 兜底。
            continue
    return False


def _cleanup(*, root: Path, path: Path) -> None:
    """幂等移除临时 worktree（失败忽略——清理是尽力而为，不应掩盖真实结果）。"""
    _git(args=["worktree", "remove", "--force", str(path)], cwd=root, check=False)
    _git(args=["worktree", "prune"], cwd=root, check=False)


def _git(*, args: list[str], cwd: Path, check: bool) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise ConflictResolveError(f"git {' '.join(args)} 失败：{proc.stderr.strip()}")
    return proc
