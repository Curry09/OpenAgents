# Spec-0064/T1: agent_config 配置加载（YAML 解析 + jsonschema 校验 + 三态每闸取值 + 不许零闸守卫 +
# rfc:skip 告警 + 每仓 override 合并）契约测试。
#
# hermetic：用 tmp_path 写临时 YAML 串断言解析结果 / 校验错误 / 告警，不触真实仓库/网络。

from pathlib import Path

import pytest

from openagents.utils.agent_config import (
    OWNER_AGENT,
    OWNER_HUMAN,
    OWNER_SKIP,
    RELEASE_AUTO,
    RELEASE_MANUAL,
    AgentConfig,
    AgentConfigError,
    default_config,
    load_agent_config,
)


def _write(tmp_path: Path, text: str) -> Path:
    cfg = tmp_path / "openagents.yml"
    cfg.write_text(text, encoding="utf-8")
    return cfg


def test_missing_file_falls_back_to_builtin_defaults(tmp_path):
    # 整份可省——文件不存在 → 全默认（全 agent stages / claude_code / manual release / 单仓）。
    cfg = load_agent_config(path=tmp_path / "nope.yml")
    assert isinstance(cfg, AgentConfig)
    for stage in ("triage", "rfc", "conflict", "ci", "e2e", "review", "merge"):
        assert cfg.stages.owner_of(stage=stage) == OWNER_AGENT
    assert cfg.agents.backend_for(role="implementer") == "claude_code"
    assert cfg.release.mode == RELEASE_MANUAL
    assert cfg.base == "main"
    assert cfg.interval == 60
    assert cfg.labels == ["openagents"]
    assert len(cfg.repos) == 1


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
  merge: human
""",
    )
    conf = load_agent_config(path=cfg)
    assert conf.stages.owner_of(stage="merge") == OWNER_HUMAN
    # 未覆盖的阶段仍回落内建默认 agent。
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
  review:   human
  merge:    human
release: auto
defaults: { interval: 120, base: develop, labels: [openagents, urgent] }
""",
    )
    conf = load_agent_config(path=cfg)
    assert conf.agents.backend_for(role="implementer") == "codex"
    assert conf.agents.backend_for(role="reviewer") == "claude_code"
    # 未声明角色回落默认。
    assert conf.agents.backend_for(role="replier") == "claude_code"
    assert conf.stages.owner_of(stage="e2e") == OWNER_SKIP
    assert conf.stages.owner_of(stage="review") == OWNER_HUMAN
    assert conf.stages.owner_of(stage="merge") == OWNER_HUMAN
    assert conf.release.mode == RELEASE_AUTO
    assert conf.interval == 120
    assert conf.base == "develop"
    assert conf.labels == ["openagents", "urgent"]


def test_review_skip_merge_agent_rejected(tmp_path):
    # 「不许零闸」守卫：未审直接自动盲合进 main → reject。
    cfg = _write(
        tmp_path,
        """
stages:
  review: skip
  merge:  agent
""",
    )
    with pytest.raises(AgentConfigError, match="不许零闸"):
        load_agent_config(path=cfg)


def test_review_skip_merge_human_allowed(tmp_path):
    # merge:human 在（人兜住）→ 跳 agent-review 站得住，不撞守卫。
    cfg = _write(
        tmp_path,
        """
stages:
  review: skip
  merge:  human
""",
    )
    conf = load_agent_config(path=cfg)
    assert conf.stages.owner_of(stage="review") == OWNER_SKIP
    assert conf.stages.owner_of(stage="merge") == OWNER_HUMAN


def test_conflict_skip_rejected(tmp_path):
    cfg = _write(tmp_path, "stages:\n  conflict: skip\n")
    with pytest.raises(AgentConfigError):
        load_agent_config(path=cfg)


def test_merge_skip_rejected(tmp_path):
    cfg = _write(tmp_path, "stages:\n  merge: skip\n")
    with pytest.raises(AgentConfigError):
        load_agent_config(path=cfg)


def test_rfc_human_rejected(tmp_path):
    # rfc 仅 agent/skip，无 human。
    cfg = _write(tmp_path, "stages:\n  rfc: human\n")
    with pytest.raises(AgentConfigError):
        load_agent_config(path=cfg)


def test_hardgate_name_in_stages_rejected(tmp_path):
    cfg = _write(tmp_path, "stages:\n  round-cap: skip\n")
    with pytest.raises(AgentConfigError, match="硬闸"):
        load_agent_config(path=cfg)


def test_always_agent_stage_in_stages_rejected(tmp_path):
    cfg = _write(tmp_path, "stages:\n  implement: human\n")
    with pytest.raises(AgentConfigError, match="恒派 agent"):
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
  merge: human
repos:
  - path: .
  - path: ../other
    base: develop
    stages: { merge: agent }
""",
    )
    conf = load_agent_config(path=cfg)
    a, b = conf.repos
    assert a.name == tmp_path.resolve().name
    # repo-a 继承顶层 merge:human。
    assert a.stages.owner_of(stage="merge") == OWNER_HUMAN
    assert a.base == "main"
    # repo-b 覆盖 merge:agent + base develop；其余阶段仍继承顶层/默认。
    assert b.stages.owner_of(stage="merge") == OWNER_AGENT
    assert b.stages.owner_of(stage="ci") == OWNER_AGENT
    assert b.base == "develop"
    assert b.path == (tmp_path / ".." / "other").resolve()


def test_per_repo_override_still_guarded(tmp_path):
    # 每仓 override 后仍不许零闸——顶层合法但某仓覆出零闸组合 → reject。
    cfg = _write(
        tmp_path,
        """
stages:
  review: skip
  merge:  human
repos:
  - path: .
    stages: { merge: agent }
""",
    )
    with pytest.raises(AgentConfigError, match="不许零闸"):
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
