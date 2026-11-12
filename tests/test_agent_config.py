# Spec-0064/T1: agent_config configuration load (YAML parsing + jsonschema verify + tri-state value per gate + no zero gate guard +
# rifc:skip alert + override combined per warehouse) contract test.
#
# Hermetic: Write a temporary YaML with tmp_path to assert the resolution results/ error/ alarm, without touching the real warehouse/network.

from pathlib import Path

import pytest

from openagents.utils.agent_config import (
    FLOW_GENERATE_ONLY,
    FLOW_MINIMAL,
    FLOW_STANDARD,
    FLOW_V02,
    OWNER_AGENT,
    OWNER_SKIP,
    RELEASE_AUTO,
    RELEASE_MANUAL,
    AgentConfig,
    AgentConfigError,
    _default_template_text,
    default_config,
    load_agent_config,
    scaffold_default_config,
)


def _write(tmp_path: Path, text: str) -> Path:
    cfg = tmp_path / "openagents.yml"
    cfg.write_text(text, encoding="utf-8")
    return cfg


def test_missing_file_falls_back_to_builtin_defaults(tmp_path):
    # The whole saver - The file does not exist  →  all defaults (all parties STAGEs/ claude_code/ humanitarian rebase/ single warehouse).
    cfg = load_agent_config(path=tmp_path / "nope.yml")
    assert isinstance(cfg, AgentConfig)
    for stage in ("triage", "rfc", "architecture", "conflict", "ci", "e2e", "review", "merge"):
        assert cfg.stages.owner_of(stage=stage) == OWNER_AGENT
    assert cfg.agents.backend_for(role="implementer") == "claude_code"
    assert cfg.release.mode == RELEASE_MANUAL
    assert cfg.base == "main"
    assert cfg.interval == 60
    assert cfg.labels == ["openagents"]
    assert len(cfg.repos) == 1
    assert cfg.flow == FLOW_STANDARD
    assert cfg.repos[0].flow == FLOW_STANDARD


def test_minimal_flow_round_trips_into_repo_plan(tmp_path):
    cfg = load_agent_config(path=_write(tmp_path, "flow: minimal\n"))
    assert cfg.flow == FLOW_MINIMAL
    assert cfg.repos[0].flow == FLOW_MINIMAL


def test_generate_only_flow_round_trips_into_repo_plan(tmp_path):
    cfg = load_agent_config(path=_write(tmp_path, "flow: generate-only\n"))
    assert cfg.flow == FLOW_GENERATE_ONLY
    assert cfg.repos[0].flow == FLOW_GENERATE_ONLY
    assert cfg.agents.backend_for(role="executor") == "claude_code"


def test_v02_flow_and_roles_round_trip(tmp_path):
    cfg = load_agent_config(
        path=_write(
            tmp_path,
            "flow: v0.2\nagents:\n  developer: {backend: nexau}\n  spec_curator: {backend: nexau}\n",
        )
    )
    assert cfg.flow == FLOW_V02
    assert cfg.repos[0].flow == FLOW_V02
    assert cfg.agents.backend_for(role="developer") == "nexau"
    assert cfg.agents.backend_for(role="spec_curator") == "nexau"


def test_unknown_flow_is_rejected(tmp_path):
    with pytest.raises(AgentConfigError):
        load_agent_config(path=_write(tmp_path, "flow: committee\n"))


def test_empty_file_falls_back_to_defaults(tmp_path):
    cfg = load_agent_config(path=_write(tmp_path, ""))
    assert cfg.stages.owner_of(stage="merge") == OWNER_AGENT
    assert cfg == default_config() or cfg.stages.owner_of(stage="merge") == OWNER_AGENT


def test_minimal_config_overrides_only_named_stages(tmp_path):
    cfg = _write(
        tmp_path,
        """
version: 1
stages:
  e2e: skip
""",
    )
    conf = load_agent_config(path=cfg)
    assert conf.stages.owner_of(stage="e2e") == OWNER_SKIP
    # Uncovered phases still fall back to build the default agent.
    assert conf.stages.owner_of(stage="ci") == OWNER_AGENT
    assert conf.stages.owner_of(stage="review") == OWNER_AGENT


def test_full_config_agents_stages_release(tmp_path):
    cfg = _write(
        tmp_path,
        """
version: 1
agents:
  triager:     { backend: claude_code }
  implementer: { backend: codex }
  reviewer:    { backend: claude_code }
stages:
  triage:   agent
  rfc:      agent
  conflict: agent
  ci:       agent
  e2e:      skip
  review:   agent
  merge:    agent
release: auto
defaults: { interval: 120, base: develop, labels: [openagents, urgent] }
""",
    )
    conf = load_agent_config(path=cfg)
    assert conf.agents.backend_for(role="implementer") == "codex"
    assert conf.agents.backend_for(role="reviewer") == "claude_code"
    # Do not declare a role fall default.
    assert conf.agents.backend_for(role="replier") == "claude_code"
    assert conf.stages.owner_of(stage="e2e") == OWNER_SKIP
    assert conf.stages.owner_of(stage="review") == OWNER_AGENT
    assert conf.stages.owner_of(stage="merge") == OWNER_AGENT
    assert conf.release.mode == RELEASE_AUTO
    assert conf.interval == 120
    assert conf.base == "develop"
    assert conf.labels == ["openagents", "urgent"]


