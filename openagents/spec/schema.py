"""Define the JSON Schema for Spec frontmatter and tasks."""

from __future__ import annotations

_DRAFT = "https://json-schema.org/draft/2020-12/schema"

# Spec-0014/T1: Element-Closed Definition, Schema shares with (future) documents.
STATUS_VALUES = ("pending", "in-progress", "done", "abandoned")
PRIORITY_VALUES = ("P0", "P1", "P2", "P3")
RELATES_TYPE_VALUES = ("extends", "supersedes", "note")

# Assue #69: Task is degraded to work breakup, with only two short lines of proste.
# Redesign description to group Overview 9 ( body, not frontmotter, therefore not here schema).
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

# Spec-0014/T1: Schema for a single Task object. id/title/status/priority will be filled, the rest is optional.
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
    # #69: Fill in each line (single writer ownership) + acceptance (verifiable).
    "required": ["id", "title", "status", "priority", "files", "acceptance"],
    "additionalProperties": False,
}

# Spec-0055/T2: Group e2e (Results Validation Intention + How to Test)
# Acceptance [} Skinned as {intent, method} - `intent` with a single intent (to check what, RFC gate freeze) `method`
# A prose measurement (how to measure, human-speech steps,** do not contain precise orders** - commands are knocked by executor when running). Cut off form
# Element count (executor self-checking tool path selection, no longer assigned by morphology) and acceptance (and go to method prose).
# Declaration of structure and type, intent/method is not emptied by validate._e2e_checks syntax. The whole block** is optional** - not included in required,
# There is no e2e piece of spec no behavior change.
E2E_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "intent": {"type": "string"},
        "method": {"type": "string"},
    },
    "required": ["intent", "method"],
    "additionalProperties": False,
}

ARCHITECTURE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "objective": {"type": "string", "minLength": 1},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "non-goals": {"type": "array", "items": {"type": "string"}},
        "candidates": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "layer": {"type": "string", "minLength": 1},
                    "boundary": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "tradeoffs": {"type": "string"},
                },
                "required": ["id", "layer", "boundary", "evidence", "tradeoffs"],
                "additionalProperties": False,
            },
        },
        "selected": {"type": "string", "minLength": 1},
        "affected-components": {"type": "array", "items": {"type": "string"}},
        "failure-modes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "objective",
        "constraints",
        "non-goals",
        "candidates",
        "selected",
        "affected-components",
        "failure-modes",
    ],
    "additionalProperties": False,
}

VERIFICATION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "behavior-cases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "polarity": {"enum": ["positive", "negative"]},
                    "stimulus": {"type": "string", "minLength": 1},
                    "expected": {"type": "string", "minLength": 1},
                    "observation": {"type": "string", "minLength": 1},
                },
                "required": ["id", "polarity", "stimulus", "expected", "observation"],
                "additionalProperties": False,
            },
        },
        "repository-invariants": {"type": "array", "items": {"type": "string"}},
        "exemptions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["behavior-cases", "repository-invariants", "exemptions"],
    "additionalProperties": False,
}

# 2026-06-24 spec-markdown-form: group markdown file frontmatter scheme (replaces metada+ history).
# List of group metadata number/title/issue/slug + questions (each re-use TASK_SCHEMA).
GROUP_FRONTMATTER_SCHEMA: dict = {
    "$schema": _DRAFT,
    "type": "object",
    "properties": {
        "number": {"type": ["string", "integer"]},
        "title": {"type": "string"},
        "issue": {"type": "integer"},
        "slug": {"type": "string"},
        # Spec-0015: Group Verbale TL; DR. Schema only declares type; non-empty is forced by _summary_checks of Validate.
        "summary": {"type": "string"},
        # Spec-0072/T1: Group-level "Atom Delivery" declaration (optional). Non-empty i.e. exemption > 6 Task soft cap warning
        # (validate._task_count_checks); Schema only states type, semantics are processed by valaidate.
        "oversized-rationale": {"type": "string"},
        # Spec-0040/T1: Group e2e rough plan (optional, not required - no e2e spec no behavior change).
        "e2e": E2E_SCHEMA,
        "architecture": ARCHITECTURE_SCHEMA,
        "verification": VERIFICATION_SCHEMA,
        "tasks": {"type": "array", "items": TASK_SCHEMA},
    },
    "required": ["number", "title", "issue", "slug", "tasks"],
    "additionalProperties": False,
}
