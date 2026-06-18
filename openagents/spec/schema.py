"""spec JSON Schema —— Task / metadata / history 的结构校验单一真源。

Spec-0014/T1: 数据层 + JSON Schema + 依赖/入口声明

用 JSON Schema draft 2020-12 声明式描述源数据形状与枚举（决策 D8）：
- TASK_SCHEMA：tasks/T*.yaml 单个 Task 对象
- METADATA_SCHEMA：metadata.yaml
- HISTORY_SCHEMA：history/T*.yaml（Task 对象数组）

校验逻辑在 validate.py 调用这三个 schema；这里只放声明，保持单一真源。
"""

from __future__ import annotations

_DRAFT = "https://json-schema.org/draft/2020-12/schema"

# Spec-0014/T1：枚举集中定义，schema 与（未来）文档共用。
STATUS_VALUES = ("pending", "in-progress", "done", "abandoned")
PRIORITY_VALUES = ("P0", "P1", "P2", "P3")
RELATES_TYPE_VALUES = ("extends", "supersedes", "note")

# Spec-0014/T1：prose 字段（块标量承载的 Markdown）—— schema 里都是可选 string。
_PROSE_KEYS = (
    "summary",
    "motivation",
    "scope",
    "design",
    "interface",
    "tradeoffs",
    "acceptance",
    "tests",
    "references",
    "open-questions",
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
    "required": ["id", "title", "status", "priority"],
    "additionalProperties": False,
}

# Spec-0014/T1：组元数据 schema。
# Spec-0015/T1：增 summary（组级人话 TL;DR）。仅声明字段合法、类型 string、不设 required——
# 「非空」语义由 Spec-0015/T3 的 validate 语义链统一负责（缺字段/空串/纯空白一条消息）。
METADATA_SCHEMA: dict = {
    "$schema": _DRAFT,
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "issue": {"type": "integer"},
        "slug": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": ["title", "issue", "slug"],
    "additionalProperties": False,
}

# Spec-0014/T1：历史文件 schema —— Task 对象数组（每项是一个完整快照）。
HISTORY_SCHEMA: dict = {
    "$schema": _DRAFT,
    "type": "array",
    "items": TASK_SCHEMA,
}
