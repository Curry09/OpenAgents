# Verification Checklist

Use this checklist when verifying a subtask implementation (Phase 3).

## Automated Checks

- [ ] **Lint** passes — `uv run ruff check .`
- [ ] **Format** passes — `uv run ruff format --check .`
- [ ] **Unit tests** pass with >= 80% coverage on changed files (or project-defined threshold) — `uv run pytest tests/ -v`
- [ ] **Integration tests** pass with full functional coverage for the RFC scope

## Code Quality

- [ ] RFC ID referenced in code comments (see `code-comment-conventions.md`):
  - Module docstring, function/class docstring, inline step comments, struct/field docs
- [ ] Only the files allocated to this subtask were touched (no overlap with other subtasks' file lists)
- [ ] No unrelated changes included in the PR
- [ ] No hardcoded secrets or credentials
- [ ] Follows CLAUDE.md Python conventions (no positional-only params; private `_` functions require explicit args, no defaults)

## Git Hygiene

- [ ] Branch is rebased on latest main (linear history)
- [ ] All tests pass AFTER rebase
- [ ] Commit messages follow Conventional Commits and reference the RFC
- [ ] One subtask = one PR

## Human Verification

- [ ] AI Review summary provided for human to approve/reject
- [ ] Human test plan provided with step-by-step instructions
- [ ] Human has executed the test plan and confirmed functionality

## Failure Handling

If any check fails:
1. Fix the issue and re-run all checks
2. If the subtask plan itself is flawed, document the issue, revert completely, and update the RFC's subtask definition
3. Never merge a failing PR to main
