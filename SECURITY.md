# Security

English | [简体中文](SECURITY.zh-CN.md)

This project is currently intended for trusted local research and development environments. Agents can execute commands, modify repositories, and call external models; delivery workflows may merge PRs automatically. Configure access to Docker sockets, host CLIs, and model gateways for your deployment. Do not expose live observation APIs publicly without authentication.

To report a security issue, prefer [GitHub private vulnerability reporting](https://github.com/Curry09/OpenAgents/security/advisories/new) (maintainers need to enable it before public release). If that entry point is unavailable, use an existing private contact with a maintainer to arrange a reporting channel. Do not post real credentials, directly exploitable details, or raw user conversations in public issues.

For ordinary bugs, use an issue template and provide the version, environment, sanitized reproduction steps, and expected behavior. Never upload `.env` files, complete profiles, tokens, unprocessed logs, or experiment archives.

Before the first public release, scan the entire Git history and all release assets, and address each finding. Rotate any exposed credentials that are still valid first. `.gitignore` and snapshot filters do not replace a history scan, nor do they guarantee that all logs produced by external services or tools have been sanitized.

The project does not yet have a separate long-term security maintenance branch or a committed response time. Release notes will identify the supported versions when a release is published.
