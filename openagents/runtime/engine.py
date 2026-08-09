# Spec-0060/T2: runtime.engine —— 新栈唯一「派 agent」入口（元信息放 docstring 之上，像 argparse # Author）

"""Fill an agent's prompt placeholders, dispatch to a backend, and return validated output.

调用示例：
    >>> out = run_agent(triager, backend=claude, work_dir=wt, issue_body=body)
    >>> out["verdict"]
    'actionable'

新栈唯一的「派 agent」入口，也是 recipe 调 agent 的唯一方式。职责三步、**不认识任何具体流程**
（换一套 agent/recipe 零改动，理念 10 机制与策略分离）：

1. 读 `agent_module.PROMPT`（`string.Template`）→ `substitute(**placeholders)` 填占位符成 task；
2. `backend.run(work_dir=..., task=prompt, context=...)` 派后端跑（backend 抽象见 backends/base.py）；
3. 解析 agent 输出**末行 JSON**、按 `agent_module.OUTPUT_SCHEMA`（键→类型 dict）校验 → 返回 dict。

保留字占位符：`work_dir`（必填，派给 backend 的工作目录）、`context`（选填，issue 正文/PR 历史等
上下文串）由 engine 从 placeholders 取出交给 backend；其余键都用于填 PROMPT 模板。

Exports:
    run_agent -- 填占位符 → 派 backend → 校验末行 JSON → 返回结构化 dict。
    AgentOutputError -- agent 输出不合 OUTPUT_SCHEMA 契约（坏 JSON / 缺键 / 类型不符）时抛出。
    NeedsHumanRequest -- agent 以结构化控制结果请求 Vigil 停止自动推进、交给人处理。
"""

from __future__ import annotations

import json
from typing import Any


class AgentOutputError(Exception):
    """Raise when an agent's output breaks the OUTPUT_SCHEMA contract.

    Spec-0060/T2: agent 输出不合契约（坏 JSON / 末行非 JSON 对象 / 缺 schema 键 / 键类型不符）时抛出。
    """


class NeedsHumanRequest(Exception):
    """Agent 主动请求控制面停止自动推进并交给人处理。

    Spec-0075/T2：这是所有角色 OUTPUT_SCHEMA 之外的统一控制 envelope。Agent 只负责给出原因；
    forge 标签、评论、签名和 subject 归属全部由 Vigil 处理。
    """

    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


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
    _raise_needs_human(payload=parsed)
    _validate(payload=parsed, schema=agent_module.OUTPUT_SCHEMA)
    return parsed


def _raise_needs_human(*, payload: dict[str, Any]) -> None:
    """识别统一 needs-human envelope；形状不完整时 fail-visible。

    只要 payload 声明了 ``needs_human``，它就不能再退回普通角色 schema：否则拼错控制结果会被某个
    恰好兼容的角色静默接受。合法形状固定为 ``{"needs_human": true, "reason": "..."}``。
    """
    if "needs_human" not in payload:
        return
    if payload.get("needs_human") is not True:
        raise AgentOutputError(f"agent needs-human 控制结果要求 needs_human=true：{payload!r}")
    unexpected = set(payload) - {"needs_human", "reason"}
    if unexpected:
        raise AgentOutputError(
            f"agent needs-human 控制结果含未知键 {sorted(unexpected)!r}：{payload!r}"
        )
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise AgentOutputError(f"agent needs-human 控制结果缺少非空 reason：{payload!r}")
    raise NeedsHumanRequest(reason=reason.strip())


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
