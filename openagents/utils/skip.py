"""# Spec-0061/T1: utils.skip —— --skip 逐闸旁路意图解析的稳定 import 面（纯逻辑、零 IO）。

把 `vigil --skip` 逗号串解析成 Skip 值对象（把指定闸当 PASS 放行）+ 与 Hold 的矛盾意图校验，
都是确定性纯解析/校验，归 utils。薄再导出现有 `skip.py`；模块级 `NONE`（「什么都不跳」默认）
再导出为 `NONE`（与 utils.hold.NONE 分属两模块，调用侧 `skip.NONE` 消歧）。不复制、不改动 skip.py。
"""

from __future__ import annotations

# Spec-0061/T1: 再导出 skip 解析 + hold/skip 矛盾校验原语（不改 skip.py）。
from openagents.skip import NONE, Skip, parse_skip, reconcile_hold_skip

__all__ = ["NONE", "Skip", "parse_skip", "reconcile_hold_skip"]
