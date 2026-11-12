"""# Spec-0074/T1: single forge distribution layer (Little detection) / Constant zero IO / Configuration segment verification / command in.

Untouch real gh/ network: github side only to pure string function (merge_command_text), gita side only until configuure
(No request); cli merge-pr laid a stake through the Monkey Patch forge.
"""

from __future__ import annotations

import argparse

import pytest

from openagents.utils import forge, github


@pytest.fixture(autouse=True)
def _reset_forge():
    """Each module level selection that uses the example to clear the forge is free of string."""
    forge.reset()
    yield
    forge.reset()


# --------------------------------------------------------------------------------------------------
# Commission with constant.
# --------------------------------------------------------------------------------------------------


def test_default_delegates_to_github(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # No configuration  →  inertity found back github
    assert forge.active_forge() == forge.FORGE_GITHUB
    assert forge.merge_command_text(pr_number=7) == "gh pr merge 7 --merge"
    assert forge.merge_verify_command_text(pr_number=7) == "gh pr view 7 --json state"


def test_discovery_crosses_linked_worktree_git_file(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    worktree = root / ".openagents" / "worktrees" / "issue-7"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /tmp/common/worktrees/issue-7\n", encoding="utf-8")
    config_dir = root / ".openagents"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "openagents.yml").write_text(
        "forge: gitea\ngitea:\n  base_url: http://gitea.local\n  owner: owner\n  repo: repo\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(worktree)
    assert forge.active_forge() == forge.FORGE_GITEA
    assert forge.merge_command_text(pr_number=7) == "openagents merge-pr --pr 7"


def test_discovery_resolves_external_linked_worktree(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    external = tmp_path / "external-worktree"
    (root / ".git" / "worktrees" / "issue-8").mkdir(parents=True)
    (root / ".openagents").mkdir()
    (root / ".openagents" / "openagents.yml").write_text(
        "forge: gitea\ngitea:\n  base_url: http://gitea.local\n  owner: owner\n  repo: repo\n",
        encoding="utf-8",
    )
    external.mkdir()
    (external / ".git").write_text(
        f"gitdir: {root / '.git' / 'worktrees' / 'issue-8'}\n", encoding="utf-8"
    )

    monkeypatch.chdir(external)
    assert forge.active_forge() == forge.FORGE_GITEA


def test_constants_reexported_statically():
    # Constants and error types are static re-export (IOs) and are defined in the same way as github.py.
    assert forge.DISCOVERY_LABEL == github.DISCOVERY_LABEL
    assert forge.PROCESS_LABELS == github.PROCESS_LABELS
    assert forge.GithubError is github.GithubError


def test_configure_gitea_delegates(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    forge.configure(
        name="gitea", settings={"base_url": "http://gitea.local", "owner": "o", "repo": "r"}
    )
    assert forge.active_forge() == forge.FORGE_GITEA
    assert forge.merge_command_text(pr_number=7) == "openagents merge-pr --pr 7"


def test_configure_unknown_forge_raises():
    with pytest.raises(github.GithubError):
        forge.configure(name="gitlab")


def test_configure_gitea_missing_settings_raises():
    with pytest.raises(github.GithubError):
        forge.configure(name="gitea", settings={"base_url": "http://x"})


def test_missing_driver_function_has_actionable_error():
    forge.configure(name="github")
    with pytest.raises(AttributeError, match="implement public operations in both drivers"):
        _ = forge.not_a_real_function


# --------------------------------------------------------------------------------------------------
# Inertity Discovery (cwd  → streasure root, read . openagents/openagents.yml, forge/gitea, two keys).
# --------------------------------------------------------------------------------------------------


def _write_config(base, text):
    (base / ".openagents").mkdir(parents=True, exist_ok=True)
    (base / ".openagents" / "openagents.yml").write_text(text, encoding="utf-8")


_GITEA_YML = "forge: gitea\ngitea:\n  base_url: http://localhost:3000\n  owner: o\n  repo: r\n"


def test_lazy_discovery_reads_config(monkeypatch, tmp_path):
    _write_config(tmp_path, _GITEA_YML)
    monkeypatch.chdir(tmp_path)
    assert forge.active_forge() == forge.FORGE_GITEA


def test_lazy_discovery_walks_up_to_repo_root(monkeypatch, tmp_path):
    _write_config(tmp_path, _GITEA_YML)
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert forge.active_forge() == forge.FORGE_GITEA


def test_lazy_discovery_stops_at_git_root(monkeypatch, tmp_path):
    # Configures the root of the guit repository without recognition (configuring only the in-house, consistent with the semantics of the cwd-repository).
    _write_config(tmp_path, _GITEA_YML)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.chdir(repo)
    assert forge.active_forge() == forge.FORGE_GITHUB


def test_broken_yaml_falls_back_to_github(monkeypatch, tmp_path):
    _write_config(tmp_path, "forge: [broken\n  - :")
    monkeypatch.chdir(tmp_path)
    assert forge.active_forge() == forge.FORGE_GITHUB


def test_unknown_forge_value_falls_back_to_github(monkeypatch, tmp_path):
    _write_config(tmp_path, "forge: gitlab\n")
    monkeypatch.chdir(tmp_path)
    assert forge.active_forge() == forge.FORGE_GITHUB


def test_gitea_declared_but_incomplete_fails_loud(monkeypatch, tmp_path):
    # Forge=gitea but gitea is missing and wrongs are reported loudly (no silent gh hitting a Gitea project).
    _write_config(tmp_path, "forge: gitea\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(github.GithubError):
        forge.active_forge()


# --------------------------------------------------------------------------------------------------
# forge/gitea configuration (schema + cross-field guard + resolved fax) for agent_config.
# --------------------------------------------------------------------------------------------------


def _load(tmp_path, text):
    from openagents.utils.agent_config import load_agent_config

    path = tmp_path / "openagents.yml"
    path.write_text(text, encoding="utf-8")
    return load_agent_config(path=path)


def test_agent_config_defaults_to_github(tmp_path):
    config = _load(tmp_path, "version: 1\n")
    assert config.forge == forge.FORGE_GITHUB
    assert config.gitea is None


def test_agent_config_parses_gitea_section(tmp_path):
    config = _load(tmp_path, _GITEA_YML)
    assert config.forge == forge.FORGE_GITEA
    assert config.gitea == {"base_url": "http://localhost:3000", "owner": "o", "repo": "r"}


def test_agent_config_rejects_gitea_without_section(tmp_path):
    from openagents.utils.agent_config import AgentConfigError

    with pytest.raises(AgentConfigError, match="gitea segment"):
        _load(tmp_path, "forge: gitea\n")


def test_agent_config_rejects_bad_gitea_shape(tmp_path):
    from openagents.utils.agent_config import AgentConfigError

    with pytest.raises(AgentConfigError):
        _load(tmp_path, "forge: gitea\ngitea:\n  base_url: http://x\n")  # owner/repo missing


def test_agent_config_rejects_unknown_forge(tmp_path):
    from openagents.utils.agent_config import AgentConfigError

    with pytest.raises(AgentConfigError):
        _load(tmp_path, "forge: gitlab\n")


# --------------------------------------------------------------------------------------------------
# stages.merge platform command injects +cli merge-pr exit.
# --------------------------------------------------------------------------------------------------


def test_stages_merge_injects_platform_commands(monkeypatch, tmp_path):
    from openagents.recipes import stages

    monkeypatch.chdir(tmp_path)  # forge → github
    monkeypatch.setattr(stages.gates, "assert_merge_allowed", lambda *, pr_number, head_sha: None)
    seen = {}

    def _fake_run_agent(agent_module, *, backend, **kw):
        seen.update(kw)
        return {"merged": True, "summary": "ok"}

    monkeypatch.setattr(stages.engine, "run_agent", _fake_run_agent)
    stages.merge(backend=object(), pr_number=42, head_sha="abc", work_dir="/wt", context_text="")
    # The platform command for Spec-0074/T1: merger is injected into the current forge (github side, the original gh command, no change in behaviour).
    assert seen["merge_command"] == "gh pr merge 42 --merge --match-head-commit abc"
    assert seen["verify_command"] == "gh pr view 42 --json state"


def test_cli_merge_pr_forwards_to_forge(monkeypatch, capsys):
    from openagents import cli

    forge.configure(name="github")
    calls = []
    monkeypatch.setattr(forge, "is_merged", lambda *, pr_number: bool(calls), raising=False)
    monkeypatch.setattr(
        forge,
        "merge_pr",
        lambda *, pr_number, method, head_sha: calls.append((pr_number, method, head_sha)),
        raising=False,
    )
    ns = argparse.Namespace(pr=42, method="merge", head_sha="abc")
    code = cli._cmd_merge_pr(ns, ctx=None)
    assert code == 0
    assert calls == [(42, "merge", "abc")]
    assert "MERGED" in capsys.readouterr().out


def test_cli_merge_pr_idempotent_when_already_merged(monkeypatch, capsys):
    from openagents import cli

    forge.configure(name="github")
    merged_calls = []
    monkeypatch.setattr(forge, "is_merged", lambda *, pr_number: True, raising=False)
    monkeypatch.setattr(
        forge, "merge_pr", lambda *, pr_number, method: merged_calls.append(1), raising=False
    )
    code = cli._cmd_merge_pr(argparse.Namespace(pr=42, method="merge"), ctx=None)
    assert code == 0
    assert merged_calls == []  # Merged  →  Not anymore POST (Queue)
    assert "MERGED" in capsys.readouterr().out
