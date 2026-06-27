"""Spec-0027/T1: 多仓库统管的配置加载（YAML 解析 + jsonschema 校验 + 默认合并）。

`openagents vigil-all` 读一份 YAML 配置统管一组仓库：顶层 `defaults`（全局默认，可选）
+ `repos`（要守夜的仓库列表，必填）。本模块把这份配置解析、声明式校验、并把 `defaults`
与每个仓库的覆盖项合并成一组 `RepoPlan`（每项含绝对化的 `path`、显示 `name`、以及
`interval`/`labels`/`base`/`hold`），供编排层（Spec-0027/T2 `Fleet`）逐仓库构造 Vigil。

设计沿用项目既有约定（CLAUDE.md 理念 1 奥卡姆，不增实体）：YAML 格式 + `ruamel.yaml`
读取 + `jsonschema` 声明式校验（与 `openagents/spec/` 同款依赖，`pyproject.toml` 已声明）。
纯解析：除读配置文件外无副作用，便于单测；不感知 git / gh / 子进程（理念 10 解耦）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from openagents import github

# Spec-0027/T1：内建默认——配置未写 `defaults` 段、或某项未覆盖时回落到这里。
# 与单仓库 `openagents vigil` 的 CLI 默认同源（interval 60 / base main），labels 取
# 发现标签单一真源 github.DISCOVERY_LABEL，避免「多仓库默认」与「单仓库默认」漂移。
_DEFAULT_INTERVAL = 60
_DEFAULT_BASE = "main"
_DEFAULT_HOLD: str | None = None
_DEFAULT_LABELS = (github.DISCOVERY_LABEL,)

_DRAFT = "https://json-schema.org/draft/2020-12/schema"

# Spec-0027/T1：`defaults` 与每个 `repos[]` 项共享的可选覆盖键。单点定义，schema 复用，
# 杜绝「默认段允许的键」与「仓库项允许的键」两处声明漂移。
_OVERRIDE_PROPERTIES: dict = {
    "interval": {"type": "integer"},
    "labels": {"type": "array", "items": {"type": "string"}},
    "base": {"type": "string"},
    "hold": {"type": ["string", "null"]},
}

# Spec-0027/T1：单个仓库项 = 共享覆盖键 + 必填 path + 可选 name（日志前缀显示名）。
_REPO_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "name": {"type": "string"},
        **_OVERRIDE_PROPERTIES,
    },
    "required": ["path"],
    "additionalProperties": False,
}

# Spec-0027/T1：最小够用 schema——顶层两键 defaults（可选）+ repos（必填、至少 1 项）。
# additionalProperties=False：未识别键直接报错，防手滑（如 `repo:` 写成单数）。
FLEET_CONFIG_SCHEMA: dict = {
    "$schema": _DRAFT,
    "type": "object",
    "properties": {
        "defaults": {
            "type": "object",
            "properties": dict(_OVERRIDE_PROPERTIES),
            "additionalProperties": False,
        },
        "repos": {
            "type": "array",
            "minItems": 1,
            "items": _REPO_SCHEMA,
        },
    },
    "required": ["repos"],
    "additionalProperties": False,
}

_yaml = YAML(typ="safe")


class FleetConfigError(Exception):
    """Spec-0027/T1：fleet 配置无法读取或不合法（缺 repos / 未知键 / 类型错 / path 缺失等）。"""


@dataclass(frozen=True)
class RepoPlan:
    """Spec-0027/T1：单个仓库的守夜计划——defaults 与该仓库覆盖合并后的最终参数。

    可 pickle 的不可变 dataclass（字段均为基础类型/Path/list）：T2 编排层把它作为
    `multiprocessing.Process` target 的参数跨进程传递，spawn 启动方式要求其可序列化。
    """

    # 绝对化后的本地仓库路径（子进程 os.chdir 的目标）。
    path: Path
    # 日志前缀显示名（缺省取 path basename）。
    name: str
    # 以下四项透传给 vigil.run（与单仓库 vigil 同义）。
    interval: int
    labels: list[str]
    base: str
    hold: str | None


def load_fleet_config(*, path: Path) -> list[RepoPlan]:
    """Spec-0027/T1：读 YAML 配置 → 校验 → 合并默认 → 返回 RepoPlan 列表。

    步骤：(1) 读文件并 YAML 解析（读不到/解析失败 → FleetConfigError）；
    (2) jsonschema 声明式校验结构与类型（不合法 → FleetConfigError，含定位）；
    (3) 把 defaults 与每个 repo 覆盖合并、path 以配置文件所在目录为基准绝对化、
    name 缺省取 basename。纯解析、无其它副作用。
    """
    data = _load_yaml(path=path)
    _validate(data=data)
    base_dir = path.resolve().parent
    defaults = data.get("defaults") or {}
    return [_build_plan(repo=repo, defaults=defaults, base_dir=base_dir) for repo in data["repos"]]


def _load_yaml(*, path: Path) -> dict:
    """读取并解析 YAML；文件缺失 / 解析错 / 顶层非映射 → FleetConfigError（清晰报错）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FleetConfigError(f"无法读取 fleet 配置 {path}：{exc}") from exc
    try:
        data = _yaml.load(text)
    except YAMLError as exc:
        raise FleetConfigError(f"fleet 配置 {path} 不是合法 YAML：{exc}") from exc
    if not isinstance(data, dict):
        raise FleetConfigError(f"fleet 配置 {path} 顶层必须是映射（defaults / repos）")
    return data


def _validate(*, data: dict) -> None:
    """对配置跑 jsonschema；任一错误汇总成一条 FleetConfigError（含字段定位）。"""
    validator = Draft202012Validator(FLEET_CONFIG_SCHEMA)
    errors = sorted(validator.iter_errors(data), key=str)
    if not errors:
        return
    lines = []
    for error in errors:
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        lines.append(f"  {location}: {error.message}")
    raise FleetConfigError("fleet 配置校验失败：\n" + "\n".join(lines))


def _build_plan(*, repo: dict, defaults: dict, base_dir: Path) -> RepoPlan:
    """把 defaults 与单个 repo 覆盖合并成 RepoPlan：覆盖优先、未覆盖回落默认/内建默认。"""
    raw_path = repo["path"]
    path = _absolutize(raw_path=raw_path, base_dir=base_dir)
    name = repo.get("name") or path.name
    return RepoPlan(
        path=path,
        name=name,
        interval=_pick(repo=repo, defaults=defaults, key="interval", fallback=_DEFAULT_INTERVAL),
        labels=list(
            _pick(repo=repo, defaults=defaults, key="labels", fallback=list(_DEFAULT_LABELS))
        ),
        base=_pick(repo=repo, defaults=defaults, key="base", fallback=_DEFAULT_BASE),
        hold=_pick(repo=repo, defaults=defaults, key="hold", fallback=_DEFAULT_HOLD),
    )


def _pick(*, repo: dict, defaults: dict, key: str, fallback):
    """三级回落取值：仓库覆盖 > 全局 defaults > 内建默认（fallback）。"""
    if key in repo:
        return repo[key]
    if key in defaults:
        return defaults[key]
    return fallback


def _absolutize(*, raw_path: str, base_dir: Path) -> Path:
    """`~` 展开 + 相对路径以配置文件所在目录为基准 → 绝对化（与 cwd 无关，可移植）。"""
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()
