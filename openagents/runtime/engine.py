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
3. 从 agent 输出提取完整 JSON、按角色声明的 JSON Schema 校验；格式违约时在隔离临时目录中修复一次。

保留字占位符：`work_dir`（必填，派给 backend 的工作目录）、`context`（选填，issue 正文/PR 历史等
上下文串）由 engine 从 placeholders 取出交给 backend；其余键都用于填 PROMPT 模板。

Exports:
    run_agent -- 填占位符 → 派 backend → 校验末行 JSON → 返回结构化 dict。
    AgentOutputError -- agent 输出不合 OUTPUT_SCHEMA 契约（坏 JSON / 缺键 / 类型不符）时抛出。
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from openagents.runtime import invocation, token_usage, tool_usage


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

    # Spec-0087: role identity/issue come from the runner, never from a log payload.
    from openagents.observations.evidence import prepare
    from openagents.observations.gaps import collect_requests

    issue_number = placeholders.get("issue_number")
    if issue_number is None and role == "drafter":
        match = re.match(r"issue #(\d+)", str(placeholders.get("target", "")))
        issue_number = int(match[1]) if match else None
    observation_scope = None
    if type(issue_number) is int and issue_number > 0:
        try:
            observation_scope = prepare(work_dir=Path(work_dir), issue=issue_number, role=role)
        except Exception as exc:
            context += f"\nObservation infrastructure unavailable: {type(exc).__name__}. Do not infer missing runtime events."
        if observation_scope is not None:
            context += "\n\n" + observation_scope["context"]

    output_schema = _output_json_schema(agent_module=agent_module)
    prompt = agent_module.PROMPT.substitute(**placeholders)
    _assert_single_copy(task=prompt, context=context, values=placeholders, role=role)
    prompt = _with_machine_contract(prompt=prompt, schema=output_schema)
    result = None
    parsed: dict[str, Any] | None = None
    status = "backend_error"
    error: str | None = None
    try:
        result = backend.run(work_dir=work_dir, task=prompt, context=context)
        status = "protocol_error"
        # Display summaries are bounded; machine protocol parsing uses the complete backend result.
        protocol_output = getattr(result, "protocol_output", result.summary)
        try:
            parsed = _parse_and_validate(text=protocol_output, schema=output_schema)
        except AgentOutputError as primary_error:
            # Spec-0091: advisory roles may explicitly opt out of costly repair calls.
            if not getattr(agent_module, "REPAIR_OUTPUT", True):
                raise
            parsed = _repair_protocol_output(
                backend=backend,
                backend_name=backend_name,
                role=role,
                schema=output_schema,
                output=protocol_output,
                primary_error=primary_error,
                placeholders=placeholders,
                audit_work_dir=Path(work_dir),
            )
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
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        collect_requests(scope=observation_scope)
        token_usage.record(
            work_dir=work_dir,
            role=role,
            backend=backend_name,
            status=status,
            usage=getattr(result, "usage", None),
        )
        invocation.record(
            role=role,
            backend=backend_name,
            prompt=prompt,
            context=context,
            placeholders=placeholders,
            structured=parsed,
            status=status,
            error=error,
        )


