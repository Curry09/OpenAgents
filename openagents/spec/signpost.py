"""spec 端到端验证指路牌：从一个 spec 组的 Task `tests` 字段抽取 e2e 脚本并渲染指路牌。

issue #53（取代 RFC-0008/RFC-0013 的 rfc.py）：把「只懂文档结构、抽 e2e 线索」的职责从
RFC Markdown 解析迁到 spec 组——脚本线索现来自各 Task 的 `tests` prose 字段。只读 spec
源数据，不感知 git / GitHub / orchestrator（理念 10 解耦），任何缺失/异常都返回 None。
"""

from __future__ import annotations

import re
from pathlib import Path

from openagents.spec import model

# 集成测试脚本相对路径：scripts/….sh，取首个（与旧 rfc.py 同一约定）。
_SCRIPT_RE = re.compile(r"scripts/[^\s`)」]+\.sh")


def script_path_for_group(*, group_dir: Path) -> str | None:
    """Scan a spec group's Task `tests` fields for the first `scripts/*.sh` path.

    issue #53：供 implement 转正前实跑（取代 rfc.script_path_for）。组不可读/无脚本→None。
    """
    if not group_dir.is_dir():
        return None
    try:
        group = model.load_group(group_dir=group_dir)
    except (OSError, ValueError):
        return None
    for task in group.tasks:
        match = _SCRIPT_RE.search(task.tests or "")
        if match:
            return match.group(0)
    return None


def signpost_for_group(*, group_dir: Path) -> str | None:
    """Render the「## 端到端验证」signpost block for a spec group.

    issue #53（取代 rfc.signpost_for）：有脚本则给可直接执行命令，否则指回 spec 组的
    Task tests；详细步骤恒指向该组（单一来源，不复制全文）。组不可读时返回 None。
    """
    if not group_dir.is_dir():
        return None
    number = group_dir.name[:4]
    spec_id = f"Spec-{number}"
    script = script_path_for_group(group_dir=group_dir)

    run_line = f"- 跑：`bash {script}`" if script else f"- 跑：见 {spec_id} 各 Task 的 `tests`"
    detail_line = f"- 详细手动步骤见 docs/specs/{group_dir.name}/ 各 Task 的 `tests` / `acceptance`"
    return "\n".join(["## 端到端验证", run_line, detail_line])
