"""# Spec-0064/T4: recipes.backfill —— backfill-rfc path 驱动追溯单列（纯控制流，零业务判断）。

`oa backfill-rfc <path>` 指着一段存量代码反推出 spec 并开 draft PR（实现在前、设计在后）。与 issue
驱动的 vigil 环**正交**——vigil 发现段扫的是 issue，不是待补文档的代码路径，故单列一个入口（不进
issue 环、与 vigil 发现段解耦，理念 10）。additive：承旧 `rfc_lifecycle.backfill_rfc`，逻辑不重复
实现，**复用 T2 `stages.rfc` 的起草原子**（drafter 的 backfill mode）。

机械序（与 draft 同构，只替换两端）：以 path slug 定址建 worktree → 派 `stages.rfc`（backfill mode，
require_delivered=True）反推 spec → 据 agent 自述 `delivered` 路由——**validate 门控**：drafter 的
backfill mode 自跑 `spec validate`，未过则 delivered=false、本 recipe 据此**不开 PR**、抛
`BackfillError`（保证开出的 draft PR 必已过质量门槛）；过则开 draft PR。判断（反推成什么 spec）全在
drafter；本函数零业务判断。三道确定性硬闸兜底交付自述内嵌于 `stages.rfc`（承 T2）。

依赖注入（hermetic 可测）：`backend` / `work_dir` 由调用方（CLI 单一接线点）传入；`github` /
`stages` 以模块属性访问，测试 monkeypatch 即可喂 canned 裁决、不触真实 LLM/网络/仓库。worktree 建
走模块级 `prepare_worktree`（默认经 utils.git.Workspace，测试可 monkeypatch 替免真 git）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from openagents.recipes import stages
from openagents.utils import git, github

# Spec-0064/T4: brownfield 反推的分支前缀——输入是代码 path（无 issue 号），用 path slug 定址。
_BACKFILL_BRANCH_PREFIX = "openagents/backfill-"

# Spec-0064/T4: 分支基线默认锁定 main（承旧 rfc_lifecycle.DEFAULT_BASE / Spec-0023 test 退役）。
DEFAULT_BASE = "main"


class BackfillError(Exception):
    """# Spec-0064/T4: backfill 反推草稿未过 validate（drafter 自述未交付）故不开 PR 时抛出（承旧 RfcLifecycleError 语义）。"""


def prepare_worktree(*, work_dir: Path, slug: str, branch: str, base: str) -> Path:
    """默认建全新隔离 worktree——经 utils.git.Workspace（可 monkeypatch 替免真 git）。承旧 prepare_worktree。"""
    return git.Workspace(work_dir=Path(work_dir)).prepare(
        issue_number=slug, branch=branch, base=base
    )


def backfill_rfc(
    *,
    path: str,
    backend: Any,
    work_dir: Path,
    base: str = DEFAULT_BASE,
) -> dict:
    """据存量代码反推 spec → 复用 stages.rfc（backfill mode）交付 → 开 draft PR。承旧 rfc_lifecycle.backfill_rfc。

    以 path slug 定址建 worktree → 派 `stages.rfc`（mode=backfill, require_delivered=True）——未过
    validate（delivered=false）→ 抛 BackfillError、不开 PR；过则开 draft PR（标「待人工补全」的段请评审
    补全后再转正，不自动 merge）。返回本轮事件（含 pr 号/摘要）。
    """
    slug = _slug_for(path=path)
    branch = f"{_BACKFILL_BRANCH_PREFIX}{slug}"
    worktree = prepare_worktree(work_dir=Path(work_dir), slug=slug, branch=branch, base=base)

    verdict = stages.rfc(
        backend=backend,
        worktree=worktree,
        mode=stages.MODE_BACKFILL,
        target=f"代码路径 `{path}`",
        branch=branch,
        detail=path,
        context_text=path,
        require_delivered=True,
    )
    if not verdict["delivered"]:
        raise BackfillError(
            f"drafter（backfill）自述未交付（疑未过 spec validate），不开 PR：`{path}`"
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


def _slug_for(*, path: str) -> str:
    """把代码 path 派生成分支安全的 slug（非字母数字折成单个连字符）。承旧 rfc_lifecycle._slug_for。"""
    raw = "".join(ch if ch.isalnum() else "-" for ch in str(path).strip("/"))
    slug = "-".join(seg for seg in raw.split("-") if seg)
    return slug or "root"


def _log(*, message: str) -> None:
    """backfill 进度打到 stderr（与 recipes.vigil 同通道）。"""
    print(message, file=sys.stderr, flush=True)
