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

# Spec-0028/T1：PR 正文内嵌总览摘要——只取信息密度最高的三段（是什么 / 为什么 / 怎么做），
# 每段超过行数上限即截断，避免正文膨胀淹没 Closes/指路牌（Reference-level / Drawbacks 缓解）。
_DIGEST_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Summary", "summary"),
    ("Motivation", "motivation"),
    ("Reference-level explanation", "reference_level"),
)
# 每段保守的行数上限（Unresolved questions：初定保守值，可后续按 PR 观感调）。
_DIGEST_MAX_LINES = 12
# 超行截断的续接提示——明确告知评审者去 spec 文件读完整内容。
_DIGEST_TRUNCATED_HINT = "…（完整见 spec 文件）"


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


def overview_digest_for_group(*, group_path: Path) -> str | None:
    """Spec-0028/T1：抽组级 9 段总览里信息密度最高的三段，渲染成 PR 正文的「## spec 总览」块。

    与 signpost_for_group 并列同质（只懂 spec 文档结构、为 PR 正文抽取、缺失返 None，不感知
    git / GitHub / orchestrator，理念 10 解耦）。取 Summary / Motivation / Reference-level，
    每段按 _DIGEST_MAX_LINES 截断（超出保留前 N 行 + 续接提示），三段各以 `### <段名>` 分隔。
    group_path 不是文件 / load_group 抛 OSError|ValueError → None（零回归：PR 正文逐字节同今天）。
    """
    if not group_path.is_file():
        return None
    try:
        group = model.load_group(path=group_path)
    except (OSError, ValueError):
        return None

    blocks: list[str] = []
    for heading, attr in _DIGEST_SECTIONS:
        body = _truncate_section(text=getattr(group.overview, attr) or "")
        if body:
            blocks.append(f"### {heading}\n{body}")
    if not blocks:
        # 三段全空（罕见，如总览尚未填写）：不渲染空块，回退到无 digest（零回归）。
        return None

    header = f"## spec 总览（摘自 docs/specs/{group_path.name}）"
    return "\n\n".join([header, *blocks])


def _truncate_section(*, text: str) -> str:
    """把一段总览正文按 _DIGEST_MAX_LINES 截断；超出保留前 N 行并追加续接提示。空段返回空串。"""
    stripped = text.strip("\n")
    if not stripped.strip():
        return ""
    lines = stripped.split("\n")
    if len(lines) <= _DIGEST_MAX_LINES:
        return stripped
    return "\n".join([*lines[:_DIGEST_MAX_LINES], _DIGEST_TRUNCATED_HINT])


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
