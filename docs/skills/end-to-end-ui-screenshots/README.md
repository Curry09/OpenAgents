# UI verification guide

This directory provides optional, reusable guidance for verifying a running application. It is not installed or loaded automatically by OpenAgents. Runtime responsibilities remain defined by the current implementer, tester, and reviewer roles under `openagents/agents/`.

## Contents

- [SKILL.md](SKILL.md): evidence selection and verification procedure.
- [Runbook template](references/_runbook-template.md): project-specific setup and reproduction details.
- [Reference-page example](references/reference-app.md): a small browser exercise using the included HTML page.

To make the guide available as a Claude Code skill, copy this directory into the target project's skill directory:

```bash
mkdir -p /path/to/your-project/.claude/skills
cp -R docs/skills/end-to-end-ui-screenshots /path/to/your-project/.claude/skills/
```

Installation is optional and changes that project's available skills. Adapt a copy of the runbook template to its actual commands, endpoints, and test data. Do not copy deployment-specific paths from another project.

For a real UI behavior, drive the application and capture the relevant state. For behavior that is not visible in the UI, collect runtime evidence and the actions that produced it. Internal refactors should use proportionate automated checks. None of these evidence types should be presented as proving a different layer of behavior.

Keep artifacts in an ignored or external evidence directory while checking a delivered candidate. Review and sanitize selected artifacts before attaching them to a PR or publishing them. A missing browser, service, or permission means the affected behavior remains unverified.

Current repository-wide checks are described in [Verification](../../VERIFICATION.md). Historical Spec-specific scripts may reference retired modules; they are not the current verification entry point.
