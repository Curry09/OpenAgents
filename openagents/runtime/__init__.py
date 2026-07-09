"""# Spec-0060/T2: runtime —— 唯一允许的「机制代码」层（引擎 + 最小硬闸 + 上下文/状态）。

本包只作命名空间标记，不做重导出——下游分模块导入（`from openagents.runtime.engine import
run_agent` / `from openagents.runtime import gates, context, state`），使 __init__ 不成为
跨 Task 的共写点（见 spec DAG 说明）。runtime 只含机制、不含任何具体流程：换一套 agent/recipe
零改动（理念 10 机制与策略分离）。
"""
