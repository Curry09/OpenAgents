"""# Spec-0064/T1: utils.agent_config —— `.openagents/openagents.yml` 声明式配置加载器。

一份 `.openagents/openagents.yml` 作「用哪些 agent + 每道闸归谁把关」的**单一真源**（承理念 1
奥卡姆 + 理念 2 去中心化）：`agents` 段声明每个角色接哪个后端（同项目可混接 Claude Code / Codex /
nexau）、`stages` 段用 `agent`/`human`/`skip` 三态声明每个可配阶段归属、`release` 段声明顶层发版
策略、`defaults`/`repos` 收编多仓库统管（沿用 `utils.fleet_config` 的 defaults 合并模式）。

沿用 `utils.fleet_config` 同款 `ruamel.yaml` + `jsonschema` Draft202012 声明式校验（理念 1，不增
新依赖），产出 resolved 不可变 dataclasses（`AgentPolicy` / `StagePolicy` / `ReleasePolicy` /
`RepoPlan` / `AgentConfig`）供编排层（Spec-0064/T3 `run_vigil`）读「这道闸归谁 / 这个角色接哪个
后端」。**整份可省**——文件不存在或空 → 全回落内建默认（= 今天的硬编码全自动行为，不写 YAML 的
用户零感知）。additive，无消费者改动（T3 才接线）。

校验分两层（对齐 fleet_config 的 schema + 手工矛盾校验分工）：
- jsonschema 验结构/类型 + 每闸合法取值（per-stage enum：`conflict`/`merge` 拒 skip、`rfc` 仅
  agent/skip）；
- 手工语义校验补 schema 表达不了的：① 确定性硬闸名（head-advanced/evidence-stamp/round-cap）与恒
  agent 阶段（implement/deliver）写进 `stages` → 明确 reject（强化分层，见约束②）；②「不许零闸」
  跨字段守卫拒 `review: skip` + `merge: agent`（未审直接盲合进 main）；③ `rfc: skip` 出显式告警
  （允许跳但别悄悄关掉 RFC 卖点，见约束①）。

纯解析：除读配置文件外无副作用（`rfc: skip` 告警走 `warnings.warn`，hermetic 可测），不感知
git / gh / 子进程（理念 10 解耦）。
"""

from __future__ import annotations

import importlib.resources
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from openagents.utils import github

# Spec-0064/T1: 三态所有者字面量——`stages` 每闸的合法取值取自它们的子集（见 _STAGE_VALID_OWNERS）。
OWNER_AGENT = (
    "agent"  # 自动化拥有此闸（红了自动打回 implementer，非「agent 判客观事实」，见分界线）
)
OWNER_HUMAN = "human"  # 停在此闸打 needs-human、挂起等人
OWNER_SKIP = "skip"  # 不设此闸（当 PASS 放行）

# Spec-0064/T1: 七个**可配**阶段名 + 各自合法取值（不是所有闸都收全三态）——见 spec Reference-level
# 「合法取值」列。conflict/merge 冲突必须解·合并必须有人或自动化把关，故不可 skip；rfc 起草只 agent
# 或不写（skip），不存在「human 起草」（人要起草直接写代码，不走本框架的 agent 起草闸）。
STAGE_TRIAGE = "triage"
STAGE_RFC = "rfc"
STAGE_CONFLICT = "conflict"
STAGE_CI = "ci"
STAGE_E2E = "e2e"
STAGE_REVIEW = "review"
STAGE_MERGE = "merge"

_STAGE_VALID_OWNERS: dict[str, tuple[str, ...]] = {
    STAGE_TRIAGE: (OWNER_AGENT, OWNER_HUMAN, OWNER_SKIP),
    STAGE_RFC: (OWNER_AGENT, OWNER_SKIP),
    STAGE_CONFLICT: (OWNER_AGENT, OWNER_HUMAN),
    STAGE_CI: (OWNER_AGENT, OWNER_HUMAN, OWNER_SKIP),
    STAGE_E2E: (OWNER_AGENT, OWNER_HUMAN, OWNER_SKIP),
    STAGE_REVIEW: (OWNER_AGENT, OWNER_HUMAN, OWNER_SKIP),
    STAGE_MERGE: (OWNER_AGENT, OWNER_HUMAN),
}

# Spec-0064/T1: 内建默认 stages——**全 agent**（含 merge=agent，等价今天不带 --hold 的全自动合并），
# 使不写 YAML 的用户零感知（承 Drawbacks「= 今天的硬编码行为」）。default review=agent 天然不撞
# 「不许零闸」守卫（review 在，merge 自动也站得住）。
_DEFAULT_STAGES: dict[str, str] = {stage: OWNER_AGENT for stage in _STAGE_VALID_OWNERS}

