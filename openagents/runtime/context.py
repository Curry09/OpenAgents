# Spec-0060/T5
"""Assemble role arguments and context from repository facts.

A Context binds a worktree, issue, branch, and PR. It reads issue and PR data
lazily through the forge interface, without making workflow decisions. Module
helpers build context for polling stages that already have the source records.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from openagents.runtime.state import RuntimeState

# Spec-0074/T1: arias-import switch - Platform operations are configured by github/gitea driver to call zero changes.
from openagents.utils import forge as github

# Spec-0093/T2: runner-owned policy follows a dispatch, never an issue/log instruction.
_EXECUTION_DISPATCH: ContextVar[tuple[RuntimeState, bool] | None] = ContextVar(
    "execution_dispatch", default=None
)


@contextmanager
def execution_dispatch(*, state: RuntimeState, required: bool):
    """Bind one delivery invocation; ContextVar prevents concurrent issue leakage."""
    token = _EXECUTION_DISPATCH.set((state, required))
    try:
        yield
    finally:
        _EXECUTION_DISPATCH.reset(token)


def execution_required(*, issue_number: int) -> bool:
    """Read or persist the independent requirement before an agent can see the issue."""
    scope = _EXECUTION_DISPATCH.get()
    if scope is None:
        return False
    state, required = scope
    return state.execution_requirement(issue_number=issue_number, required=required)


def sections(*items: tuple[str, str]) -> str:
    """Render non-empty dynamic prompt sections exactly once."""
    return "\n\n".join(
        f"--- {name} ---\n{text}" for name, text in items if isinstance(text, str) and text.strip()
    )


class Context:
    """# Spec-0060/T5: Context source for solve_issue run at a time - stage output placeholder

    tectonic locking work_dir (worktree path)/ issue_number/ lanch/ pr_number; read side inert tone
    utils.github (issue body, PR history). Gythub front for testing hermetic, issue/PR reading
    (Default real utils.github, test is fungible).
    """

    def __init__(
        self,
        *,
        work_dir: Path,
        issue_number: int,
        branch: str,
        pr_number: int | None = None,
    ) -> None:
        self._work_dir = Path(work_dir)
        self._issue_number = issue_number
        self._branch = branch
        self._pr_number = pr_number

    @property
    def workspace(self) -> Path:
        """Worktree Path - After Delivery Recide to gates.assert_head_advanced Read Objective Head."""
        return self._work_dir

    def for_plan(self, *, issue_number: int) -> dict:
        """Drafting placeholder: issue number + text."""
        return {
            "work_dir": self._work_dir,
            "context": self._issue_context(issue_number=issue_number),
            "issue_number": issue_number,
            "issue_body": self._issue_body(issue_number=issue_number),
        }

    def for_implement(self, *, issue_number: int) -> dict:
        """First round of issue/PR + empty feedback (feedback=”” for first round of tables)."""
        return {
            "work_dir": self._work_dir,
            "context": self._issue_context(issue_number=issue_number),
            "issue_number": issue_number,
            "pr_number": self._pr_number or 0,
            "feedback": "",
        }

    def for_iterate(self, *, issue_number: int, feedback: str) -> dict:
        """An iterative placeholder: Same as implement but with returnwer feedback."""
        payload = self.for_implement(issue_number=issue_number)
        payload["feedback"] = feedback
        return payload

    def for_review(self, *, issue_number: int) -> dict:
        """The placeholder at the evaluation stage: PR + issue text + PR hereafter."""
        return {
            "issue_number": issue_number,
            "work_dir": self._work_dir,
            "context": self._pr_context(issue_number=issue_number),
            "pr_number": self._pr_number or 0,
            "issue_body": self._issue_body(issue_number=issue_number),
        }

    def for_deliver(self, *, issue_number: int) -> dict:
        """Delivery stage placeholder: Branch name + PR number (deliver agent to resolve conflict with commit/push/)."""
        return {
            "work_dir": self._work_dir,
            "context": "",
            "branch": self._branch,
            "pr_number": self._pr_number or 0,
        }

    def _issue_body(self, *, issue_number: int) -> str:
        """Read the text of the issue (posters utils.github)."""
        return github.get_issue(number=issue_number).body

    def _issue_context(self, *, issue_number: int) -> str:
        """Contextline for drafting/realization: issue title + text."""
        issue = github.get_issue(number=issue_number)
        return f"issue #{issue.number}「{issue.title}」\n\n{issue.body}"

    def _pr_context(self, *, issue_number: int) -> str:
        """Contextline for the review stage: the text of the issue + PR historical review (no PR is given only to the text of the issue)."""
        base = self._issue_context(issue_number=issue_number)
        if self._pr_number is None:
            return base
        comments = github.list_comments(pr_number=self._pr_number)
        if not comments:
            return base
        history = "\n".join(f"- @{c.author}: {c.body}" for c in comments)
        return f"{base}\n\nPR #{self._pr_number} comment history:\n{history}"


# Spec-0061/T4: Cirque type recipe (vigil discovery / poll_comments watch) placeholder assembly.
#
# with `Context`（solve_issue Once. run Tie the death order. issue/PR）The blogger says:vigil PV issue Sweep, sweep.poll_comments PV
# PR Sweep, there is no "single context example of run at a time" so the placeholders for both phases are assembled in ** Modular Functions**: the reference is
# Recipe is a problem/comment object (no more second reading gutiub) that has been drawn in the dir/truct logic, and only pure assembly.


def for_triage(*, work_dir: Path, issue: object) -> dict:
    """Assemble the issue number and body from an existing discovery result."""
    return {
        "work_dir": Path(work_dir),
        "context": sections(("issue", f"issue #{issue.number}「{issue.title}」\n\n{issue.body}")),
        "issue_number": issue.number,
    }


def for_architecture(
    *, work_dir: Path, issue_number: int, design_digest: str, spec_text: str
) -> dict:
    """Build the pre-implementation architecture review context."""
    return {
        "work_dir": Path(work_dir),
        "context": spec_text,
        "issue_number": issue_number,
        "design_digest": design_digest,
    }


def for_reply(*, work_dir: Path, pr_number: int, branch: str, comment: object) -> dict:
    """Assemble the PR identifiers and human comment for the reply role."""
    return {
        "work_dir": Path(work_dir),
        "context": sections(("human comment", comment.body)),
        "pr_number": pr_number,
        "branch": branch,
    }


def for_issue_reply(*, work_dir: Path, issue_number: int, comment: object) -> dict:
    """Assemble the issue number and human comment for an issue-only reply.
    Spec-0016/T3.
    """
    return {
        "work_dir": Path(work_dir),
        "context": sections(("human comment", comment.body)),
        "issue_number": issue_number,
    }
