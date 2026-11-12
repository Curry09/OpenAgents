# Spec-0061/T2
"""Define reply prompts for issue comments and pull request comments.

Only the pull request role may implement and deliver code changes. Both roles
return a reply and whether it resolves the comment.
"""

from string import Template

PROMPT = Template(
    """You respond to a comment on PR #$pr_number (branch $branch).
1. Determine whether the comment asks a question, requests a change, or challenges an implementation.
2. Make changes only if needed. Follow the delivery protocol to commit and push them to the PR head.
3. Reply directly: answer the question, state what changed, or describe the blocker precisely.

When changing Python, follow PEP 257, PEP 8, and Google style §3.8. For modules, use an English summary
sentence ending with a period, a blank line, usage examples, and an Exports: entry for each exported
class, exception, or function. For __init__.py, also list submodules and packages. Put the Spec ID in a
file-level # comment, like argparse.py's # Author:, never inside the docstring where help() would show it.
For functions and classes, use an imperative summary of at most 80 characters ending in a period, then
the Spec-NNNN/Tn reference on line two. Use Args:, Returns:, and Raises: for structured details.

Set resolved=true only when this response and any changes fully address the comment. If a person must
decide or provide more information, set resolved=false and name what is missing in reply.

Return one line of JSON with a string reply and boolean resolved.
Read the comment once in the context below.
"""
)

# Spec-0016/T3: Reply to issue comments without starting implementation (#149).
# This role has no working branch and does not use the delivery protocol.
# Both reply roles share the same reply and resolved schema.
ISSUE_PROMPT = Template(
    """You respond to a new comment on issue #$issue_number.
1. Identify the request: a follow-up question, a new requirement, or a correction.
2. Reply only. The issue is still being clarified. Answer the question, clarify your understanding, or
   acknowledge the comment and restate the planned work. Do not edit code or open a PR; that happens
   during the solve stage.
3. Be direct and specific. If you cannot answer or the decision is outside your authority, explain why.

Set resolved=true only when the reply fully addresses the request. If a person must decide or provide
more information, set resolved=false and name what is missing in reply.

Return one line of JSON with a string reply and boolean resolved.
Read the comment once in the context below.
"""
)

OUTPUT_SCHEMA = {"reply": str, "resolved": bool}
