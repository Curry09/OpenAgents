# Spec-0027/T1: fleet_config 配置加载（YAML 解析 + jsonschema 校验 + 默认合并）契约测试。
#
# 纯解析、无 I/O 副作用（除读配置文件外）；用 tmp_path 写临时 YAML，断言合并后的
# RepoPlan 列表与各类非法输入的清晰报错。不触达 git / gh / 子进程。

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from openagents.utils.fleet_config import FleetConfigError, RepoPlan, load_fleet_config


def _write(tmp_path: Path, text: str) -> Path:
    cfg = tmp_path / "fleet.yml"
    cfg.write_text(text, encoding="utf-8")
    return cfg


def test_full_config_merges_defaults_and_overrides(tmp_path):
    # repo-a 全用默认；repo-b 覆盖 interval/labels/base；repo-c 显式 name + hold。
    cfg = _write(
        tmp_path,
        """
defaults:
  interval: 60
  labels: [openagents]
  base: main
  hold: null
repos:
  - path: repo-a
  - path: repo-b
    interval: 120
    labels: [openagents, urgent]
    base: develop
  - path: sub/repo-c
    name: c
    hold: spec,merge
""",
    )
    plans = load_fleet_config(path=cfg)
    assert [p.name for p in plans] == ["repo-a", "repo-b", "c"]

    a, b, c = plans
    # repo-a：默认下沉。
    assert a.interval == 60
    assert a.labels == ["openagents"]
    assert a.base == "main"
    assert a.hold is None
    # path 绝对化（相对路径以配置文件所在目录为基准）。
    assert a.path == (tmp_path / "repo-a").resolve()
    assert a.path.is_absolute()

    # repo-b：每仓库覆盖生效，未覆盖的 hold 仍取默认。
    assert b.interval == 120
    assert b.labels == ["openagents", "urgent"]
    assert b.base == "develop"
    assert b.hold is None
    assert b.name == "repo-b"  # name 缺省取 basename

    # repo-c：显式 name 优先；hold 覆盖。
    assert c.name == "c"
    assert c.hold == "spec,merge"
    assert c.path == (tmp_path / "sub" / "repo-c").resolve()


def test_defaults_block_optional_uses_builtin_defaults(tmp_path):
    # 不写 defaults 段：内建默认（interval=60 / labels=[openagents] / base=main / hold=None）。
    cfg = _write(tmp_path, "repos:\n  - path: only\n")
    (plan,) = load_fleet_config(path=cfg)
    assert plan.interval == 60
    assert plan.labels == ["openagents"]
    assert plan.base == "main"
    assert plan.hold is None
    assert plan.name == "only"


def test_home_tilde_path_expanded(tmp_path):
    cfg = _write(tmp_path, "repos:\n  - path: ~/work/repo-h\n")
    (plan,) = load_fleet_config(path=cfg)
    assert plan.path == (Path.home() / "work" / "repo-h").resolve()
    assert plan.name == "repo-h"


def test_absolute_path_kept(tmp_path):
    target = tmp_path / "abs-repo"
    cfg = _write(tmp_path, f"repos:\n  - path: {target}\n")
    (plan,) = load_fleet_config(path=cfg)
    assert plan.path == target.resolve()


def test_missing_repos_key_raises(tmp_path):
    cfg = _write(tmp_path, "defaults:\n  interval: 60\n")
    with pytest.raises(FleetConfigError):
        load_fleet_config(path=cfg)


def test_empty_repos_list_raises(tmp_path):
    cfg = _write(tmp_path, "repos: []\n")
    with pytest.raises(FleetConfigError):
        load_fleet_config(path=cfg)


def test_repo_without_path_raises(tmp_path):
    cfg = _write(tmp_path, "repos:\n  - name: nopath\n")
    with pytest.raises(FleetConfigError):
        load_fleet_config(path=cfg)


def test_unknown_top_level_key_raises(tmp_path):
    cfg = _write(tmp_path, "repos:\n  - path: r\nbogus: 1\n")
    with pytest.raises(FleetConfigError):
        load_fleet_config(path=cfg)


def test_unknown_repo_key_raises(tmp_path):
    cfg = _write(tmp_path, "repos:\n  - path: r\n    typo: 1\n")
    with pytest.raises(FleetConfigError):
        load_fleet_config(path=cfg)


def test_wrong_type_interval_raises(tmp_path):
    cfg = _write(tmp_path, "repos:\n  - path: r\n    interval: fast\n")
    with pytest.raises(FleetConfigError):
        load_fleet_config(path=cfg)


def test_missing_config_file_raises(tmp_path):
    with pytest.raises(FleetConfigError):
        load_fleet_config(path=tmp_path / "nope.yml")


def test_repoplan_is_frozen():
    # frozen dataclass：可 pickle 的不可变值对象，T2 编排层跨 spawn 子进程传它。
    plan = RepoPlan(
        path=Path("/x"), name="x", interval=60, labels=["openagents"], base="main", hold=None
    )
    with pytest.raises(FrozenInstanceError):
        plan.interval = 1  # type: ignore[misc]