def test_review_skip_merge_agent_rejected(tmp_path):
    # No Zero Gate Guard: Unheard direct automatic blinding entry main reject.
    cfg = _write(
        tmp_path,
        """
stages:
  review: skip
  merge:  agent
""",
    )
    with pytest.raises(AgentConfigError, match="Automatic merge requires agent review"):
        load_agent_config(path=cfg)


def test_retired_human_owner_reports_exact_stage(tmp_path):
    cfg = _write(
        tmp_path,
        """
stages:
  review: skip
  merge:  human
""",
    )
    with pytest.raises(AgentConfigError, match="stages/merge.*retired"):
        load_agent_config(path=cfg)


def test_conflict_skip_rejected(tmp_path):
    cfg = _write(tmp_path, "stages:\n  conflict: skip\n")
    with pytest.raises(AgentConfigError):
        load_agent_config(path=cfg)


def test_merge_skip_rejected(tmp_path):
    cfg = _write(tmp_path, "stages:\n  merge: skip\n")
    with pytest.raises(AgentConfigError):
        load_agent_config(path=cfg)


def test_rfc_human_rejected(tmp_path):
    cfg = _write(tmp_path, "stages:\n  rfc: human\n")
    with pytest.raises(AgentConfigError, match="stages/rfc.*retired"):
        load_agent_config(path=cfg)


def test_hardgate_name_in_stages_rejected(tmp_path):
    cfg = _write(tmp_path, "stages:\n  round-cap: skip\n")
    with pytest.raises(AgentConfigError, match="Hard gate names"):
        load_agent_config(path=cfg)


def test_always_agent_stage_in_stages_rejected(tmp_path):
    cfg = _write(tmp_path, "stages:\n  implement: skip\n")
    with pytest.raises(AgentConfigError, match="Constant"):
        load_agent_config(path=cfg)


def test_rfc_skip_emits_warning(tmp_path):
    cfg = _write(tmp_path, "stages:\n  rfc: skip\n")
    with pytest.warns(UserWarning, match="rfc=skip"):
        conf = load_agent_config(path=cfg)
    assert conf.stages.owner_of(stage="rfc") == OWNER_SKIP


def test_per_repo_stage_override_merges(tmp_path):
    cfg = _write(
        tmp_path,
        """
stages:
  e2e: skip
repos:
  - path: .
  - path: ../other
    base: develop
    stages: { e2e: agent }
""",
    )
    conf = load_agent_config(path=cfg)
    a, b = conf.repos
    assert a.name == tmp_path.resolve().name
    # Repo-a inheritance top level e2e:skip.
    assert a.stages.owner_of(stage="e2e") == OWNER_SKIP
    assert a.base == "main"
    # repo-b over e2e: agent + base develop; the rest of the period is still the top/default.
    assert b.stages.owner_of(stage="e2e") == OWNER_AGENT
    assert b.stages.owner_of(stage="ci") == OWNER_AGENT
    assert b.base == "develop"
    assert b.path == (tmp_path / ".." / "other").resolve()


def test_per_repo_override_still_guarded(tmp_path):
    # No zeros are allowed after each warehouse - a legal top floor but a single warehouse has a zerostack set of projects.
    cfg = _write(
        tmp_path,
        """
repos:
  - path: .
    stages: { review: skip }
""",
    )
    with pytest.raises(AgentConfigError, match="Automatic merge requires agent review"):
        load_agent_config(path=cfg)


def test_unknown_top_level_key_rejected(tmp_path):
    cfg = _write(tmp_path, "bogus: 1\n")
    with pytest.raises(AgentConfigError):
        load_agent_config(path=cfg)


def test_unknown_agent_role_rejected(tmp_path):
    cfg = _write(tmp_path, "agents:\n  nobody: { backend: codex }\n")
    with pytest.raises(AgentConfigError):
        load_agent_config(path=cfg)


def test_invalid_release_rejected(tmp_path):
    cfg = _write(tmp_path, "release: sometimes\n")
    with pytest.raises(AgentConfigError):
        load_agent_config(path=cfg)


def test_top_level_non_mapping_rejected(tmp_path):
    cfg = _write(tmp_path, "- just\n- a\n- list\n")
    with pytest.raises(AgentConfigError):
        load_agent_config(path=cfg)


