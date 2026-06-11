# Verification Checklist

Use this checklist when verifying a Task implementation (Phase 3).

## Automated Checks

- [ ] **Lint** passes — `uv run ruff check .`
- [ ] **Format** passes — `uv run ruff format --check .`
- [ ] **Unit tests** pass with >= 80% coverage on changed files (or project threshold) — `uv run pytest tests/ -v`
- [ ] **Integration tests** pass with full functional coverage for the Task scope
- [ ] **Spec valid** — `uv run spec validate` is error-free
- [ ] **OVERVIEW drift-free** — `uv run spec render` then `git diff --exit-code docs/specs/OVERVIEW.md` (no diff)

## Code Quality

- [ ] Spec id referenced in code comments (see `code-comment-conventions.md`): module docstring, function/class docstring, inline step comments, struct/field docs
- [ ] Only the files in this Task's `files` list were touched (no overlap with other Tasks)
- [ ] No unrelated changes in the PR
- [ ] No hardcoded secrets or credentials
- [ ] Follows CLAUDE.md Python conventions (no positional-only params; private `_` functions require explicit args, no defaults)

## Git Hygiene

- [ ] Branch is rebased on latest base (`test`), linear history
- [ ] All tests pass AFTER rebase
- [ ] Commit messages follow Conventional Commits and reference the spec id
- [ ] One Task = one PR

## Human Verification

- [ ] AI Review summary provided for human to approve/reject
- [ ] Human test plan provided with step-by-step instructions
- [ ] Human has executed the test plan and confirmed functionality

## Failure Handling

If any check fails:
1. Fix the issue and re-run all checks.
2. If the Task plan itself is flawed, document the issue, revert completely, and `spec amend` the Task definition with lessons learned (old version goes to history).
3. Never merge a failing PR.
