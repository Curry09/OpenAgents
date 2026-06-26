"""Spec-0025/T1: 代码盘点助手——扫存量代码路径产出结构化 inventory。

brownfield 反向补全 RFC 的输入端（取代 `rfc <issue>` 的「从 GitHub 拉 issue」）：给定一个
代码路径，校验其存在、轻量盘点出文件清单 / 模块级 docstring / 公开符号，并据 path 形态
（单文件 vs 目录）确定本次「一份 spec」的范围。纯函数、无副作用——只读文件系统、用 ast
静态解析，不感知 git / GitHub / backend（理念 10 解耦），便于单测。

产出的 inventory 有两用（见 Spec-0025 Guide-level）：
  1. 校验路径存在（不存在 / 无 .py 文件即抛 BackfillError，在建 worktree 前就快速失败）；
  2. 为反推 agent 圈定阅读范围——render() 出的摘要拼进 `_BACKFILL_RFC_TASK` prompt。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


class BackfillError(ValueError):
    """Spec-0025/T1: 盘点失败时抛出（路径不存在 / 目录下无可盘点的 .py 文件）。

    继承 ValueError（路径本质是坏输入值）→ 落入 cli._run 已有的已知运行期错误通道，
    无需 CLI 接线层特判即可转成干净一行提示 + 非零退出（T3 薄路由不含错误处理逻辑）。
    """


@dataclass(frozen=True)
class ModuleInfo:
    """Spec-0025/T1: 单个 .py 模块的盘点结果。"""

    # 相对扫描根的 POSIX 路径（单文件形态即文件名本身）。
    path: str
    # 模块级 docstring（首个语句为字符串字面量时取之），无则 None。
    docstring: str | None
    # 顶层公开符号（def / async def / class，名字不以 `_` 起），按出现顺序去重。
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class Inventory:
    """Spec-0025/T1: 一次盘点的汇总——文件清单 + 各模块结构 + path 形态。"""

    # 被扫描的原始路径（POSIX 字符串）。
    root: str
    # path 形态：单文件 True / 目录 False，决定「一份 spec」的范围叙述。
    single_file: bool
    # 按相对路径字典序排列的模块清单。
    modules: tuple[ModuleInfo, ...]

    def render(self) -> str:
        """渲染成喂给反推 agent 的范围摘要（文件清单 + 各模块公开符号）。

        单一来源：orchestrator 把它拼进 `_BACKFILL_RFC_TASK`，给 agent 圈定阅读范围，
        不替代 agent 真正读代码（理念 8 证据驱动）。
        """
        shape = "单文件" if self.single_file else "目录"
        lines = [f"盘点根：{self.root}（{shape}，共 {len(self.modules)} 个 .py 模块）"]
        for module in self.modules:
            summary = (module.docstring or "").strip().splitlines()
            head = summary[0] if summary else "（无模块 docstring）"
            symbols = "、".join(module.symbols) if module.symbols else "（无公开符号）"
            lines.append(f"- {module.path}：{head}")
            lines.append(f"    公开符号：{symbols}")
        return "\n".join(lines)


def inventory(*, path: Path) -> Inventory:
    """Spec-0025/T1: 盘点 `path` 下的存量 .py 代码，产出结构化 Inventory。

    校验：路径不存在 → BackfillError；目录下无任何 .py 文件 → BackfillError（空目录同理）。
    单文件须为 .py，否则按目录无 .py 处理（抛错）。纯读、无副作用。
    """
    target = Path(path)
    if not target.exists():
        raise BackfillError(f"路径不存在：{target}")

    if target.is_file():
        files = [target] if target.suffix == ".py" else []
    else:
        # 目录：递归收集 .py（字典序稳定，便于可复现的 inventory / 测试断言）。
        files = sorted(target.rglob("*.py"))

    if not files:
        raise BackfillError(f"路径下无可盘点的 .py 文件：{target}")

    base = target.parent if target.is_file() else target
    modules = tuple(_module_info(file=file, base=base) for file in files)
    return Inventory(root=target.as_posix(), single_file=target.is_file(), modules=modules)


def slug_for(*, path: Path) -> str:
    """Spec-0025/T1: 据 path 派生文件系统安全的 slug，供 backfill 分支名 / worktree 键复用。

    单文件去 `.py` 后缀；非字母数字折成连字符；空串兜底为 `code`。纯函数。
    """
    target = Path(path)
    name = target.name or "root"
    if name.endswith(".py"):
        name = name[:-3]
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return slug or "code"


def _module_info(*, file: Path, base: Path) -> ModuleInfo:
    """Spec-0025/T1: 解析单个 .py，抽模块 docstring + 顶层公开符号。

    解析失败（语法错误 / 读不出）时降级为「有路径、无 docstring、无符号」，绝不抛错——
    盘点是尽力而为的范围提示，单个坏文件不该让整次盘点失败。
    """
    rel = file.relative_to(base).as_posix()
    try:
        tree = ast.parse(file.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return ModuleInfo(path=rel, docstring=None, symbols=())
    return ModuleInfo(
        path=rel, docstring=ast.get_docstring(tree), symbols=_public_symbols(tree=tree)
    )


def _public_symbols(*, tree: ast.Module) -> tuple[str, ...]:
    """Spec-0025/T1: 取顶层 def / async def / class 中名字不以 `_` 起的公开符号（去重保序）。"""
    seen: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_") and node.name not in seen:
                seen.append(node.name)
    return tuple(seen)