# --------------------------------------------------------------------------------------------------
# Spec-0067/T1: Pack the default configuration template +scaffold_default_config (defluent/ Zipple etc./ readable) contract test.
# --------------------------------------------------------------------------------------------------


def test_packaged_template_matches_builtin_defaults(tmp_path):
    # Floatproof hard gates: After load_agent_config has been deciphered, the default default_config() must be built at a semantic equivalent.
    # Defaults written in templates for dying (stagets all / claude_code / legal / intelval 60 / basemain /
    # labels [openagents]）with agent_config._DEFAULT_* It's the same thing in two.——The other side is not synchronized with the other.
    # This CI is red (Spec-0067 Drawbacks). Field by field and not whole-object equivalent: repos path relies on configuration drop point, and the  Drawbacks are not the only ones who can use the Zodiac Quotient.
    # Unlike the cwd benchmark for default_config() is more than the syntax stages/agents/release/defaults.
    cfg_path = tmp_path / ".openagents" / "openagents.yml"
    assert scaffold_default_config(path=cfg_path, force=False) is True
    cfg = load_agent_config(path=cfg_path)
    builtin = default_config()
    for stage in ("triage", "rfc", "architecture", "conflict", "ci", "e2e", "review", "merge"):
        assert (
            cfg.stages.owner_of(stage=stage) == builtin.stages.owner_of(stage=stage) == OWNER_AGENT
        )
    for role in ("triager", "drafter", "implementer", "reviewer", "replier", "deliver"):
        assert cfg.agents.backend_for(role=role) == "claude_code"
    assert cfg.release.mode == builtin.release.mode == RELEASE_MANUAL
    assert cfg.interval == builtin.interval == 60
    assert cfg.base == builtin.base == "main"
    assert cfg.labels == builtin.labels == ["openagents"]


def test_scaffold_writes_when_absent(tmp_path):
    # Target does not exist  →  Father directory, text template, return True; content is typed to the type.
    cfg_path = tmp_path / ".openagents" / "openagents.yml"
    assert not cfg_path.exists()
    assert scaffold_default_config(path=cfg_path, force=False) is True
    assert cfg_path.exists()
    assert cfg_path.read_text(encoding="utf-8") == _default_template_text()


def test_scaffold_is_idempotent_without_force(tmp_path):
    # Existing and force=False  →  returns False, never overwrites user changes.
    cfg_path = tmp_path / ".openagents" / "openagents.yml"
    scaffold_default_config(path=cfg_path, force=False)
    cfg_path.write_text("stages:\n  review: human\n", encoding="utf-8")
    assert scaffold_default_config(path=cfg_path, force=False) is False
    assert cfg_path.read_text(encoding="utf-8") == "stages:\n  review: human\n"


def test_scaffold_force_overwrites(tmp_path):
    # Force =True  →  Overwrites existing, returns True, resets the package template.
    cfg_path = tmp_path / ".openagents" / "openagents.yml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text("stages:\n  review: human\n", encoding="utf-8")
    assert scaffold_default_config(path=cfg_path, force=True) is True
    assert cfg_path.read_text(encoding="utf-8") == _default_template_text()


def test_scaffolded_file_loads_cleanly(tmp_path):
    # The generator must be capable of being deciphered by an existing loader (round-trip: scaffold thad).
    cfg_path = tmp_path / ".openagents" / "openagents.yml"
    scaffold_default_config(path=cfg_path, force=False)
    cfg = load_agent_config(path=cfg_path)
    assert isinstance(cfg, AgentConfig)
    assert cfg.stages.owner_of(stage="merge") == OWNER_AGENT


def test_architecture_owner_is_inferred_and_cannot_bypass_rfc(tmp_path) -> None:
    with pytest.warns(UserWarning):
        skipped = load_agent_config(path=_write(tmp_path, "stages:\n  rfc: skip\n"))
    assert skipped.stages.owner_of(stage="architecture") == OWNER_SKIP

    path = _write(tmp_path, "stages:\n  rfc: agent\n  architecture: skip\n")
    with pytest.raises(AgentConfigError, match="architecture:skip"):
        load_agent_config(path=path)


# Spec-0093/T1: required execution facts are a project policy, never an issue instruction.
def test_execution_evidence_requirement_is_carried_to_every_repo(tmp_path):
    cfg = load_agent_config(
        path=_write(
            tmp_path,
            "execution_evidence:\n  required: true\nrepos:\n  - path: one\n  - path: two\n",
        )
    )
    assert cfg.execution_evidence_required is True
    assert all(repo.execution_evidence_required for repo in cfg.repos)
    assert default_config().execution_evidence_required is False


@pytest.mark.parametrize("value", ["{}", "{required: yes, unexpected: true}", "{required: 'true'}"])
def test_execution_evidence_requirement_is_strict(tmp_path, value):
    with pytest.raises(AgentConfigError):
        load_agent_config(path=_write(tmp_path, f"execution_evidence: {value}\n"))
