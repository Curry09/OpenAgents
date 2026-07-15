# Spec-0059/T2: 代码生成 agent 的 PROMPT 注入 docstring 权威规则的锚点测试。

"""Assert every code-generating agent's PROMPT injects the two-layer docstring rules.

针对 implementer / drafter / replier（会生成或修改 Python 源码的 agent）逐个断言其 `PROMPT.template`
含**模块层**锚点（`Exports:` / 禁 `\"\"\"#` 措辞 / spec-id 上移为 `#` 注释）与**函数层**锚点
（`Args:` / `Returns:` / `Raises:` / 祈使句提示）。纯字符串断言、不触真实 LLM / 网络 / 仓库。

Exports:
    无导出对象（pytest 用例模块）。
"""

from __future__ import annotations

import pytest

from openagents.agents import drafter, implementer, replier

# Spec-0059/T2: 只有「会写 Python 源码」的三个 agent 注入 docstring 规则；纯判断 agent 与 deliver 不注入。
_CODE_GENERATING_AGENTS = [implementer, drafter, replier]

# 模块层规则的锚点子串：列导出 / 禁 """# 写法 / spec-id 上移为顶部 # 注释。
_MODULE_LAYER_ANCHORS = ["Exports:", '"""#', "上移"]

# 函数层规则的锚点子串：Args/Returns/Raises 结构化 + 祈使句提示。
_FUNCTION_LAYER_ANCHORS = ["Args:", "Returns:", "Raises:", "祈使句"]


@pytest.mark.parametrize(
    "module", _CODE_GENERATING_AGENTS, ids=lambda m: m.__name__.rsplit(".", 1)[-1]
)
def test_prompt_injects_module_layer_docstring_rule(module):
    template = module.PROMPT.template
    for anchor in _MODULE_LAYER_ANCHORS:
        assert anchor in template, f"{module.__name__} 的 PROMPT 缺模块层 docstring 锚点 {anchor!r}"


@pytest.mark.parametrize(
    "module", _CODE_GENERATING_AGENTS, ids=lambda m: m.__name__.rsplit(".", 1)[-1]
)
def test_prompt_injects_function_layer_docstring_rule(module):
    template = module.PROMPT.template
    for anchor in _FUNCTION_LAYER_ANCHORS:
        assert anchor in template, f"{module.__name__} 的 PROMPT 缺函数层 docstring 锚点 {anchor!r}"


@pytest.mark.parametrize(
    "module", _CODE_GENERATING_AGENTS, ids=lambda m: m.__name__.rsplit(".", 1)[-1]
)
def test_prompt_cites_all_three_authorities(module):
    # 规则须溯源三个权威标准（PEP 257 / PEP 8 / Google §3.8），与 T1 conventions 同源。
    template = module.PROMPT.template
    for authority in ["PEP 257", "PEP 8", "Google"]:
        assert authority in template, f"{module.__name__} 的 PROMPT 未引用权威标准 {authority!r}"