# Spec-0064/T1: 已知 agent 角色 → 后端映射的默认（backends/ 目前只有 claude_code，理念 2 的声明面
# 先留 schema 位、混接 codex/nexau 的实现另议）。角色齐全一份，`agents` 段可逐角色覆盖 backend。
_ROLES = ("triager", "drafter", "implementer", "reviewer", "replier", "deliver")
_DEFAULT_BACKEND = "claude_code"

# Spec-0064/T1: 确定性硬闸名（`runtime.gates`）——恒机器、恒在、skip 关不掉（防 #140 空转的安全
# 底线，见约束②）。写进 `stages` 即报错，把「可配阶段」与「硬底线」词分开以强化分层。
_HARDGATE_NAMES = ("head-advanced", "evidence-stamp", "round-cap")
# Spec-0064/T1: 恒 agent、不可配的阶段（写码/交付永远派 agent，无「谁把关」的选择），写进 stages 亦 reject。
_ALWAYS_AGENT_STAGES = ("implement", "deliver")

# Spec-0064/T1: 顶层发版策略——manual（人决定何时物化版本，默认最安全）/ auto（main 绿+无 BLOCKED
# 自动物化，实现另议，见 Future）。不进 `stages`：release 是跨 issue 的仓库级动作、非某 issue 的流水线阶段。
RELEASE_MANUAL = "manual"
RELEASE_AUTO = "auto"

# Spec-0064/T1: defaults 段内建默认——与单仓库 vigil / fleet_config 同源（interval 60 / base main /
# labels 取发现标签单一真源），避免「本配置默认」与既有默认漂移。
_DEFAULT_INTERVAL = 60
_DEFAULT_BASE = "main"
_DEFAULT_LABELS = (github.DISCOVERY_LABEL,)

# Spec-0064/T1: 单仓库统管默认——不写 `repos` 段时守当前目录（path=.），承 fleet「单仓库整段可省」。
_DEFAULT_REPO_PATH = "."

# Spec-0064/T1: 配置文件默认落点（承 .openagents/ 命名空间；单仓库整份可省 → 内建默认）。
DEFAULT_CONFIG_PATH = ".openagents/openagents.yml"

# Spec-0067/T1: 打包进包内的默认配置注释模板——`oa init` 从它生成盘上 .openagents/openagents.yml
# 的单一真源。放 openagents/data/ 使源码树（editable 安装）与 wheel 里路径一致、两种安装模式同源
# （见 Spec-0067 Rationale）。防漂移：tests 断言它经 load_agent_config 解析后语义等价 default_config()。
_TEMPLATE_RESOURCE = "openagents.yml.template"

_DRAFT = "https://json-schema.org/draft/2020-12/schema"

# Spec-0064/T1: `stages` 段 schema——只列七个可配阶段、各自 owner 走 enum（per-stage 合法取值），
# additionalProperties=False 挡未知/保留名（硬闸名/恒 agent 名/拼写漂移都由手工预扫给精确文案后，
# 这里作 schema 兜底）。
_STAGES_SCHEMA: dict = {
    "type": "object",
    "properties": {stage: {"enum": list(owners)} for stage, owners in _STAGE_VALID_OWNERS.items()},
    "additionalProperties": False,
}

# Spec-0064/T1: `agents` 段 schema——role → { backend: str }，只认已知角色（additionalProperties=False）。
_AGENTS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        role: {
            "type": "object",
            "properties": {"backend": {"type": "string"}},
            "required": ["backend"],
            "additionalProperties": False,
        }
        for role in _ROLES
    },
    "additionalProperties": False,
}

# Spec-0064/T1: 单个 `repos[]` 项——必填 path + 可选 name/base/interval/labels + 每仓 stages 覆盖。
_REPO_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "name": {"type": "string"},
        "base": {"type": "string"},
        "interval": {"type": "integer"},
        "labels": {"type": "array", "items": {"type": "string"}},
        "stages": _STAGES_SCHEMA,
    },
    "required": ["path"],
    "additionalProperties": False,
}

