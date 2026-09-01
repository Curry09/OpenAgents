# Spec-0060/T2: runtime.engine —— 新栈唯一「派 agent」入口（元信息放 docstring 之上，像 argparse # Author）

"""Fill an agent's prompt placeholders, dispatch to a backend, and return validated output.

调用示例：
    >>> out = run_agent(triager, backend=claude, work_dir=wt, issue_body=body)
    >>> out["verdict"]
    'actionable'

新栈唯一的「派 agent」入口，也是 recipe 调 agent 的唯一方式。职责三步、**不认识任何具体流程**
（换一套 agent/recipe 零改动，理念 10 机制与策略分离）：

1. 读 `agent_module.PROMPT`（`string.Template`）→ `substitute(**placeholders)` 填占位符成 task；
2. `backend.run(work_dir=..., task=prompt, context=...)` 派后端跑（backend 抽象见 backends/base.py）；
3. 解析 agent 输出**末行 JSON**、按 `agent_module.OUTPUT_SCHEMA`（键→类型 dict）校验 → 返回 dict。

保留字占位符：`work_dir`（必填，派给 backend 的工作目录）、`context`（选填，issue 正文/PR 历史等
上下文串）由 engine 从 placeholders 取出交给 backend；其余键都用于填 PROMPT 模板。

Exports:
    run_agent -- 填占位符 → 派 backend → 校验末行 JSON → 返回结构化 dict。
    AgentOutputError -- agent 输出不合 OUTPUT_SCHEMA 契约（坏 JSON / 缺键 / 类型不符）时抛出。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openagents.runtime import token_usage, tool_usage


class AgentOutputError(Exception):
    """Raise when an agent's output breaks the OUTPUT_SCHEMA contract.

    Spec-0060/T2: agent 输出不合契约（坏 JSON / 末行非 JSON 对象 / 缺 schema 键 / 键类型不符）时抛出。
    """


def run_agent(agent_module: Any, *, backend: Any, **placeholders: Any) -> dict[str, Any]:
    """填 agent 的 PROMPT 占位符 → 派 backend → 解析并校验末行 JSON → 返回结构化 dict。

    `work_dir`（必填）与 `context`（选填，缺省空串）是保留字占位符：从 placeholders 取出交给
    `backend.run`，其余键用于 `agent_module.PROMPT.substitute`（Template 忽略多余键，故保留字
    即便未出现在模板里也无碍）。返回值是按 `agent_module.OUTPUT_SCHEMA` 校验通过的 dict。
    """
    if "work_dir" not in placeholders:
        raise AgentOutputError("run_agent 缺少必填保留字占位符 work_dir")
    work_dir = placeholders.pop("work_dir")
    context = placeholders.pop("context", "")
    module_name = getattr(agent_module, "__name__", agent_module.__class__.__name__)
    role = str(module_name).rsplit(".", 1)[-1]
    backend_name = str(getattr(backend, "name", backend.__class__.__name__))

    prompt = agent_module.PROMPT.substitute(**placeholders)
    _assert_single_copy(task=prompt, context=context, values=placeholders, role=role)
    result = None
    parsed: dict[str, Any] | None = None
    status = "backend_error"
    error: str | None = None
    try:
        result = backend.run(work_dir=work_dir, task=prompt, context=context)
        status = "protocol_error"
        # Display summaries are bounded; machine protocol parsing uses the complete backend result.
        parsed = _parse_last_json(text=getattr(result, "protocol_output", result.summary))
        _validate(payload=parsed, schema=agent_module.OUTPUT_SCHEMA)
        tool_events = getattr(result, "tool_events", ())
        if tool_events:
            reason = parsed.get("lookup_exception_reason", "")
            tool_usage.record(
                work_dir=work_dir,
                role=role,
                tool_names=tool_events,
                lookup_exception_reason=reason if isinstance(reason, str) else "",
            )
        status = "success"
        return parsed
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        token_usage.record(
            work_dir=work_dir,
            role=role,
            backend=backend_name,
            status=status,
            usage=getattr(result, "usage", None),
        )
        _record_role_invocation(
            role=role,
            prompt=prompt,
            context=str(context),
            placeholders={key: str(value) for key, value in placeholders.items()},
            structured=parsed,
            status=status,
            error=error,
        )


def _record_role_invocation(
    *,
    role: str,
    prompt: str,
    context: str,
    placeholders: dict[str, str],
    structured: object,
    status: str,
    error: str | None,
) -> None:
    """Spec-0049/T6：fail-open 把填好的 prompt/context 与 structured 写入 ROLE_RUNS_DIR。"""
    root_raw = os.environ.get("ROLE_RUNS_DIR", "").strip()
    if not root_raw:
        return
    try:
        root = Path(root_raw)
        root.mkdir(parents=True, exist_ok=True)
        invocation_id = uuid.uuid4().hex
        captured = datetime.now(UTC).isoformat()
        stamp = captured.replace(":", "").replace("-", "")[:15]
        payload = {
            "schema_version": 1,
            "invocation_id": invocation_id,
            "run_id": os.environ.get("AUTO_DESIGNER_RUN_ID") or None,
            "round": _optional_int(raw=os.environ.get("AUTO_DESIGNER_ROUND", "")),
            "side": "delivery",
            "role": role,
            "subject": {
                "kind": "issue" if placeholders.get("issue_number") else "round",
                "id": placeholders.get("issue_number") or os.environ.get("AUTO_DESIGNER_ROUND", ""),
            },
            "replayable": role != "implementer",
            "input": {
                "prompt": _redact(text=prompt),
                "context": _redact(text=context),
                "placeholders": placeholders,
            },
            "output": {"structured": structured, "status": status, "error": error},
            "env": {
                "model": os.environ.get("ANTHROPIC_MODEL") or os.environ.get("OPENAGENTS_MODEL"),
                "agent_def_pin": None,
                "captured_at": captured,
            },
        }
        path = root / f"{stamp}_{role}_{invocation_id[:8]}.json"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        return


def _optional_int(*, raw: str) -> int | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _redact(*, text: str) -> str:
    out = text
    for name in (
        "GITEA_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        value = os.environ.get(name, "").strip()
        if value:
            out = out.replace(value, f"${{{name}}}")
    return out


def _parse_last_json(*, text: str) -> dict[str, Any]:
    """从 agent 输出里取**末行 JSON 对象**：自底向上找第一行能 json 解析成 dict 的非空行。

    对末尾偶有的空白/句号等噪声宽容（自底向上扫），但要求确有一行是 JSON 对象——否则 raise。
    """
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise AgentOutputError(f"agent 输出末尾未找到合法 JSON 对象：{text[-200:]!r}")


_DYNAMIC_TEXT_MIN = 32


def _normalized_text(*, text: str) -> str:
    """Normalize whitespace for deterministic prompt-overlap checks."""
    return re.sub(r"\s+", " ", text).strip()


def _assert_single_copy(*, task: str, context: str, values: dict[str, Any], role: str) -> None:
    """Reject non-trivial dynamic payloads duplicated across task and context.

    Spec-0081/T1: ``task`` owns stable role instructions and short routing scalars while
    ``context`` owns issue bodies, comments, specs, feedback, snapshots, and evidence.  Check both
    rendered string placeholders and context paragraphs so a new role cannot silently reintroduce
    the old double-payload pattern.  Short values are ignored to allow identifiers and branch names
    to appear naturally in both halves.
    """
    normalized_task = _normalized_text(text=task)
    normalized_context = _normalized_text(text=context)
    if not normalized_context:
        return

    candidates = [value for value in values.values() if isinstance(value, str)]
    candidates.extend(re.split(r"\n\s*\n", context))
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalized_text(text=candidate)
        if len(normalized) < _DYNAMIC_TEXT_MIN or normalized in seen:
            continue
        seen.add(normalized)
        if normalized in normalized_task and normalized in normalized_context:
            excerpt = normalized[:120]
            raise AgentOutputError(f"{role} 的动态 prompt 载荷同时出现在 task/context：{excerpt!r}")


def _validate(*, payload: dict[str, Any], schema: dict[str, type]) -> None:
    """按 OUTPUT_SCHEMA（键→Python 类型）校验：缺键 / 类型不符 → 抛 AgentOutputError。

    极简键→类型校验（见 spec Unresolved：值域约束先留 agent prompt 自述 + 后续按需硬化）。
    bool 是 int 的子类，故对 int 期望显式排除 bool，避免 True 冒充数字混过。
    """
    for key, expected in schema.items():
        if key not in payload:
            raise AgentOutputError(f"agent 输出缺少 schema 键 {key!r}：{payload!r}")
        value = payload[key]
        if expected is int and isinstance(value, bool):
            raise AgentOutputError(f"agent 输出键 {key!r} 期望 int，得到 bool：{value!r}")
        if not isinstance(value, expected):
            raise AgentOutputError(
                f"agent 输出键 {key!r} 类型不符：期望 {expected.__name__}，"
                f"得到 {type(value).__name__}（{value!r}）"
            )