def _parse_last_json(*, text: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract the last complete JSON object, including multiline/fenced output.

    Every ``{`` is considered as a possible object boundary with ``raw_decode``.  When a schema is
    supplied, a valid outer protocol object wins over later nested objects.  This avoids the old
    line-oriented failure where pretty-printed JSON made an inner array item look like the result.
    """
    decoder = json.JSONDecoder()
    candidates: list[tuple[int, dict[str, Any]]] = []
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append((match.start(), value))
    if not candidates:
        raise AgentOutputError(f"agent 输出中未找到完整 JSON 对象：{text[-200:]!r}")
    if schema is not None:
        validator = Draft202012Validator(schema)
        valid = [candidate for candidate in candidates if validator.is_valid(candidate[1])]
        if valid:
            return valid[-1][1]
        required = set(schema.get("required") or ())
        # Prefer the object that resembles the outer envelope most closely so validation reports
        # the real contract mismatch rather than a later nested object.
        candidates.sort(key=lambda item: (len(required.intersection(item[1])), item[0]))
    return candidates[-1][1]


def _parse_and_validate(*, text: str, schema: dict[str, Any]) -> dict[str, Any]:
    payload = _parse_last_json(text=text, schema=schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.path)
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        if first.validator == "required" and not first.absolute_path:
            missing = next(
                (key for key in schema.get("required", ()) if key not in payload),
                "<unknown>",
            )
            raise AgentOutputError(f"agent 输出缺少 schema 键 {missing!r}：{payload!r}")
        raise AgentOutputError(f"agent 输出不符合 JSON Schema（{location}）：{first.message}")
    return payload


def _output_json_schema(*, agent_module: Any) -> dict[str, Any]:
    explicit = getattr(agent_module, "OUTPUT_JSON_SCHEMA", None)
    if explicit is not None:
        Draft202012Validator.check_schema(explicit)
        return explicit
    properties = {
        key: {"type": _json_type(expected)} for key, expected in agent_module.OUTPUT_SCHEMA.items()
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": list(properties),
        "properties": properties,
        "additionalProperties": True,
    }


def _with_machine_contract(*, prompt: str, schema: dict[str, Any]) -> str:
    return (
        f"{prompt.rstrip()}\n\n"
        "【机器输出契约】最终响应必须是满足下列 JSON Schema 的一个完整 JSON 对象。"
        "可以单行或多行，但不得放入 Markdown 代码围栏，不得在对象后追加说明。\n"
        f"{json.dumps(schema, ensure_ascii=False, sort_keys=True)}\n"
    )


def _json_type(expected: type) -> str:
    mapping = {
        str: "string",
        bool: "boolean",
        int: "integer",
        float: "number",
        list: "array",
        dict: "object",
    }
    try:
        return mapping[expected]
    except KeyError as exc:
        raise TypeError(f"unsupported OUTPUT_SCHEMA type: {expected!r}") from exc


_REPAIR_OUTPUT_LIMIT = 65_536


def _repair_protocol_output(
    *,
    backend: Any,
    backend_name: str,
    role: str,
    schema: dict[str, Any],
    output: str,
    primary_error: AgentOutputError,
    placeholders: dict[str, Any],
    audit_work_dir: Path,
) -> dict[str, Any]:
    """Run one serialization-only retry in a disposable directory.

    The retry cannot touch the delivery worktree.  It may only re-express claims already present in
    the original answer; the same schema is validated again and failure remains fail-closed.
    """
    repair_prompt = (
        "你是机器协议格式修复器。不得调查仓库、不得调用工具、不得新增事实或证据。"
        "只把 ORIGINAL_OUTPUT 中已经存在的内容重排为满足 JSON_SCHEMA 的一个 JSON 对象。"
        "字段名明显为同义缩写时按 schema 字段名归一化；缺失且无法无损恢复的字符串填空串、数组填空数组，"
        "不要猜测语义。只输出 JSON，不要 Markdown、解释或代码围栏。\n\n"
        f"VALIDATION_ERROR:\n{primary_error}\n\n"
        f"JSON_SCHEMA:\n{json.dumps(schema, ensure_ascii=False, sort_keys=True)}\n\n"
        f"ORIGINAL_OUTPUT:\n{output[-_REPAIR_OUTPUT_LIMIT:]}"
    )
    repair_result = None
    repaired: dict[str, Any] | None = None
    repair_status = "backend_error"
    repair_error: str | None = None
    with tempfile.TemporaryDirectory(prefix="openagents-protocol-repair-") as temporary:
        repair_dir = Path(temporary)
        subprocess.run(
            ["git", "init", "--quiet", str(repair_dir)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            repair_result = backend.run(work_dir=repair_dir, task=repair_prompt, context="")
            repair_status = "protocol_error"
            repaired = _parse_and_validate(
                text=getattr(repair_result, "protocol_output", repair_result.summary),
                schema=schema,
            )
            repair_status = "success"
            return repaired
        except Exception as exc:
            repair_error = f"{type(exc).__name__}: {exc}"
            raise AgentOutputError(
                f"agent 原始输出协议错误且格式修复失败：原始={primary_error}; 修复={repair_error}"
            ) from exc
        finally:
            repair_role = f"{role}_protocol_repair"
            token_usage.record(
                work_dir=audit_work_dir,
                role=repair_role,
                backend=backend_name,
                status=repair_status,
                usage=getattr(repair_result, "usage", None),
            )
            invocation.record(
                role=repair_role,
                backend=backend_name,
                prompt=repair_prompt,
                context="",
                placeholders=placeholders,
                structured=repaired,
                status=repair_status,
                error=repair_error,
            )


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
