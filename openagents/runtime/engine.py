"""# Spec-0060/T2: runtime.engine —— run_agent 引擎（填占位符 → 派 backend → 收结构化输出）。

新栈唯一的「派 agent」入口，也是 recipe 调 agent 的唯一方式。职责三步、**不认识任何具体流程**
（换一套 agent/recipe 零改动，理念 10 机制与策略分离）：

1. 读 `agent_module.PROMPT`（`string.Template`）→ `substitute(**placeholders)` 填占位符成 task；
2. `backend.run(work_dir=..., task=prompt, context=...)` 派后端跑（backend 抽象见 backends/base.py）；
3. 解析 agent 输出**末行 JSON**、按 `agent_module.OUTPUT_SCHEMA`（键→类型 dict）校验 → 返回 dict。

失败语义（见 spec Unresolved 定死为「raise，交上层 recipe 按轮次消化」）：agent 吐坏 JSON /
末行不是 JSON 对象 / 缺 schema 键 / 键类型不符 → 抛 `AgentOutputError`。engine 不重试、不兜业务，
把「这轮输出不合契约」明确上抛，由 recipe 层决定（solve_issue 里表现为 round_cap 内的一轮）。

保留字占位符：`work_dir`（必填，派给 backend 的工作目录）、`context`（选填，issue 正文/PR 历史等
上下文串）由 engine 从 placeholders 取出交给 backend；其余键都用于填 PROMPT 模板。
"""

from __future__ import annotations

import json
from typing import Any


class AgentOutputError(Exception):
    """# Spec-0060/T2: agent 输出不合 OUTPUT_SCHEMA 契约（坏 JSON / 缺键 / 类型不符）时抛出。"""


def run_agent(agent_module: Any, *, backend: Any, **placeholders: Any) -> dict[str, Any]:
    """填 agent 的 PROMPT 占位符 → 派 backend → 解析并校验末行 JSON → 返回结构化 dict。

    `work_dir`（必填）与 `context`（选填，缺省空串）是保留字占位符：从 placeholders 取出交给
    `backend.run`，其余键用于 `agent_module.PROMPT.substitute`（Template 忽略多余键，故保留字
    即便未出现在模板里也无碍）。返回值是按 `agent_module.OUTPUT_SCHEMA` 校验通过的 dict。
    """
    if "work_dir" not in placeholders:
        raise AgentOutputError("run_agent 缺少必填保留字占位符 work_dir")
    work_dir = placeholders.pop("work_dir")
    context = placeholders.pop("context", "")

    prompt = agent_module.PROMPT.substitute(**placeholders)
    result = backend.run(work_dir=work_dir, task=prompt, context=context)

    parsed = _parse_last_json(text=result.summary)
    _validate(payload=parsed, schema=agent_module.OUTPUT_SCHEMA)
    return parsed


def _parse_last_json(*, text: str) -> dict[str, Any]:
    """从 agent 输出里取**末行 JSON 对象**：自底向上找第一行能 json 解析成 dict 的非空行。

    对末尾偶有的空白/句号等噪声宽容（自底向上扫），但要求确有一行是 JSON 对象——否则 raise。
    """
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise AgentOutputError(f"agent 输出末尾未找到合法 JSON 对象：{text[-200:]!r}")


def _validate(*, payload: dict[str, Any], schema: dict[str, type]) -> None:
    """按 OUTPUT_SCHEMA（键→Python 类型）校验：缺键 / 类型不符 → 抛 AgentOutputError。

    极简键→类型校验（见 spec Unresolved：值域约束先留 agent prompt 自述 + 后续按需硬化）。
    bool 是 int 的子类，故对 int 期望显式排除 bool，避免 True 冒充数字混过。
    """
    for key, expected in schema.items():
        if key not in payload:
            raise AgentOutputError(f"agent 输出缺少 schema 键 {key!r}：{payload!r}")
        value = payload[key]
        if expected is int and isinstance(value, bool):
            raise AgentOutputError(f"agent 输出键 {key!r} 期望 int，得到 bool：{value!r}")
        if not isinstance(value, expected):
            raise AgentOutputError(
                f"agent 输出键 {key!r} 类型不符：期望 {expected.__name__}，"
                f"得到 {type(value).__name__}（{value!r}）"
            )
