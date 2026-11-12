# Spec-0060/T4
"""Define the Git delivery prompt and delivery receipt schema.

Delivery covers the working branch only. The caller verifies the pushed head
and handles draft promotion.
"""

from string import Template

PROMPT = Template(
    """You deliver changes for branch $branch, PR #$pr_number. Put the work on the actual PR head:
1. Record the current local HEAD as base_sha for cross-checking. It does not establish delivery.
2. Run git status. Finish any in-progress rebase, merge, or cherry-pick before making a new commit.
   If there are uncommitted changes to deliver, use `git add -A && git commit -m "<meaningful message>"`.
   If already committed, only finish the push. Do not create empty commits or reuse a fixed message.
3. Capture the remote branch baseline with `BASE=$$(git rev-parse origin/$branch)`, then run
   `git fetch origin $branch $rebase_onto`. Capture BASE before the fetch changes the tracking ref;
   otherwise the lease can be equivalent to an unconditional force push.
4. Rebase onto `origin/$rebase_onto`. Read conflict markers, preserve both sides' intent, and use
   `git add -A && git rebase --continue` until complete. Do not abort or set automation-failed.
5. If the repository has docs/specs/ and a spec CLI, run spec validate, spec render, and spec graph in
   that order before pushing. Include generated files in the commit and rerun affected checks.
   Do not handwrite generated files.
6. Run `git push --force-with-lease=$branch:$$BASE origin HEAD:$branch`. The conflict worktree may be
   detached, so push its HEAD to the explicit working branch. Never use a bare force push. Use the lease
   only for $branch, never main, protected branches, or someone else's branch.

Delivery requires a successful push, no undelivered worktree changes, and origin/$branch equal to HEAD.
If everything was already delivered, verify and return; do not manufacture a new commit. Leave ignored
caches out. Vigil handles draft promotion from PR state; do not call the forge CLI or API to promote it.

Return one line of JSON. Use the pre-delivery HEAD from step 1 for base_sha and the delivered HEAD for head_sha:
{"delivered":true,"base_sha":"pre-delivery HEAD","head_sha":"delivered HEAD","summary":"one sentence including whether rebase conflicts were resolved"}.
Set delivered=false if the delivery criteria are not met.
"""
)

OUTPUT_SCHEMA = {"delivered": bool, "base_sha": str, "head_sha": str, "summary": str}
