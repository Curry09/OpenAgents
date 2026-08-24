"""# Spec-0074/T1: forge 分发层单测——委托 / 惰性发现 / 常量零 IO / 配置段校验 / 命令注入。

不触真实 gh/网络：github 侧只调纯字符串函数（merge_command_text），gitea 侧只到 configure 为止
（不发请求）；cli merge-pr 经 monkeypatch forge 打桩。
"""

from __future__ import annotations

import argparse

import pytest

from openagents.utils import forge, github


@pytest.fixture(autouse=True)
def _reset_forge():
    """每个用例前后清掉 forge 的模块级选择，互不串台。"""
    forge.reset()
    yield
    forge.reset()


# --------------------------------------------------------------------------------------------------
# 委托与常量。
# --------------------------------------------------------------------------------------------------


def test_default_delegates_to_github(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # 无配置 → 惰性发现回落 github
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
    # 常量与错误类型是静态 re-export（import 时零 IO），且与 github.py 同一份定义。
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
    with pytest.raises(AttributeError, match="事实契约"):
        _ = forge.not_a_real_function


# --------------------------------------------------------------------------------------------------
# 惰性发现（cwd → 仓库根，读 .openagents/openagents.yml 的 forge/gitea 两键）。
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
    # 配置在 git 仓库根之上 → 不认（配置只认本仓的，与 gh 的 cwd→仓库绑定语义一致）。
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
    # forge=gitea 但 gitea 段缺失 → 大声报错（绝不静默拿 gh 打一个 Gitea 项目）。
    _write_config(tmp_path, "forge: gitea\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(github.GithubError):
        forge.active_forge()


# --------------------------------------------------------------------------------------------------
# agent_config 的 forge/gitea 配置段（schema + 跨字段守卫 + resolved 透传）。
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

    with pytest.raises(AgentConfigError, match="gitea 段"):
        _load(tmp_path, "forge: gitea\n")


def test_agent_config_rejects_bad_gitea_shape(tmp_path):
    from openagents.utils.agent_config import AgentConfigError

    with pytest.raises(AgentConfigError):
        _load(tmp_path, "forge: gitea\ngitea:\n  base_url: http://x\n")  # 缺 owner/repo


def test_agent_config_rejects_unknown_forge(tmp_path):
    from openagents.utils.agent_config import AgentConfigError

    with pytest.raises(AgentConfigError):
        _load(tmp_path, "forge: gitlab\n")


# --------------------------------------------------------------------------------------------------
# stages.merge 的平台命令注入 + cli merge-pr 出口。
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
    # Spec-0074/T1: merger 的平台命令按当前 forge 注入（github 侧即原 gh 命令，行为零变化）。
    assert seen["merge_command"] == "gh pr merge 42 --merge"
    assert seen["verify_command"] == "gh pr view 42 --json state"


def test_cli_merge_pr_forwards_to_forge(monkeypatch, capsys):
    from openagents import cli

    forge.configure(name="github")
    calls = []
    monkeypatch.setattr(forge, "is_merged", lambda *, pr_number: bool(calls), raising=False)
    monkeypatch.setattr(
        forge,
        "merge_pr",
        lambda *, pr_number, method: calls.append((pr_number, method)),
        raising=False,
    )
    ns = argparse.Namespace(pr=42, method="merge")
    code = cli._cmd_merge_pr(ns, ctx=None)
    assert code == 0
    assert calls == [(42, "merge")]
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
    assert merged_calls == []  # 已合并 → 不再 POST（幂等）
    assert "MERGED" in capsys.readouterr().out
