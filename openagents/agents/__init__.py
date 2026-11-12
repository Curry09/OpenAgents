# Spec-0060/T4, Spec-0064/T6
"""Define role prompts and output schemas.

Each role module exports a string.Template and its output schema. Recipes
choose which role runs; runtime.engine renders and validates the result.
"""

from openagents.agents import deliver, drafter, implementer, replier, reviewer, tester, triager

__all__ = ["drafter", "implementer", "reviewer", "deliver", "tester", "triager", "replier"]
