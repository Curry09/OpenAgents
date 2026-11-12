# Spec-0060/T2: runtime.engine - The only "partagain" entrance to the New Inn (Measure message above docstring, like aragparse #Author)

"""Render a role prompt, dispatch it to a backend, and validate its result.

The engine reserves work_dir and context for backend invocation. Other fields
fill the role template. Extract the final JSON object, check the declared
schema, and allow one serialization-only repair for invalid output.

Exports:
    run_agent: Run a role and return its validated result.
    AgentOutputError: Report an invalid or unrecoverable role result.
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

    Spec-0060/T2: agent output is thrown when it is not contractual (bad JSON/ end line does not match JSON object/ missing schema key/ key type).
    """


def run_agent(agent_module: Any, *, backend: Any, **placeholders: Any) -> dict[str, Any]:
    """Fill in ant’s PROMPT placeholder Queue back Queend Queue and verify the endline JSON Quest returns structured dict.

    `work_dir`(Prescribed) with `context`(check-in, default empty) is a reserved placeholder: from placeholders Take it out and hand it over.
    `backend.run`, the rest of the key is used for `agent_module.PROMPT.substitute` (Template ignores the extra key, so keep the word)
    Not even in the template. Return values are verified as `agent_module.OUTPUT_SCHEMA`.
    """
    if "work_dir" not in placeholders:
        raise AgentOutputError("run_agent Missing required placeholder work_dir")
    work_dir = placeholders.pop("work_dir")
    context = placeholders.pop("context", "")
    module_name = getattr(agent_module, "__name__", agent_module.__class__.__name__)
    role = str(module_name).rsplit(".", 1)[-1]
    backend_name = str(getattr(backend, "name", backend.__class__.__name__))

    # Spec-0087: role identity/issue come from the runner, never from a log payload.
    from openagents.observations.evidence import prepare
    from openagents.observations.execution_contracts import ExecutionContractUnavailable
    from openagents.observations.gaps import collect_requests
    from openagents.runtime.context import execution_required

    issue_number = placeholders.get("issue_number")
    if issue_number is None and role == "drafter":
        match = re.match(r"issue #(\d+)", str(placeholders.get("target", "")))
        issue_number = int(match[1]) if match else None
    observation_scope = None
    if type(issue_number) is int and issue_number > 0:
        try:
            required = execution_required(issue_number=issue_number)
            observation_scope = prepare(
                work_dir=Path(work_dir),
                issue=issue_number,
                role=role,
                execution_required=required,
            )
        except ExecutionContractUnavailable:
            # Spec-0093/T2: a required-condition fault stops before calling the model.
            raise
        except Exception as exc:
            context += f"\nObservation infrastructure unavailable: {type(exc).__name__}. Do not infer missing runtime events."
        if observation_scope is not None:
            context += "\n\n" + observation_scope["context"]
            if observation_scope.get("execution_contract_context"):
                context += "\n\n" + observation_scope["execution_contract_context"]

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
        raise AgentOutputError(f"No complete JSON object in agent output: {text[-200:]!r}")
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
            raise AgentOutputError(f"Agent output missing schema key {missing!r}：{payload!r}")
        raise AgentOutputError(
            f"Agent output does not match JSON Schema ({location}): {first.message}"
        )
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
        "Machine output contract: return one complete JSON object conforming to this JSON Schema. "
        "One or multiple lines are allowed. Do not use Markdown fences or append explanations.\n"
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
        "Repair the machine output format. Do not inspect the repository, call tools, or add facts or evidence. "
        "Rearrange only the content already present in ORIGINAL_OUTPUT into one JSON object conforming to JSON_SCHEMA. "
        "Normalize obvious synonymous abbreviations to the schema field names. Use an empty string or array when a missing value cannot be recovered without loss. "
        "Do not guess meaning. Return only JSON, without Markdown, explanations, or code fences.\n\n"
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
                f"Agent output violated its protocol and repair failed: original={primary_error}; repair={repair_error}"
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
            raise AgentOutputError(f"{role} Dynamic propt load appears in task/context:{excerpt!r}")


def _validate(*, payload: dict[str, Any], schema: dict[str, type]) -> None:
    """Press OUTPUT_SCHEMA (key  → Python type) to verify: missing / type does not match AgentoutError.

    Very simple keys type verification (see spec Unresolved: a value limit is left in ant programt + subsequent structification).
    Bool is a subcategory of int, so expect int to exclude the bool in a visible way, and avoid the fact that True is impersonating a number overlay.
    """
    for key, expected in schema.items():
        if key not in payload:
            raise AgentOutputError(f"Agent output missing schema key {key!r}：{payload!r}")
        value = payload[key]
        if expected is int and isinstance(value, bool):
            raise AgentOutputError(f"Agent output key {key!r} expected int, got bool: {value!r}")
        if not isinstance(value, expected):
            raise AgentOutputError(
                f"Agent output key {key!r} has the wrong type: expected {expected.__name__}，"
                f"Got it. {type(value).__name__}（{value!r}）"
            )
