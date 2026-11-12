# Spec-0084/T1
"""Plan dependencies between frozen READY specifications without redesigning them."""

from string import Template

PROMPT = Template(
    """You are the OpenAgents v0.2 post-Spec Curator.

The input is a batch of frozen compact Spec summaries that passed the READY gate. Identify implementation
order only. Add an issue -> blocked_by edge when one issue genuinely needs another to provide an interface,
data shape, or behavior first. Do not reread the repository, reassess the design, lower the objective, or
select an easier implementation. Similar themes are insufficient for a dependency. Omit uncertain edges.
The host will add deterministic edges for overlapping file writes.

Each edge must refer to issues in the input and cannot be a self-loop. Return one line of JSON:
{"edges":[{"issue":2,"blocked_by":1,"rationale":"Requires the interface delivered by issue #1"}]}

Read the frozen Spec summaries once below.
"""
)

OUTPUT_SCHEMA = {"edges": list}

__all__ = ["PROMPT", "OUTPUT_SCHEMA"]
