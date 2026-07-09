"""# Spec-0061/T1: utils.release —— 发版确定性原语的稳定 import 面。

发版（预检通过后从 main HEAD 切 release/vX.Y.Z 分支 + tag + changelog）是**机械零判断**的
操作，恰恰**不该**交给 agent——归 utils 确定性层，与「最小硬闸」是同一条分界线（见 Spec-0060
Guide-level：需要判断→agent；客观机械→确定性代码）。薄再导出现有 `release.py`，不复制、不改动。
"""

from __future__ import annotations

# Spec-0061/T1: 再导出发版原语（不改 release.py）。
from openagents.release import ReleaseResult, release

__all__ = ["ReleaseResult", "release"]
