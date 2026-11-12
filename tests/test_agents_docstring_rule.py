# Spec-0059/T2: The code generates ant-generated PROMPT into the anchor test of the docstring authoritative rule.

"""Assert every code-generating agent's PROMPT injects the two-layer docstring rules.

Unclaim `PROMPT.template` for implementer / draffer / replier (agent that will generate or modify Python source code)
Contains ** Modular Layer** Oords (`Exports:`/ Ban `\"\"\"#` / spec-id Up to `#` Comment) and ** Function Layer** Ods
(`Args:` / `Returns:` / `Raises:`/ message). Pure string assertion, untouched LLM/ network/ repository.

Exports:
    No object (pytest with example module) is exported.
"""

from __future__ import annotations

import pytest

from openagents.agents import drafter, implementer, replier

# Spec-0059/T2: Only three angents "can write Python source" into docstring rules; pure judgement agent and deliver do not inject.
_CODE_GENERATING_AGENTS = [implementer, drafter, replier]

# An anchor string for the Modular Layer rules: Column Export/ Ban ""# writing / spec-id moves up to top # comment.
_MODULE_LAYER_ANCHORS = ["Exports:", "file-level # comment", "help()"]

# The anchor line of the function layer rule: Args/Returns/Raises Structure + Prayer Point.
_FUNCTION_LAYER_ANCHORS = ["Args:", "Returns:", "Raises:", "imperative"]


@pytest.mark.parametrize(
    "module", _CODE_GENERATING_AGENTS, ids=lambda m: m.__name__.rsplit(".", 1)[-1]
)
def test_prompt_injects_module_layer_docstring_rule(module):
    template = module.PROMPT.template
    for anchor in _MODULE_LAYER_ANCHORS:
        assert anchor in template, (
            f"{module.__name__} PROMPT missing module layer docstring anchor {anchor!r}"
        )


@pytest.mark.parametrize(
    "module", _CODE_GENERATING_AGENTS, ids=lambda m: m.__name__.rsplit(".", 1)[-1]
)
def test_prompt_injects_function_layer_docstring_rule(module):
    template = module.PROMPT.template
    for anchor in _FUNCTION_LAYER_ANCHORS:
        assert anchor in template, (
            f"{module.__name__} PROMPT FUNCTION layer docstring anchor {anchor!r}"
        )


@pytest.mark.parametrize(
    "module", _CODE_GENERATING_AGENTS, ids=lambda m: m.__name__.rsplit(".", 1)[-1]
)
def test_prompt_cites_all_three_authorities(module):
    # The rule is to be traced to three authoritative criteria (PEP 257 / PEP 8 / Google § 3.8), which are identical to T1 communications.
    template = module.PROMPT.template
    for authority in ["PEP 257", "PEP 8", "Google"]:
        assert authority in template, (
            f"{module.__name__} PROMPT does not invoke authoritative criteria {authority!r}"
        )