# Spec-0064/T1: 顶层 schema——全键可选（整份省略 → 内建默认），additionalProperties=False 防手滑。
AGENT_CONFIG_SCHEMA: dict = {
    "$schema": _DRAFT,
    "type": "object",
    "properties": {
        "version": {"type": "integer"},
        "agents": _AGENTS_SCHEMA,
        "stages": _STAGES_SCHEMA,
        "release": {"enum": [RELEASE_MANUAL, RELEASE_AUTO]},
        "defaults": {
            "type": "object",
            "properties": {
                "interval": {"type": "integer"},
                "base": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "repos": {"type": "array", "minItems": 1, "items": _REPO_SCHEMA},
    },
    "additionalProperties": False,
}

_yaml = YAML(typ="safe")


class AgentConfigError(Exception):
    """# Spec-0064/T1: `.openagents/openagents.yml` 无法读取或不合法时抛出（结构错 / 非法取值 /
    硬闸名进 stages / review:skip+merge:agent 零闸组合等）。上层 CLI 转干净一行提示（承 fleet_config）。"""


@dataclass(frozen=True)
class AgentPolicy:
    """# Spec-0064/T1: 角色 → 后端 的 resolved 映射（理念 2 去中心化的声明面）。"""

    backends: dict[str, str] = field(default_factory=dict)

    def backend_for(self, *, role: str) -> str:
        """取某角色接的后端名；未声明 → 内建默认（claude_code）。"""
        return self.backends.get(role, _DEFAULT_BACKEND)


@dataclass(frozen=True)
class StagePolicy:
    """# Spec-0064/T1: 阶段 → 所有者（agent/human/skip）的 resolved 三态映射。"""

    owners: dict[str, str] = field(default_factory=dict)

    def owner_of(self, *, stage: str) -> str:
        """取某阶段归谁把关（agent/human/skip）；未声明 → 内建默认（agent）。"""
        return self.owners.get(stage, _DEFAULT_STAGES.get(stage, OWNER_AGENT))


@dataclass(frozen=True)
class ReleasePolicy:
    """# Spec-0064/T1: 顶层发版策略（manual/auto）。"""

    mode: str = RELEASE_MANUAL


@dataclass(frozen=True)
class RepoPlan:
    """# Spec-0064/T1: 单仓库守夜计划——defaults 与该仓库覆盖合并后的最终参数 + 该仓 resolved stages。

    可 pickle 的不可变 dataclass（承 fleet.RepoPlan：`recipes.fleet` 跨 spawn 子进程传它）。`stages`
    是顶层 stages 与本仓 `repos[].stages` 覆盖合并后的最终三态；`agents` 由顶层共享（不逐仓覆盖）。
    """

    path: Path
    name: str
    interval: int
    base: str
    labels: list[str]
    stages: StagePolicy


@dataclass(frozen=True)
class AgentConfig:
    """# Spec-0064/T1: 整份 `.openagents/openagents.yml` 的 resolved 视图——编排层的单一读入口。"""

    version: int
    agents: AgentPolicy
    stages: StagePolicy
    release: ReleasePolicy
    interval: int
    base: str
    labels: list[str]
    repos: list[RepoPlan]


def default_config() -> AgentConfig:
    """内建默认配置（整份可省时的回落）——全 agent stages / claude_code / manual release / 单仓 `.`。"""
    stages = StagePolicy(owners=dict(_DEFAULT_STAGES))
    return AgentConfig(
        version=1,
        agents=AgentPolicy(backends={}),
        stages=stages,
        release=ReleasePolicy(mode=RELEASE_MANUAL),
        interval=_DEFAULT_INTERVAL,
        base=_DEFAULT_BASE,
        labels=list(_DEFAULT_LABELS),
        repos=[
            RepoPlan(
                path=Path(_DEFAULT_REPO_PATH).resolve(),
                name=Path(_DEFAULT_REPO_PATH).resolve().name,
                interval=_DEFAULT_INTERVAL,
                base=_DEFAULT_BASE,
                labels=list(_DEFAULT_LABELS),
                stages=stages,
            )
        ],
    )


def _default_template_text() -> str:
    """读打包进包内的默认配置注释模板文本（Spec-0067/T1）。

    走 `importlib.resources.files("openagents")` 定位包目录再 joinpath 到 data/ 下的模板，
    只依赖 `openagents` 是包（恒成立），不要求 data 子目录本身是包；editable 与 wheel 两种
    安装模式都可达（源码树与 wheel 内路径同为 openagents/data/）。
    """
    resource = importlib.resources.files("openagents").joinpath("data", _TEMPLATE_RESOURCE)
    return resource.read_text(encoding="utf-8")


def scaffold_default_config(*, path: Path, force: bool) -> bool:
    """把包内默认配置注释模板写到 `path`（Spec-0067/T1）——`oa init` 的落盘出口。

    幂等：`path` 已存在且 `not force` → 直接返回 False（不碰用户改动）；否则建好父目录后写入
    模板文本、返回 True（`force=True` 时覆盖既有）。生成物只是声明式默认，运行时 flag 仍可单次
    覆盖它（见 `cli._effective_config`）。除写目标文件外无副作用（不读 git/gh/网络，理念 10 解耦）。
    """
    resolved = Path(path)
    if resolved.exists() and not force:
        return False
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(_default_template_text(), encoding="utf-8")
    return True


def load_agent_config(*, path: Path) -> AgentConfig:
    """读 `.openagents/openagents.yml` → 校验 → 合并默认 → 返回 resolved `AgentConfig`。

    步骤：(1) 文件不存在 / 空 → 全回落内建默认（整份可省，不写 YAML 零感知）；(2) YAML 解析 +
    jsonschema 结构/类型/每闸合法取值校验；(3) 手工语义校验（硬闸名/恒 agent 名进 stages reject、
    「不许零闸」守卫、`rfc: skip` 告警）；(4) 合并 defaults 与每仓 override 产出 RepoPlan 列表。
    纯解析、无其它副作用（告警走 warnings.warn）。
    """
    resolved_path = Path(path)
    if not resolved_path.exists():
        return default_config()
    data = _load_yaml(path=resolved_path)
    if data is None:
        return default_config()  # 空文件（YAML 解析出 None）→ 全默认。
    _check_reserved_stage_names(data=data)
    _validate(data=data)
    return _build_config(data=data, base_dir=resolved_path.resolve().parent)


def _load_yaml(*, path: Path) -> dict | None:
    """读取并解析 YAML；文件读不到 / 解析错 / 顶层非映射（非空）→ AgentConfigError；空 → None。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentConfigError(f"无法读取 openagents 配置 {path}：{exc}") from exc
    try:
        data = _yaml.load(text)
    except YAMLError as exc:
        raise AgentConfigError(f"openagents 配置 {path} 不是合法 YAML：{exc}") from exc
    if data is None:
        return None
    if not isinstance(data, dict):
        raise AgentConfigError(
            f"openagents 配置 {path} 顶层必须是映射（version / agents / stages / release / …）"
        )
    return data


def _check_reserved_stage_names(*, data: dict) -> None:
    """手工预扫：顶层与每仓 `stages` 里出现确定性硬闸名 / 恒 agent 阶段名 → 精确 reject（先于 schema）。

    schema 的 additionalProperties=False 也会拒这些键，但给的是泛化 message；此处先扫给可操作的
    分层解释（硬闸永不进 stages / implement·deliver 恒 agent），强化约束②的落地语义。
    """
    blocks = [data.get("stages")]
    for repo in data.get("repos") or []:
        if isinstance(repo, dict):
            blocks.append(repo.get("stages"))
    for stages in blocks:
        if not isinstance(stages, dict):
            continue
        for name in stages:
            if name in _HARDGATE_NAMES:
                raise AgentConfigError(
                    f"stages 里不允许出现确定性硬闸名 {name!r}——"
                    f"head 前移 / 证据戳 / round_cap 恒机器把关、skip 关不掉，不是可配阶段（约束②）"
                )
            if name in _ALWAYS_AGENT_STAGES:
                raise AgentConfigError(
                    f"stages 里不允许配置阶段 {name!r}——写码/交付恒派 agent，无「归谁把关」可选"
                )


def _validate(*, data: dict) -> None:
    """jsonschema 结构/类型/每闸合法取值校验 + 手工「不许零闸」守卫；任一错误汇总成 AgentConfigError。"""
    validator = Draft202012Validator(AGENT_CONFIG_SCHEMA)
    errors = sorted(validator.iter_errors(data), key=str)
    if errors:
        lines = []
        for error in errors:
            location = "/".join(str(part) for part in error.absolute_path) or "<root>"
            lines.append(f"  {location}: {error.message}")
        raise AgentConfigError("openagents 配置校验失败：\n" + "\n".join(lines))
    # 「不许零闸」跨字段守卫——顶层与每仓合并后的 stages 都要过（override 后仍不许零闸）。
    _guard_no_zero_gate(
        stages=_merge_stages(base=None, override=data.get("stages")), scope="<root>"
    )
    for repo in data.get("repos") or []:
        merged = _merge_stages(base=data.get("stages"), override=repo.get("stages"))
        _guard_no_zero_gate(stages=merged, scope=f"repos/{repo.get('path')}")


def _guard_no_zero_gate(*, stages: dict[str, str], scope: str) -> None:
    """拒绝 `review: skip` + `merge: agent`——未审就自动盲合进 main（理念 5「PR 需人审」的底线）。

    只要 `merge: human` 在（人点头），跳 agent-review 就站得住（人兜住）；`merge: agent`（自动合）
    时 review 必须在（agent 或 human）。天然不撞内建默认（review=agent）。
    """
    review = stages.get(STAGE_REVIEW, _DEFAULT_STAGES[STAGE_REVIEW])
    merge = stages.get(STAGE_MERGE, _DEFAULT_STAGES[STAGE_MERGE])
    if review == OWNER_SKIP and merge == OWNER_AGENT:
        raise AgentConfigError(
            f"{scope}: 不许零闸——review:skip + merge:agent 会让未审代码自动盲合进 main；"
            f"要么开 review、要么把 merge 交给人（merge:human）"
        )


def _merge_stages(*, base: dict | None, override: dict | None) -> dict[str, str]:
    """把内建默认 → 顶层 → 每仓覆盖三级合并成完整 stages 三态映射（未覆盖回落内建默认）。"""
    merged = dict(_DEFAULT_STAGES)
    if base:
        merged.update(base)
    if override:
        merged.update(override)
    return merged


def _build_config(*, data: dict, base_dir: Path) -> AgentConfig:
    """把校验过的原始 dict 合并默认，产出 resolved AgentConfig（含每仓 RepoPlan）。"""
    _warn_rfc_skip(stages=_merge_stages(base=None, override=data.get("stages")))

    agents = _build_agents(raw=data.get("agents") or {})
    top_stages = StagePolicy(owners=_merge_stages(base=None, override=data.get("stages")))
    release = ReleasePolicy(mode=data.get("release", RELEASE_MANUAL))

    defaults = data.get("defaults") or {}
    interval = defaults.get("interval", _DEFAULT_INTERVAL)
    base = defaults.get("base", _DEFAULT_BASE)
    labels = list(defaults.get("labels", list(_DEFAULT_LABELS)))

    raw_repos = data.get("repos")
    if not raw_repos:
        raw_repos = [{"path": _DEFAULT_REPO_PATH}]
    repos = [
        _build_repo(
            repo=repo,
            base_dir=base_dir,
            top_stages=data.get("stages"),
            interval=interval,
            base=base,
            labels=labels,
        )
        for repo in raw_repos
    ]
    return AgentConfig(
        version=data.get("version", 1),
        agents=agents,
        stages=top_stages,
        release=release,
        interval=interval,
        base=base,
        labels=labels,
        repos=repos,
    )


def _build_agents(*, raw: dict) -> AgentPolicy:
    """把 `agents` 段折成 role → backend 映射（缺省角色由 AgentPolicy.backend_for 回落默认）。"""
    backends = {role: spec["backend"] for role, spec in raw.items()}
    return AgentPolicy(backends=backends)


def _build_repo(
    *,
    repo: dict,
    base_dir: Path,
    top_stages: dict | None,
    interval: int,
    base: str,
    labels: list[str],
) -> RepoPlan:
    """把单个 repo 的 defaults/override 合并成 RepoPlan——path 绝对化、stages 三级合并、其余回落 defaults。"""
    path = _absolutize(raw_path=repo["path"], base_dir=base_dir)
    stages = StagePolicy(owners=_merge_stages(base=top_stages, override=repo.get("stages")))
    return RepoPlan(
        path=path,
        name=repo.get("name") or path.name,
        interval=repo.get("interval", interval),
        base=repo.get("base", base),
        labels=list(repo.get("labels", labels)),
        stages=stages,
    )


def _warn_rfc_skip(*, stages: dict[str, str]) -> None:
    """`rfc: skip` 出显式告警（约束①）——允许跳（撞理念 4 先改 RFC 再改代码），但别悄悄关掉框架的
    RFC 卖点。走 warnings.warn（hermetic 可测：pytest.warns 断言）而非静默。"""
    if stages.get(STAGE_RFC) == OWNER_SKIP:
        warnings.warn(
            "stages.rfc=skip：将跳过 RFC 起草直接实现，撞理念 4（先改 RFC 再改代码）——"
            "仅当按 issue 粒度的显式选择使用，别放进全局默认悄悄关掉 RFC 卖点（Spec-0064 约束①）",
            stacklevel=2,
        )


def _absolutize(*, raw_path: str, base_dir: Path) -> Path:
    """`~` 展开 + 相对路径以配置文件所在目录为基准 → 绝对化（与 cwd 无关，可移植；承 fleet_config）。"""
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()
