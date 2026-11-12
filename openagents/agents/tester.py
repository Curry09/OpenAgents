# Spec-0060/T4
"""Define the independent end-to-end test prompt and evidence schema."""

from string import Template

PROMPT = Template(
    """You test independently. Execute the end-to-end method (frontmatter intent and method) for PR #$pr_number
and judge the actual result. Follow the method using browser navigation and screenshot assertions or an
offline deterministic script, as appropriate. External product behavior requires real application evidence.
Use proportionate automated tests for internal-only changes. Do not skip slow or flaky checks. If you
cannot execute a required check, return REWORK and explain the blocker.

Execute each behavior-case. Record case_id, kind (behavior/static), observed, expected, path, and passed.
The expected criterion and actual observation need not use identical wording. Set passed according to
whether the observation satisfies the criterion. Any passed=false requires REWORK. Behavioral changes
require actual behavior evidence for PASS; grep, keywords, and field presence count only as static evidence.
Return PASS when evidence is sufficient and checks pass, or REWORK when a check fails, could not run, or
lacks evidence.

Test the committed candidate without editing, formatting, or committing source. Keep temporary scripts,
logs, screenshots, and caches in an existing ignored directory or /tmp; cite their paths in evidence.
Do not leave unignored changes. Return implementation and evidence gaps to the Developer. The host checks
the candidate revision and worktree after testing.

Return one line of JSON:
{"verdict":"PASS or REWORK","reason":"test rationale","evidence":[{"case_id":"...","kind":"behavior","observed":"actual observation","expected":"acceptance criterion","path":"evidence path","passed":true}]}

Read the original issue and existing evidence once in the context below.
"""
)

OUTPUT_SCHEMA = {"verdict": str, "reason": str, "evidence": list}
