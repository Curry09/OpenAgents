# Spec-0065/T1
"""Propose blocking dependencies for new issues.

Existing edges anchor the proposal and are never reordered or removed by the
role. Vigil validates suggestions and writes them through the forge driver.
"""

from string import Template

PROMPT = Template(
    """You order issue dependencies. Read the snapshot of open, ready issues and identify where an issue
must wait until another issue's PR is merged.

There are two reasons to order work:
1. Logical dependencies: A defines or changes an interface, data model, or contract that B needs, even if
   they touch different files.
2. Write conflicts: A and B will change the same files and cannot safely proceed in parallel. Require evidence
   of overlap; otherwise use the logical dependency test.

Existing edges are read-only anchors set by a person or a previous run. Do not reorder or delete them, and
do not add edges for issues that already have incoming edges. Suggest edges only for nodes without them.

Apply the fail-open rule: add an edge only when the dependency is real and the wrong order would misdirect the later
implementation or create a write conflict. Treat uncertain pairs as independent. Invented dependencies
block work; the execution side rechecks live GitHub state.

Return one line of JSON: {"edges":[{"issue":2,"blocked_by":[1],"rationale":"Why this order is required"}]}.
If there are no new dependencies, return {"edges":[]}.

Read the ready issue snapshot and existing edges once in the context below.
"""
)

OUTPUT_SCHEMA = {"edges": list}

__all__ = ["PROMPT", "OUTPUT_SCHEMA"]
