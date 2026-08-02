# Spec-0074/T1: utils.forge —— 托管平台（forge）分发层：按配置把 github.py 同名公共面委托给对应 driver。

"""forge 分发模块：消费方以 `from openagents.utils import forge as github` 引入，调用点零改动换轨。

github.py（gh CLI 薄封装）的模块函数公共面是全仓平台操作的事实契约；本模块经 PEP 562 的模块级
`__getattr__` 把属性访问委托给**当前生效的 driver**（github / gitea），使「用哪个托管平台」成为
`.openagents/openagents.yml` `forge` 段的声明式选择（缺省 github，存量用户零感知）。

driver 选择的两条路径：
- **显式**：`configure(name=..., settings=...)`（vigil / CLI 装配置后调用、测试注入）；
- **惰性发现**：未显式配置时，首次函数访问从 cwd 向上找 `.openagents/openagents.yml` 轻量读
  `forge`/`gitea` 两键（不走 agent_config 全量校验——本模块须保持依赖图叶位，且 issue/release 等
  不装配置的命令也要选对 driver，语义与 gh 的 cwd 绑定一致）。文件缺失 / 坏 YAML → fail-open 回落
  github（老项目零感知）；**声明了 forge=gitea 但 gitea 段不完整 → 大声报错**（绝不静默拿 gh 打一个
  Gitea 项目）。

流程标签常量与 `GithubError` forge 中立（两 driver 共用 github.py 里的一份定义），在 import 时直接
re-export——模块顶层取常量零 IO，不触发惰性发现。
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import ModuleType
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

# Spec-0074/T1: forge 中立的常量与错误类型——import 时静态 re-export（零 IO），不走 __getattr__。
from openagents.utils.github import (  # noqa: F401  re-export 供消费方经 forge 取用
    APPROVAL_LABEL,
    BLOCKED_LABEL,
    DISCOVERY_LABEL,
    DISPATCH_LABEL,
    PROCESS_LABELS,
    GithubError,
)

FORGE_GITHUB = "github"
FORGE_GITEA = "gitea"
_VALID_FORGES = (FORGE_GITHUB, FORGE_GITEA)

# 惰性发现读的配置文件相对路径。与 agent_config.DEFAULT_CONFIG_PATH 同值但不 import 它——
# agent_config 反向引用本模块（FORGE_* 常量），本模块必须停在依赖图更低处以免循环。
_CONFIG_RELPATH = Path(".openagents") / "openagents.yml"

_lock = threading.Lock()
_active: str | None = None  # None = 尚未确定 → 首次函数访问走惰性发现
_yaml = YAML(typ="safe")


def configure(*, name: str, settings: dict[str, Any] | None = None) -> None:
    """显式装载 forge 选择；`gitea` 时 settings（base_url/owner/repo/token_env）透传给 driver 校验。

    幂等可重入（fleet 多仓子进程 / 测试各自装配）。非法 forge 名或 gitea 设置不完整 → GithubError
    （错误类型不分叉，cli 的错误归一化零改动）。
    """
    global _active
    if name not in _VALID_FORGES:
        raise GithubError(f"未知 forge {name!r}（可选：{'/'.join(_VALID_FORGES)}）")
    with _lock:
        if name == FORGE_GITEA:
            from openagents.utils import (
                gitea,  # noqa: PLC0415  惰性：github 用户不付 gitea import 费
            )

            gitea.configure(settings=dict(settings or {}))
        _active = name


def reset() -> None:
    """回到「尚未确定」态（下次访问重新惰性发现）——测试隔离用。"""
    global _active
    with _lock:
        _active = None


def active_forge() -> str:
    """当前生效的 forge 名；未显式配置时先做一次惰性发现（结果缓存）。"""
    if _active is None:
        _discover()
    return _active or FORGE_GITHUB


def _discover() -> None:
    """惰性发现：从 cwd 向上找 `.openagents/openagents.yml`，读 forge/gitea 两键后 configure。

    文件缺失 / 坏 YAML / 顶层非映射 / forge 值未知 → 回落 github（fail-open，老项目零感知）。
    forge=gitea 但 gitea 段不完整 → configure 抛 GithubError 原样上抛（fail-loud，见模块 docstring）。
    """
    name, settings = _read_config(start=Path.cwd())
    configure(name=name, settings=settings)


def _read_config(*, start: Path) -> tuple[str, dict[str, Any]]:
    """从 start 逐级向上找配置文件；到 git 仓库根（含 .git 的层）为止不再上翻。"""
    for base in (start, *start.parents):
        candidate = base / _CONFIG_RELPATH
        if candidate.is_file():
            return _parse_forge(path=candidate)
        if (base / ".git").exists():
            break  # 仓库根已到——配置只认本仓的（与 gh 的 cwd→仓库绑定语义一致）
    return FORGE_GITHUB, {}


def _parse_forge(*, path: Path) -> tuple[str, dict[str, Any]]:
    """轻量读 forge/gitea 两键（其余键不管，全量校验归 agent_config）；不可读/不合形 → github。"""
    try:
        data = _yaml.load(path.read_text(encoding="utf-8")) or {}
    except (OSError, YAMLError):
        return FORGE_GITHUB, {}
    if not isinstance(data, dict):
        return FORGE_GITHUB, {}
    name = data.get("forge") or FORGE_GITHUB
    if name not in _VALID_FORGES:
        return FORGE_GITHUB, {}
    raw_settings = data.get("gitea")
    settings = dict(raw_settings) if isinstance(raw_settings, dict) else {}
    return str(name), settings


def _driver_module() -> ModuleType:
    """当前 forge 对应的 driver 模块（github.py 公共面是事实契约，driver 同名实现）。"""
    if active_forge() == FORGE_GITEA:
        from openagents.utils import gitea  # noqa: PLC0415  惰性 import（见 configure）

        return gitea
    from openagents.utils import github  # noqa: PLC0415  与 gitea 分支对称

    return github


def __getattr__(name: str) -> Any:
    """PEP 562：把未在本模块定义的属性访问委托给当前 driver（函数/数据类都经此走）。"""
    if name.startswith("_"):
        raise AttributeError(name)
    module = _driver_module()
    try:
        return getattr(module, name)
    except AttributeError as exc:
        raise AttributeError(
            f"forge driver {module.__name__} 缺少公共面 {name!r}——"
            f"github.py 是事实契约，新增公共函数需两 driver 同步实现（Spec-0074 Drawbacks 1）"
        ) from exc
