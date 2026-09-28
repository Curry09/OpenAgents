"""Spec-0091: cheap advice, never authoritative dependencies."""

from string import Template

PROMPT = Template("""Give a SMALL, advisory coordination plan for the supplied ready issues.
Use only the supplied snapshot. Do not call tools, inspect files, implement, or contact the forge.
Some bodies may be clipped: uncertainty means omit the hint, not invent a requirement.
The original issues and all independent acceptance criteria remain authoritative.
Each issue keeps its own delivery and acceptance. Do not propose splitting an issue into PRs,
substituting another issue's delivery, or treating a broader proposal as acceptance of this one.
File locations reported in issue text are unverified claims, not inspected source evidence.
Identify likely shared implementation mechanisms, useful reuse advice and tentative ordering.
Shared files do NOT imply a hard dependency. Developers may correct every suggestion.
Do not merge, drop, rewrite, or require coverage of all issues. No hard blocked_by edges.
At most 8 entries in EACH array. Keep advice under 400 characters. Return JSON:
{"clusters":[{"issues":[1,2],"region":"mechanism","first_issue":1,"advice":"..."}],
 "suggested_order":[{"issue":2,"after":1,"reason":"..."}],
 "notes":[{"issues":[1],"advice":"..."}]}
Empty arrays are valid. Use real issue numbers from the snapshot only.
""")
OUTPUT_SCHEMA = {"clusters": list, "suggested_order": list, "notes": list}
REPAIR_OUTPUT = False
