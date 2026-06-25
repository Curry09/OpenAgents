"""spec 端到端验证指路牌：从一个 spec 组的组级 Overview 抽取 e2e 脚本并渲染指路牌。

issue #53（取代 RFC-0008/RFC-0013 的 rfc.py）：把「只懂文档结构、抽 e2e 线索」的职责从
RFC Markdown 解析迁到 spec 组。issue #69 起，设计叙述上移到组级 rust-RFC 9 段总览，
e2e 脚本线索改从 Overview（通常落在 Reference-level explanation）抽取。只读 spec 源数据，
不感知 git / GitHub / orchestrator（理念 10 解耦），任何缺失/异常都返回 None。
"""

from __future__ import annotations

import re
from pathlib import Path

from openagents.spec import model

# 集成测试脚本相对路径：scripts/….sh，取首个（与旧 rfc.py 同一约定）。
_SCRIPT_RE = re.compile(r"scripts/[^\s`)」]+\.sh")


def script_path_for_group(*, group_path: Path) -> str | None:
    """Scan a spec group's 组级 Overview 9 段 for the first `scripts/*.sh`.

    issue #69：脚本线索从组级总览（按 _OVERVIEW_SECTIONS 顺序，通常落在 Reference-level）
    抽取。组现为单文件 NNNN-slug.md；组不可读/无脚本→None。
    """
    if not group_path.is_file():
        return None
    try:
        group = model.load_group(path=group_path)
    except (OSError, ValueError):
        return None
    for _, attr in model._OVERVIEW_SECTIONS:
        match = _SCRIPT_RE.search(getattr(group.overview, attr) or "")
        if match:
            return match.group(0)
    return None


def signpost_for_group(*, group_path: Path) -> str | None:
    """Render the「## 端到端验证」signpost block for a spec group markdown file.

    有脚本则给可直接执行命令，否则指回 spec 组的 Task tests；详细步骤恒指向该组文件
    （单一来源，不复制全文）。组不可读时返回 None。
    """
    if not group_path.is_file():
        return None
    number = group_path.name[:4]
    spec_id = f"Spec-{number}"
    script = script_path_for_group(group_path=group_path)

    run_line = (
        f"- 跑：`bash {script}`"
        if script
        else f"- 跑：见 {spec_id} 总览的 Reference-level explanation"
    )
    detail_line = (
        f"- 详细手动步骤见 docs/specs/{group_path.name} 的组级总览 + 各 Task 的 `acceptance`"
    )
    return "\n".join(["## 端到端验证", run_line, detail_line])
