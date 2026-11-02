# AHE-Beta integration

English | [简体中文](ahe-beta.zh-CN.md)

[AHE-Beta](https://github.com/Curry09/AHE-Beta) runs simulated-user experiments, collects feedback, and generates Harness improvement requests. OpenAgents implements those requests in the Harness repository through issues and PRs. The next user round runs the resulting version; OpenAgents does not run the controller's experiment or independent benchmark evaluation.

## Installation and generated configuration

Install the backend needed by the controller's selected delivery environment. Claude Code needs the external CLI; NexAU needs the `nexau` extra, `OPENAGENTS_BACKEND=nexau`, and exported `OPENAGENTS_NEXAU_MODEL`, `OPENAGENTS_NEXAU_BASE_URL`, and `OPENAGENTS_NEXAU_API_KEY`. NexAU uses the Anthropic-compatible Messages API. Installation and endpoint details are in the [configuration guide](../CONFIGURATION.md).

The controller generates `.openagents/openagents.yml` in its delivery repository. Current configuration uses Gitea, the default `standard` flow, soft coordination, and agent review. E2e is skipped; CI is skipped by default and may be enabled by the local experiment's CI policy. Execution-condition evidence is required. This differs from the standalone defaults, where all configurable stages use agents.

Configure experiments through AHE-Beta's `backend/scripts/experiment.py` entry point and its public experiment configuration. Generated OpenAgents YAML may be rewritten; editing it is not a durable way to change the experiment. The standalone `v02` batch command is a separate workflow, not an alias for the controller's delivery round.

The delivery process needs Git and API access to the same Gitea repository. For E2B deployments, use an address reachable from the sandbox; `127.0.0.1` refers to that sandbox, not the operator's machine. Pin the actual OpenAgents executable or image and set `OPENAGENTS_NO_SELF_UPDATE=1` to keep it fixed.

## Observation evidence

The controller publishes authorized session evidence as an issue attachment. OpenAgents supports gzip and ZIP; ZIP must contain only `evidence.json` and declare its encoding. A handle without an encoding is interpreted as gzip. Hashes, issue/session authorization, size limits, and file-path checks apply to both formats.

For Gitea.com, the reader permits the attachment endpoint's constrained signed HTTPS redirect to its supported R2 storage host. Requests to external storage do not carry the Gitea token, cookies, or `.netrc` authentication. Other sites use direct same-origin downloads. An unexpected storage host is rejected rather than permitting arbitrary redirects.

Before enabling a publisher format, inspect the reader **inside the actual delivery environment**:

```bash
OPENAGENTS_NO_SELF_UPDATE=1 openagents observation-capabilities --json
```

The capability object declares gzip/ZIP, `single-evidence-json-v1`, and the supported download policies. Older gzip attachments need no migration. Internal protocol markers retain their established names for wire compatibility; the project name does not change those identifiers.

## Execution conditions

The controller enables this in trusted project configuration:

```yaml
execution_evidence:
  required: true
```

The requirement is stored with dispatched work, so restarting with a default configuration cannot silently downgrade it. Missing or invalid required evidence blocks model dispatch. Vigil releases the slot and waits for repaired evidence; the explicit batch runner records a failed node that can be retried after repair.

The shared context preserves each source's original goal and public deliverables, whether further user input is available, its budget, and safe independent-assessment summaries. Large source sets are explicitly paged. Historical conversations remain evidence rather than instructions. A `passed: null` assessment has no binary verdict; an observed task failure does not by itself establish a Harness defect or disqualify a candidate.

Private graders, answer files, and hidden evaluation plans must remain outside role context. Required-evidence delivery does not itself add an independent benchmark gate.

## Verify a pair

Run AHE-Beta's configuration and observation contract checks against the intended OpenAgents checkout, then run the reader probes and a live synthetic readback in the deployment network. Commands and validation boundaries are in [Verification](../VERIFICATION.md). A capability declaration or successful degraded delivery does not replace verified read-only evidence and final role-context checks.

Record both repository commits and the deployed package/image identity. See [Releasing](../RELEASING.md) for paired version manifests and rollout order.
