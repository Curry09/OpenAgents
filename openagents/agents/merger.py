# Spec-0017/T3
"""Define the final merge action after deterministic gates pass.

The caller supplies forge-specific commands bound to the approved head.
"""

from string import Template

PROMPT = Template(
    """You merge PR #$pr_number. The runtime has checked that CI is green and approval is bound to the
current head. Execute the supplied operation:

`$merge_command`

The candidate SHA in the command is the approval boundary. Do not remove or replace it or use a merge
command without that condition. If the version changes, return without merging and let the host review again.

Run `$verify_command`. An output containing "MERGED" confirms success. An already merged PR is a successful no-op.

If the merge fails or an uncovered condition blocks it (such as branch protection or a changed base),
do not force the merge, loop, claim success, or change forge labels. Return one line of JSON:
{"merged":false,"summary":"specific blocker and verified facts"}
On success return {"merged":true,"summary":"one sentence about the merge"}.
"""
)

OUTPUT_SCHEMA = {"merged": bool, "summary": str}
