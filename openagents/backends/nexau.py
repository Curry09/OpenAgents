# Spec-0085/T3
"""NexAU coding backend for Anthropic-compatible Messages gateways."""

from __future__ import annotations

import importlib.resources
import json
import os
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import MethodType
from typing import Any

from openagents.backends.base import AgentResult
from openagents.runtime.invocation import redact_text

MODEL_ENV = "OPENAGENTS_NEXAU_MODEL"
BASE_URL_ENV = "OPENAGENTS_NEXAU_BASE_URL"
API_KEY_ENV = "OPENAGENTS_NEXAU_API_KEY"
MAX_CONTEXT_ENV = "OPENAGENTS_NEXAU_MAX_CONTEXT_TOKENS"
MAX_OUTPUT_ENV = "OPENAGENTS_NEXAU_MAX_OUTPUT_TOKENS"

_DEFAULT_MAX_CONTEXT = 262_144
_DEFAULT_MAX_OUTPUT = 32_768


class NexAUBackend:
    """Run one non-interactive coding agent inside its assigned worktree."""

    name = "nexau"

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._model = model or _required_env(MODEL_ENV)
        self._base_url = _sdk_base_url(base_url or _required_env(BASE_URL_ENV))
        self._api_key = api_key or _required_env(API_KEY_ENV)

    def run(self, *, work_dir: Path, task: str, context: str) -> AgentResult:
        """Run NexAU with local-shell tools and return its stop-tool payload."""
        resolved = Path(work_dir).resolve()
        from nexau import Agent, AgentConfig  # noqa: PLC0415 - optional runtime dependency

        config_path = Path(
            str(importlib.resources.files("openagents").joinpath("data", "nexau", "agent.yaml"))
        )
        config = AgentConfig.from_yaml(config_path=config_path)
        _bind_sandbox_work_dir(config=config, work_dir=resolved)
        config.max_context_tokens = _positive_int(MAX_CONTEXT_ENV, _DEFAULT_MAX_CONTEXT)
        config.llm_config.model = self._model
        config.llm_config.base_url = self._base_url
        config.llm_config.api_key = self._api_key
        config.llm_config.max_tokens = _positive_int(MAX_OUTPUT_ENV, _DEFAULT_MAX_OUTPUT)
        config.llm_config.api_type = "anthropic_chat_completion"
        config.llm_config.stream = False
        # WIS requires Bearer auth. NexAU 0.4.1 also constructs an old httpx.Timeout that the
        # installed Anthropic SDK's httpx2 client cannot consume, so use a plain seconds value.
        config.llm_config.to_client_kwargs = MethodType(_client_kwargs, config.llm_config)
        audit_dir = os.environ.get("OPENAGENTS_NEXAU_AUDIT_DIR", "").strip()
        tracer = None
        if audit_dir:
            from nexau.archs.tracer.adapters import (  # noqa: PLC0415
                InMemoryTracer,
            )

            tracer = InMemoryTracer()
            config.tracers.append(tracer)
        try:
            output = Agent(config=config).run(message=_prompt(task=task, context=context))
        except Exception as exc:
            if audit_dir:
                _write_audit(
                    audit_dir=Path(audit_dir),
                    model=self._model,
                    work_dir=resolved,
                    task=task,
                    context=context,
                    output="",
                    error={"type": type(exc).__name__, "message": str(exc)},
                    traces=tracer.dump_traces() if tracer is not None else [],
                    secrets=(self._api_key,),
                )
            raise
        text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        if audit_dir:
            _write_audit(
                audit_dir=Path(audit_dir),
                model=self._model,
                work_dir=resolved,
                task=task,
                context=context,
                output=text,
                error=None,
                traces=tracer.dump_traces() if tracer is not None else [],
                secrets=(self._api_key,),
            )
        status = subprocess.run(
            ["git", "-C", str(resolved), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        return AgentResult(
            changed=bool(status.stdout.strip()),
            summary=text[:2000],
            raw_output=text,
        )


def _client_kwargs(llm_config: Any) -> dict[str, Any]:
    """Return WIS-compatible Anthropic SDK construction arguments."""
    return {
        "auth_token": llm_config.api_key,
        "base_url": llm_config.base_url,
        "max_retries": llm_config.max_retries,
        "timeout": llm_config.timeout or 300.0,
    }


def _sdk_base_url(url: str) -> str:
    """Anthropic SDK appends ``/v1/messages``; normalize a direct ``.../v1`` endpoint."""
    normalized = url.rstrip("/")
    return normalized[:-3] if normalized.endswith("/v1") else normalized


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少 NexAU backend 环境变量 {name}")
    return value


def _bind_sandbox_work_dir(*, config: Any, work_dir: Path) -> None:
    """Bind one agent config to its worktree without mutating process-global state."""
    sandbox = getattr(config, "sandbox_config", None)
    if sandbox is None:
        raise RuntimeError("NexAU AgentConfig 缺少 sandbox_config，无法隔离工作区")
    if hasattr(sandbox, "model_copy"):
        config.sandbox_config = sandbox.model_copy(update={"work_dir": str(work_dir)})
    elif hasattr(sandbox, "copy"):  # pragma: no cover - NexAU 0.4 uses Pydantic v2
        config.sandbox_config = sandbox.copy(update={"work_dir": str(work_dir)})
    else:
        raise RuntimeError("NexAU sandbox_config 不支持不可变 work_dir 绑定")


def _prompt(*, task: str, context: str) -> str:
    return (
        "严格执行下面的 OpenAgents 角色契约。当前 Agent sandbox work_dir 是唯一可写工作区；"
        "不得访问父目录、其它 worktree、宿主路径或挂载外路径。最终必须调用 complete_task，"
        "并把角色要求的单行 JSON 原样放入 result，不要加 Markdown 围栏。\n\n"
        f"任务：\n{task}\n\n上下文：\n{context}"
    )


def _write_audit(
    *,
    audit_dir: Path,
    model: str,
    work_dir: Path,
    task: str,
    context: str,
    output: str,
    error: dict[str, str] | None,
    traces: list[dict[str, Any]],
    secrets: tuple[str, ...] = (),
) -> None:
    """Persist a complete local role trace without credentials or provider configuration."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid.uuid4().hex[:8]}"
    path = audit_dir / f"{run_id}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "recorded_at": datetime.now(UTC).isoformat(),
                "model": _redact_audit_value(model, secrets=secrets),
                "work_dir": str(work_dir),
                "task": _redact_audit_value(task, secrets=secrets),
                "context": _redact_audit_value(context, secrets=secrets),
                "output": _redact_audit_value(output, secrets=secrets),
                "error": _redact_audit_value(error, secrets=secrets),
                "traces": _redact_audit_value(traces, secrets=secrets),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _redact_audit_value(value: Any, *, secrets: tuple[str, ...] = ()) -> Any:
    """Redact configured and directly supplied credentials recursively."""
    if isinstance(value, str):
        redacted = redact_text(value)
        for secret in secrets:
            if secret:
                redacted = redacted.replace(secret, "${OPENAGENTS_NEXAU_API_KEY}")
        return redacted
    if isinstance(value, dict):
        return {
            str(key): _redact_audit_value(item, secrets=secrets)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_audit_value(item, secrets=secrets) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_audit_value(str(value), secrets=secrets)


__all__ = ["NexAUBackend"]
