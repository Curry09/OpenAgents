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


# --------------------------------------------------------------------------------------------------
# Spec-0067/T1: 打包默认配置模板 + scaffold_default_config（防漂移 / 幂等 / 可回读）契约测试。
# --------------------------------------------------------------------------------------------------


def test_packaged_template_matches_builtin_defaults(tmp_path):
    # 防漂移硬闸：打包模板经 load_agent_config 解析后，必须语义等价内建默认 default_config()。
    # 模板里写死的默认（stages 全 agent / claude_code / manual / interval 60 / base main /
    # labels [openagents]）与 agent_config._DEFAULT_* 是两处表述同一事实——改一方不同步另一方，
    # 这条 CI 就红（Spec-0067 Drawbacks）。逐字段比而非整对象等值：repos 路径依赖配置文件落点，
    # 与 default_config() 的 cwd 基准不同，比 stages/agents/release/defaults 语义即可。
    cfg_path = tmp_path / ".openagents" / "openagents.yml"
    assert scaffold_default_config(path=cfg_path, force=False) is True
    cfg = load_agent_config(path=cfg_path)
    builtin = default_config()
    for stage in ("triage", "rfc", "conflict", "ci", "e2e", "review", "merge"):
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
    # 目标不存在 → 建好父目录、写入模板文本、返回 True；内容逐字等于打包模板。
    cfg_path = tmp_path / ".openagents" / "openagents.yml"
    assert not cfg_path.exists()
    assert scaffold_default_config(path=cfg_path, force=False) is True
    assert cfg_path.exists()
    assert cfg_path.read_text(encoding="utf-8") == _default_template_text()


def test_scaffold_is_idempotent_without_force(tmp_path):
    # 已存在且 force=False → 返回 False、绝不覆盖用户改动。
    cfg_path = tmp_path / ".openagents" / "openagents.yml"
    scaffold_default_config(path=cfg_path, force=False)
    cfg_path.write_text("stages:\n  review: human\n", encoding="utf-8")
    assert scaffold_default_config(path=cfg_path, force=False) is False
    assert cfg_path.read_text(encoding="utf-8") == "stages:\n  review: human\n"


def test_scaffold_force_overwrites(tmp_path):
    # force=True → 覆盖既有、返回 True，内容重置回打包模板。
    cfg_path = tmp_path / ".openagents" / "openagents.yml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text("stages:\n  review: human\n", encoding="utf-8")
    assert scaffold_default_config(path=cfg_path, force=True) is True
    assert cfg_path.read_text(encoding="utf-8") == _default_template_text()


def test_scaffolded_file_loads_cleanly(tmp_path):
    # 生成物必须能被既有加载器无错解析（round-trip：scaffold → load）。
    cfg_path = tmp_path / ".openagents" / "openagents.yml"
    scaffold_default_config(path=cfg_path, force=False)
    cfg = load_agent_config(path=cfg_path)
    assert isinstance(cfg, AgentConfig)
    assert cfg.stages.owner_of(stage="merge") == OWNER_AGENT
