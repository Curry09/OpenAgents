import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from openagents.backends.nexau import (
    NexAUBackend,
    _bind_sandbox_work_dir,
    _positive_int,
    _sdk_base_url,
    _write_audit,
)


def test_messages_endpoint_is_normalized_for_anthropic_sdk():
    assert _sdk_base_url("https://gateway.example/api/v1") == "https://gateway.example/api"
    assert _sdk_base_url("https://gateway.example/api/") == "https://gateway.example/api"


def test_explicit_constructor_does_not_require_environment():
    backend = NexAUBackend(model="m", base_url="https://gateway/api/v1", api_key="secret")
    assert backend.name == "nexau"


def test_positive_int_falls_back_on_invalid_values(monkeypatch):
    monkeypatch.setenv("LIMIT", "bad")
    assert _positive_int("LIMIT", 12) == 12
    monkeypatch.setenv("LIMIT", "34")
    assert _positive_int("LIMIT", 12) == 34
    monkeypatch.setenv("LIMIT", "0")
    assert _positive_int("LIMIT", 12) == 12


def test_missing_constructor_environment_fails_cleanly(monkeypatch):
    for name in (
        "OPENAGENTS_NEXAU_MODEL",
        "OPENAGENTS_NEXAU_BASE_URL",
        "OPENAGENTS_NEXAU_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="OPENAGENTS_NEXAU_MODEL"):
        NexAUBackend()


def test_sandbox_work_dir_is_bound_on_config_without_global_environment_mutation(
    monkeypatch, tmp_path
):
    class _Sandbox:
        def __init__(self, work_dir="old"):
            self.work_dir = work_dir

        def model_copy(self, *, update):
            return _Sandbox(work_dir=update["work_dir"])

    config = SimpleNamespace(sandbox_config=_Sandbox())
    monkeypatch.setenv("SANDBOX_WORK_DIR", "/tmp/another-worktree")

    _bind_sandbox_work_dir(config=config, work_dir=tmp_path)

    assert config.sandbox_config.work_dir == str(tmp_path)
    assert "SANDBOX_WORK_DIR" in os.environ
    assert os.environ["SANDBOX_WORK_DIR"] == "/tmp/another-worktree"


def test_nexau_agent_definition_loads_packaged_system_prompt():
    path = Path(__file__).parents[1] / "openagents" / "data" / "nexau" / "agent.yaml"
    text = path.read_text(encoding="utf-8")
    assert "system_prompt: ./system.md" in text
    assert "system_prompt_type: file" in text


def test_nexau_audit_redacts_direct_and_configured_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAGENTS_NEXAU_API_KEY", "env-secret")
    _write_audit(
        audit_dir=tmp_path,
        model="model",
        work_dir=tmp_path / "repo",
        task="direct-secret",
        context="env-secret",
        output="direct-secret",
        error={"message": "env-secret"},
        traces=[{"content": "direct-secret"}],
        secrets=("direct-secret",),
    )

    records = [path for path in tmp_path.glob("*.json")]
    assert len(records) == 1
    payload = json.loads(records[0].read_text(encoding="utf-8"))
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "direct-secret" not in rendered
    assert "env-secret" not in rendered
    assert "${OPENAGENTS_NEXAU_API_KEY}" in rendered
