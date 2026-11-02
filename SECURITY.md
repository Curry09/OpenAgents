# Security

English | [简体中文](SECURITY.zh-CN.md)

OpenAgents runs in trusted development environments. Agents execute commands, modify repositories, and call external models; delivery workflows can merge PRs automatically. Grant access to repositories, host tools, and model services according to the deployment's needs. Keep the local observation API bound to a trusted interface unless access control is provided separately.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/Curry09/OpenAgents/security/advisories/new) when it is available. Otherwise, contact a maintainer through an existing private channel to arrange a report. Do not publish credentials, exploitable details, or raw conversations in a public issue.

For ordinary bugs, use an issue template and include the version, environment, sanitized reproduction steps, and expected behavior.

## Credentials and runtime records

Store credentials outside version control. Review logs, invocation traces, screenshots, and experiment archives before sharing: they may contain task content or data returned by external tools. Redaction in one ledger does not guarantee that all other records are sanitized. Do not upload `.env` files or complete user profiles.

When preparing a public source snapshot or release, inspect Git history as well as distribution assets. `.gitignore` and snapshot filters do not remove already committed data. Revoke exposed credentials and assess the affected records before redistributing them.

## Maintenance

There is currently no separate long-term security maintenance branch or guaranteed response time. Release notes will identify any supported release branches.
