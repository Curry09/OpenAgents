"""spec JSON Schema —— 组 markdown frontmatter / Task 的结构校验单一真源。

Spec-0014/T1（2026-06-24 spec-markdown-form 更新）：
用 JSON Schema draft 2020-12 声明式描述源数据形状与枚举（决策 D8）：
- TASK_SCHEMA：frontmatter `tasks` 列表里的单个 Task 对象
- GROUP_FRONTMATTER_SCHEMA：组 markdown 文件的 frontmatter（number/title/issue/slug/summary/tasks）

校验逻辑在 validate.py 调用这两个 schema；这里只放声明，保持单一真源。
"""

from __future__ import annotations

_DRAFT = "https://json-schema.org/draft/2020-12/schema"

# Spec-0014/T1：枚举集中定义，schema 与（未来）文档共用。
STATUS_VALUES = ("pending", "in-progress", "done", "abandoned")
PRIORITY_VALUES = ("P0", "P1", "P2", "P3")
RELATES_TYPE_VALUES = ("extends", "supersedes", "note")

# issue #69：Task 退化为工作分解行，只保留两个一行短 prose（进 frontmatter）。
# 重设计叙述上移到组级 Overview 9 段（正文，不进 frontmatter，故不在此 schema）。
_PROSE_KEYS = (
    "scope",
    "acceptance",
)

_RELATES_TO_SCHEMA = {
    "type": "object",
    "properties": {
        "ref": {"type": "string"},
        "type": {"enum": list(RELATES_TYPE_VALUES)},
    },
    "required": ["ref", "type"],
    "additionalProperties": False,
}

# Spec-0014/T1：单个 Task 对象的 schema。id/title/status/priority 必填，其余可选。
TASK_SCHEMA: dict = {
    "$schema": _DRAFT,
    "type": "object",
    "properties": {
        "id": {"type": "string", "pattern": r"^T[0-9A-Za-z]+$"},
        "title": {"type": "string"},
        "status": {"enum": list(STATUS_VALUES)},
        "priority": {"enum": list(PRIORITY_VALUES)},
        "tags": {"type": "array", "items": {"type": "string"}},
        "depends-on": {"type": "array", "items": {"type": "string"}},
        "relates-to": {"type": "array", "items": _RELATES_TO_SCHEMA},
        "parallel": {"type": "boolean"},
        "files": {"type": "array", "items": {"type": "string"}},
        "version": {"type": "integer", "minimum": 1},
        "updated": {"type": "string"},
        "change-reason": {"type": "string"},
        "supersedes": {"type": "array", "items": {"type": "string"}},
        "split-from": {"type": ["string", "null"]},
        "merged-from": {"type": "array", "items": {"type": "string"}},
        "derived-from": {"type": "array", "items": {"type": "string"}},
        **{key: {"type": "string"} for key in _PROSE_KEYS},
    },
    # issue #69：files（单一 writer 所有权）+ acceptance（可验证）每行必填。
    "required": ["id", "title", "status", "priority", "files", "acceptance"],
    "additionalProperties": False,
}

# 2026-06-24 spec-markdown-form：组 markdown 文件的 frontmatter schema（取代 metadata + history）。
# 组元数据 number/title/issue/slug + tasks 列表（每项复用 TASK_SCHEMA）。
GROUP_FRONTMATTER_SCHEMA: dict = {
    "$schema": _DRAFT,
    "type": "object",
    "properties": {
        "number": {"type": ["string", "integer"]},
        "title": {"type": "string"},
        "issue": {"type": "integer"},
        "slug": {"type": "string"},
        # Spec-0015：组级人话 TL;DR。schema 只声明类型；非空由 validate 的 _summary_checks 强制。
        "summary": {"type": "string"},
        "tasks": {"type": "array", "items": TASK_SCHEMA},
    },
    "required": ["number", "title", "issue", "slug", "tasks"],
    "additionalProperties": False,
}
