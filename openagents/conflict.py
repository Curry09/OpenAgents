"""Spec-0028/T2：merge 冲突派 coding agent 语义解冲突——indexheal 的语义化兄弟。

`indexheal`（issue #48）只能**确定性**消解生成式索引 `docs/specs/OVERVIEW.md` 的冲突
（按合并后的 spec 源整表重渲即得并集）。其余**任何真冲突**目前一律甩给人工 rebase。本模块
补上中间一层：在 PR 分支的临时 worktree 里把 base 并入，撞冲突时把冲突文件清单喂给注入的
coding 后端 agent，让它读 `<<<<<<<` 标记、语义解决、跑 ruff+pytest 自测、续 commit、push；
解不了（仍有残留冲突标记 / 任何异常）才 `merge --abort` 回落人工。形成分层降级：
**indexheal（确定性，仅 OVERVIEW）→ conflict（通用，啃真冲突）→ 人工兜底**。

照搬 indexheal 已验证的骨架（理念 10 解耦）：纯决策 `resolve_branch` 与 IO 解耦——git 走注入
的 `run`、语义解决走注入的 `backend`，便于 hermetic 单测；IO 工厂 `make_resolver` 负责临时
detached worktree 的建/清理与 push。安全降级（关键）：任何异常都吞成 False——解冲突只是优化，
失败即退回「留言等人」的现状，绝不解错后静默 push、也绝不拖垮合并扇出。
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from openagents import github
from openagents.backends.base import AgentBackend

# 解冲突用的临时 worktree 根（.openagents/ 已被 .gitignore 忽略），按 agent + 分支名隔离、用后即删。
_RESOLVE_SUBDIR = Path(".openagents") / "resolve"

# 冲突标记前缀——agent 解完后据此 grep 残留，二次确认无未消解冲突（与 --diff-filter=U 双保险）。
_CONFLICT_MARKER = "<<<<<<<"

# 喂给 coding 后端的语义解冲突 + 自测指令模板。强调：解完必须跑 ruff+pytest 自测，解不了就别
# 留残标——自测门控是「宁可不解、不可解错」的根（Spec-0028 Drawbacks：正确性风险缓解）。
_RESOLVE_TASK = (
    "本分支正在 `git merge` base，出现合并冲突。请逐个打开下列冲突文件，读 `<<<<<<<` / "
    "`=======` / `>>>>>>>` 标记，**语义化**地解决冲突（保留双方真实意图，而非机械取一边），"
    "清除所有冲突标记，然后跑 `ruff check . && ruff format --check . && pytest -q` 自测。"
    "若自测通过即完成（不要自行 commit，外层会统一提交）；若无法解决或自测不过，请保持文件"
    "现状、不要清除冲突标记（外层会据残留标记回落人工）。\n\n冲突文件：\n{files}"
)

# Spec-0036/T3：人类对本次解冲突的指导段（guidance 非空时拼到 _RESOLVE_TASK 之后）。人在被 merge
# 冲突挂起的 PR 下回的评论（如「先解 X 再动 Y」）经此喂给解冲突 agent——补齐「merge 闸也听人话」
# （issue #97 A 项）。guidance="" 时该段不拼接，行为逐字节同今天（零回归）。
_GUIDANCE_SECTION = "\n\n人类对本次解冲突的指导（请据此优先处理）：\n{guidance}"


class ConflictResolveError(Exception):
    """解冲突过程中的 git 操作失败（IO 层 / resolve_branch 据此降级为 False）。"""


def resolve_branch(
    *,
    worktree: Path,
    base: str,
    backend: AgentBackend,
    run: Callable[..., subprocess.CompletedProcess[str]],
    guidance: str = "",
) -> bool:
    """在 worktree 内把 `origin/<base>` 并入当前分支并尝试语义解冲突，返回是否已解决（待调用方 push）。

    - 干净合并 → True（无需 agent）。
    - 冲突 → 把冲突文件清单喂给 backend.run 让 agent 语义解决 + 自测；解完**无残留冲突标记**
      （`--diff-filter=U` 为空且 grep 无 `<<<<<<<`）→ `git add -A` + `commit --no-edit` → True。
    - 仍有残留冲突标记 / 自测失败（agent 按指令保留残标）/ 任何异常 → `merge --abort` → False。

    Spec-0036/T3：guidance 为人类对本次解冲突的指导（merge 闸解挂时的评论正文）。`guidance=""`
    （缺省）即不带人类指导，喂给 agent 的 task 逐字节同今天（零回归）；非空时拼进 _RESOLVE_TASK 的
    「人类对本次解冲突的指导」段，让解冲突 agent 看到人说了什么。返回类型保持 bool 不变（不波及
    rebase.rebase_open_prs 对 resolve(...) 的真值判断）。

    任何异常都吞成 False（安全降级）：解冲突是优化，失败即退回人工留言路径，绝不解错后静默 push。
    """
    try:
        merged = run(args=["merge", f"origin/{base}", "--no-edit"], cwd=worktree, check=False)
        if merged.returncode == 0:
            return True
        conflicts = _conflicted(worktree=worktree, run=run)
        if not conflicts:
            # 合并失败但无 U 文件（非冲突类错误，如 base 不存在）：无从下手，abort 交人工。
            run(args=["merge", "--abort"], cwd=worktree, check=False)
            return False
        backend.run(
            work_dir=worktree,
            task=_resolve_task(conflicts=conflicts, guidance=guidance),
            context="\n".join(str(path) for path in conflicts),
        )
        if _has_residual_conflict(worktree=worktree, run=run, files=conflicts):
            run(args=["merge", "--abort"], cwd=worktree, check=False)
            return False
        run(args=["add", "-A"], cwd=worktree, check=True)
        run(args=["commit", "--no-edit"], cwd=worktree, check=True)
        return True
    except Exception:  # noqa: BLE001 — 安全降级：任何异常都吞成 False，回落人工留言路径
        # best-effort 收尾：尝试 abort 让 worktree 回到干净态（abort 自身异常也忽略）。
        try:
            run(args=["merge", "--abort"], cwd=worktree, check=False)
        except Exception:  # noqa: BLE001 — 收尾尽力而为，不掩盖原始降级结果
            pass
        return False


def make_resolver(
    *, work_dir: Path, base: str, backend: AgentBackend, agent_id: str
) -> Callable[..., bool]:
    """构造 `rebase_open_prs` / messages 用的 resolve 回调 `(*, pr_number) -> bool`。

    与 `indexheal.make_healer` 同构：取 PR head 分支 → 建临时 detached worktree（`.openagents/`
    下、按 agent_id + 分支名隔离，避免并发 agent 相撞）→ `resolve_branch` → 成功则 push 回该分支
    → `finally` 幂等清理 worktree。任何环节失败都吞成 False（安全降级到人工留言路径）。
    """
    root = Path(work_dir)
    # agent_id 进 worktree 路径：多 agent 并发解同一/不同 PR 时按身份隔离临时工作区（理念 6）。
    bucket = _RESOLVE_SUBDIR / agent_id.replace("/", "-")

    def resolve(*, pr_number: int, guidance: str = "") -> bool:
        # Spec-0036/T3：guidance 透传给 resolve_branch（merge 闸解挂时人类评论正文当解冲突指导）。
        # guidance=""（缺省，含 auto-rebase 等无人类评论场景）即行为逐字节同今天（零回归）。
        try:
            branch = github.pr_head_branch(pr_number=pr_number)
        except github.GithubError:
            return False
        path = root / bucket / branch.replace("/", "-")
        try:
            _git(args=["fetch", "origin", base, branch], cwd=root, check=True)
            _cleanup(root=root, path=path)
            _git(
                args=["worktree", "add", "--force", "--detach", str(path), f"origin/{branch}"],
                cwd=root,
                check=True,
            )
            if not resolve_branch(
                worktree=path, base=base, backend=backend, run=_git, guidance=guidance
            ):
                return False
            _git(args=["push", "origin", f"HEAD:refs/heads/{branch}"], cwd=path, check=True)
            return True
        except ConflictResolveError:
            return False
        finally:
            _cleanup(root=root, path=path)

    return resolve


def _resolve_task(*, conflicts: list[Path], guidance: str) -> str:
    """Spec-0036/T3：拼解冲突任务 prompt——基础 _RESOLVE_TASK，guidance 非空时追加人类指导段。

    guidance=""（缺省）即只返回基础模板，逐字节同今天（零回归）；非空时在冲突文件清单之后追加
    「人类对本次解冲突的指导」段。私有纯函数，调用方显式传参。
    """
    task = _RESOLVE_TASK.format(files="\n".join(str(path) for path in conflicts))
    if guidance.strip():
        task += _GUIDANCE_SECTION.format(guidance=guidance)
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
