"""# Spec-0061/T1: utils.fleet_config —— 多仓库统管配置解析的稳定 import 面（纯解析/校验）。

读一份 YAML（仓库列表 + 全局默认 + 每仓库覆盖）→ 校验 → 合并成 RepoPlan 列表，是确定性纯
解析（无副作用除读文件），归 utils。recipes.fleet 靠它把配置转成每仓库的执行计划再扇出。
薄再导出现有 `fleet_config.py`（含 FleetConfigError 异常 + RepoPlan 类型），不复制、不改动。
"""

from __future__ import annotations

# Spec-0061/T1: 再导出 fleet 配置解析原语 + 类型 + 异常（不改 fleet_config.py）。
from openagents.fleet_config import FleetConfigError, RepoPlan, load_fleet_config

__all__ = ["FleetConfigError", "RepoPlan", "load_fleet_config"]
