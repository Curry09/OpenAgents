"""# Spec-0061/T1: utils.results —— 成果看板渲染的稳定 import 面。

把 State 的 RunRecord 渲成本地 HTML 看板并打开浏览器，是面向成果验收（理念 8）的确定性渲染，
归 utils。薄再导出现有 `results.py`，不复制、不改动。board 读侧仍依赖旧 State（本批次不动旧
state.py，见 Spec-0060 交付边界）；新栈 runtime.state 与其并存，最终统一留收敛批次。
"""

from __future__ import annotations

# Spec-0061/T1: 再导出看板渲染原语（不改 results.py）。
from openagents.results import board, render

__all__ = ["board", "render"]
