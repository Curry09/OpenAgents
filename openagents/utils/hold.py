"""# Spec-0061/T1: utils.hold —— --hold 分级监督闸意图解析的稳定 import 面（纯逻辑、零 IO）。

把 `vigil --hold` 逗号串解析成 Hold 值对象（在 spec/merge 闸停下等人）是确定性纯解析，归 utils。
薄再导出现有 `hold.py`；模块级 `NONE`（「哪都不停」默认）再导出为 `NONE`（本命名空间内无冲突，
与 utils.skip 的 NONE 分属两个模块，调用方 `from openagents.utils import hold, skip` 后各自
`hold.NONE`/`skip.NONE` 天然消歧）。不复制、不改动 hold.py。
"""

from __future__ import annotations

# Spec-0061/T1: 再导出 hold 解析原语（不改 hold.py）。
from openagents.hold import NONE, Hold, parse_hold

__all__ = ["NONE", "Hold", "parse_hold"]
