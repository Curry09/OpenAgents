"""Spec-0033/T1：worktree-free 的合并冲突诊断采集 + 「卡在哪」段格式化（解耦新模块，理念 10）。

issue #92 的根：所有「合并冲突」通知今天都拿 `rebase.CONFLICT_COMMENT` 一句永不带诊断的静态串
当正文——结构上答不出「具体什么 conflict」。本模块用 **`git merge-tree --write-tree
origin/<base> origin/<head>`**（git 2.38+，不 checkout、不动工作区、不建 worktree）在对象库里算出
某 PR 分支并入目标分支会撞哪些文件、每个冲突文件的关键 hunk 摘要，产出一段结构化 markdown
（冲突文件清单 + 关键 hunk 摘要 + 卡在哪一步），供 merge 闸挂起评论与合并扇出冲突评论的「卡在哪」段。

三件事，全部**安全降级**（任何异常吞成「空诊断」，绝不上抛——诊断只是优化，绝不因「想给诊断」让
挂起/扇出本身失败，见 Reference-level「防自循环 / 安全不变式」）：
- collect：跑 merge-tree + 解析为 ConflictDiag（注入 run，hermetic 可测）。
- format_blocker：纯函数把 ConflictDiag 渲成「卡在哪」段；空诊断退回等价 CONFLICT_COMMENT 的兜底文案。
- make_diagnoser：IO 工厂（与 conflict.make_resolver 同构），返回 diagnose(*, pr_number)->str 闭包，
  供 rebase_open_prs / messages 注入。

证据（CLAUDE.md 理念 7/8）：实测 git 2.39 `git merge-tree --write-tree HEAD <branch>` 冲突时 stdout 为
首行 tree OID + 若干 `<mode> <object> <stage>\t<path>` 行 + 信息段，冲突标记落在写入的 tree blob 里
（非 stdout 内联）；故关键 hunk 经 `git show <tree>:<path>` 从 blob 读出首个冲突块（见 git-merge-tree
文档 https://git-scm.com/docs/git-merge-tree，「Cleanly merging / conflict reporting」）。
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from openagents import github, rebase

# Spec-0033/T1：冲突文件信息行——`git merge-tree --write-tree` 冲突输出里每个未消解 stage 一行，
# 形如 `100644 <40位 sha> 1\t<path>`（mode SP object SP stage TAB path）。stage∈{1,2,3}，同一文件
# 多 stage → 去重保序。只认这种结构化行，信息段（"Auto-merging" / "CONFLICT (...)"）天然不匹配。
_CONFLICT_FILE_RE = re.compile(r"^[0-7]{6} [0-9a-f]{7,64} [123]\t(.+)$")

# Spec-0033/T1：冲突标记前缀（与 conflict._CONFLICT_MARKER 同义，本模块独立持有避免跨模块耦合）。
_MARK_OURS = "<<<<<<<"
_MARK_THEIRS = ">>>>>>>"

# Spec-0033/T1：关键 hunk 摘要的字符上限——为「一眼定位」服务、不刷屏（Drawbacks：截断阈值列入
# Unresolved，此处取保守值）。超限即截断并附省略提示，人可据冲突文件清单本地 `git diff` 看全。
_MAX_HUNK_CHARS = 600
_TRUNCATED_HINT = "…（已截断，完整冲突请本地 git diff 查看）"

# Spec-0033/T1：make_diagnoser 默认「卡在哪一步」描述模板（合并目标分支撞冲突的统一语境）。
_DEFAULT_STEP = "自动合并目标分支 origin/{base} 时"


@dataclass(frozen=True)
class ConflictDiag:
    """Spec-0033/T1：一次合并冲突的诊断快照——冲突文件清单 + 每文件关键 hunk 摘要。

    files：冲突文件清单（去重保序，权威来源是 merge-tree 的未消解 stage 行）。
    hunks：file -> 关键 hunk 摘要（首个冲突块、按 _MAX_HUNK_CHARS 截断）；拿不到内容的文件可缺省。
    空诊断（files 为空）即「无冲突 / 采集失败」，由 format_blocker 退回泛化兜底文案。
    """

    files: list[str] = field(default_factory=list)
    hunks: dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """无冲突文件即视为空诊断（采集不到任何可定位信息）。"""
        return not self.files


# 模块级空诊断单例：collect/make_diagnoser 的安全降级返回值，避免到处构造。
_EMPTY = ConflictDiag()


def collect(
    *, base: str, head: str, run: Callable[..., subprocess.CompletedProcess[str]]
) -> ConflictDiag:
    """Spec-0033/T1：经注入 run 跑 merge-tree 并解析为 ConflictDiag（worktree-free，安全降级）。

    run 签名 `run(*, args: list[str]) -> CompletedProcess`（args 不含 "git" 前缀）。流程：
    1. `merge-tree --write-tree origin/<base> origin/<head>` —— 干净合并 stdout 仅一行 tree OID
       （无 stage 行）→ 解析出空清单 → 空诊断；冲突时 stdout 含 stage 行 + 信息段。
    2. 从 stdout 解析冲突文件清单（_CONFLICT_FILE_RE）；无 → 空诊断（「无冲突」与「命令非0/输出异常」
       都自然落到这里）。
    3. tree OID（首行）+ 每个冲突文件经 `git show <tree>:<path>` 取 blob 内首个冲突块作关键 hunk 摘要。

    命令缺失（FileNotFoundError）/ 任何异常 → 返回空 ConflictDiag，绝不上抛（诊断只是优化）。
    """
    try:
        proc = run(args=["merge-tree", "--write-tree", f"origin/{base}", f"origin/{head}"])
    except Exception:  # noqa: BLE001 — 安全降级：命令缺失/任何异常都吞成空诊断，绝不上抛
        return _EMPTY
    output = proc.stdout or ""
    files = _parse_conflict_files(output=output)
    if not files:
        # 干净合并（仅 tree OID 行）/ 非 0 错误输出 / 解析不到结构化冲突行 —— 一律空诊断。
        return _EMPTY
    tree_oid = _parse_tree_oid(output=output)
    hunks: dict[str, str] = {}
    for path in files:
        hunk = _hunk_for(path=path, tree_oid=tree_oid, run=run)
        if hunk:
            hunks[path] = hunk
    return ConflictDiag(files=files, hunks=hunks)


def format_blocker(*, diag: ConflictDiag, step: str) -> str:
    """Spec-0033/T1：把 ConflictDiag 渲成「卡在哪」段 markdown（纯函数，无 IO）。

    非空诊断 → 「卡在哪一步 + 冲突文件清单 + 关键 hunk 摘要」；下游（blocknote.build）会把整段当
    blocker 逐行包成引用块，故此处只产纯文本、不自带签名/引用前缀。空诊断 → 退回 rebase.CONFLICT_COMMENT
    （等价今日泛化兜底文案、单一来源，避免串漂移），使调用方无需自己判空。
    """
    if diag.is_empty():
        return rebase.CONFLICT_COMMENT
    lines = [
        f"{step}以下文件存在无法自动解决的冲突，需人工裁断——",
        "",
        f"冲突文件清单（{len(diag.files)}）",
    ]
    lines.extend(f"- {path}" for path in diag.files)
    for path in diag.files:
        hunk = diag.hunks.get(path)
        if hunk:
            lines.extend(["", f"关键 hunk 摘要 · {path}", "```", hunk, "```"])
    return "\n".join(lines)


def make_diagnoser(*, work_dir: str, base: str) -> Callable[..., str]:
    """Spec-0033/T1：构造 rebase_open_prs / messages 用的 diagnose 回调 `(*, pr_number) -> str`。

    与 conflict.make_resolver 同构（IO 工厂）：闭包内取 PR head 分支 → `git fetch` base/head →
    collect + format_blocker，整体 best-effort。任何环节失败（取分支失败 / fetch 失败 / 异常）→ 退回
    format_blocker 对空诊断的兜底文案（即 rebase.CONFLICT_COMMENT），绝不上抛。work_dir 缺省/失败由
    调用方（messages._make_diagnoser 仅在 work_dir 齐备时构造、否则传 None）兜底退回静态文案。
    """
    root = Path(work_dir)
    step = _DEFAULT_STEP.format(base=base)

    def _run(*, args: list[str]) -> subprocess.CompletedProcess[str]:
        # worktree-free：在 work_dir 仓库根直跑 git，只读对象库、不动工作区。
        return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)

    def diagnose(*, pr_number: int) -> str:
        try:
            branch = github.pr_head_branch(pr_number=pr_number)
            # 取最新 base/head，使 origin/<base>、origin/<branch> 可被 merge-tree 解析（best-effort）。
            _run(args=["fetch", "origin", base, branch])
            diag = collect(base=base, head=branch, run=_run)
            return format_blocker(diag=diag, step=step)
        except Exception:  # noqa: BLE001 — 安全降级：任何环节失败都退回空诊断兜底文案
            return format_blocker(diag=_EMPTY, step=step)

    return diagnose


def _parse_tree_oid(*, output: str) -> str:
    """merge-tree --write-tree 的输出首行即写入的 toplevel tree OID；取不到返回 ""。"""
    for line in output.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _parse_conflict_files(*, output: str) -> list[str]:
    """从 merge-tree 输出解析冲突文件清单（去重保序）；非冲突/无结构化行返回 []。"""
    files: list[str] = []
    for line in output.splitlines():
        match = _CONFLICT_FILE_RE.match(line)
        if match:
            path = match.group(1)
            if path not in files:
                files.append(path)
    return files


def _hunk_for(
    *, path: str, tree_oid: str, run: Callable[..., subprocess.CompletedProcess[str]]
) -> str:
    """取某冲突文件的关键 hunk 摘要：从写入 tree 的 blob（`git show <tree>:<path>`）读首个冲突块。

    安全降级：无 tree_oid / show 失败 / 无冲突标记 → 返回 ""（该文件无 hunk，仍在清单里）。
    """
    if not tree_oid:
        return ""
    try:
        proc = run(args=["show", f"{tree_oid}:{path}"])
    except Exception:  # noqa: BLE001 — 单文件 hunk 取不到不影响整体诊断，吞成空
        return ""
    return _first_conflict_block(text=proc.stdout or "")


def _first_conflict_block(*, text: str) -> str:
    """提取文本里首个 `<<<<<<< … >>>>>>>` 冲突块（含两端标记行），按 _MAX_HUNK_CHARS 截断。"""
    start = text.find(_MARK_OURS)
    if start == -1:
        return ""
    marker = text.find(_MARK_THEIRS, start)
    if marker == -1:
        block = text[start:]
    else:
        line_end = text.find("\n", marker)
        block = text[start:] if line_end == -1 else text[start:line_end]
    if len(block) > _MAX_HUNK_CHARS:
        return block[:_MAX_HUNK_CHARS] + _TRUNCATED_HINT
    return block
