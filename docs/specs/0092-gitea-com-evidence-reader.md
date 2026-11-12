---
number: "0092"
title: "Gitea.com-compatible evidence reading and capability declarations"
issue: 0
slug: gitea-com-evidence-reader
summary: "Support legacy gzip evidence and read ZIP, restrict signed-download boundaries, and provide auto-designer with actual runtime capability checks and joint acceptance testing."
e2e:
  intent: "The same evidence is actually retrieved by the reader through both the legacy self-hosted and Gitea.com paths, with no regression in the legacy path."
  method: "Use synthetic authorization evidence and a separate probe issue to verify that both gzip and ZIP packages produce correct read-only copies during real prepare runs; separately check the capabilities of the actual deployment, redirect authentication boundaries, and rejection cases."
architecture:
  objective: "Support ZIP and Gitea.com within the original issue evidence boundary while preserving legacy gzip support and role semantics."
  constraints:
    - "Existing gzip handles and handles without encoding remain valid; content authorization validation remains unchanged."
    - "Only the explicitly defined Gitea.com R2 profile may cross domains, and it must not carry Gitea authentication."
    - "Capability checks are offline and read-only and do not trigger self-updates."
  non-goals:
    - "Do not add an arbitrary URL downloader or modify ordinary forge APIs or role workflows."
  candidates:
    - id: additive-transport
      layer: evidence transport
      boundary:
        - "Attachments belonging to the current issue"
        - "Envelope with explicit encoding"
        - "Capabilities of the actual executable"
      evidence:
        - "Cross-repository gzip baseline passes"
        - "Gitea.com ZIP/303 probe"
        - "Legacy reader BadGzipFile"
      tradeoffs: "Maintain both encodings and a fixed hosted-download policy."
    - id: replace-all
      layer: protocol
      boundary:
        - "All historical attachments and readers"
      evidence:
        - "Existing deployments default to gzip"
      tradeoffs: "Unnecessarily requires all self-hosted users to upgrade and migrate."
  selected: additive-transport
  affected-components:
    - observations.evidence
    - utils.gitea
    - observations.capabilities
    - cli
  failure-modes:
    - "A degraded evidence-retrieval result must not be treated as success."
    - "Gitea authentication must not be leaked to object storage."
    - "Capability queries must not trigger software upgrades."
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: "Legacy gzip evidence and valid ZIP issue evidence each enter prepare."
      expected: "Obtain read-only historical files matching the session/digest."
      observation: "Combined checks using real prepare runs and offline fixtures."
    - id: BC2
      polarity: negative
      stimulus: "Unknown encodings, corrupt packages, attachments that do not belong to the issue, or redirects that are not allowed."
      expected: "Reject within defined bounds without sending cross-origin authentication."
      observation: "Negative decoding and transport cases, and checks of actual headers."
    - id: BC3
      polarity: positive
      stimulus: "Invoke the capability command in an empty directory with no credentials and network access disabled."
      expected: "Return only JSON, with no updates, file creation, or model calls."
      observation: "CLI subprocess tests and runtime image checks."
  repository-invariants:
    - "Ordinary CLI commands and GitHub workflows are unaffected."
    - "Legacy gzip support and existing authorization, digest, and path protections are preserved."
  exemptions: []
tasks:
  - id: T1
    title: "Dual-format evidence decoding compatible with legacy handles"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/observations/evidence.py
      - tests/test_observation_evidence.py
    scope: "Default to gzip and explicitly read encoding; perform bounded decompression of single-file ZIP archives, then reuse the existing issue/session/path/manifest validation and read-only handoff."
    acceptance: "Legacy/explicit gzip and ZIP succeed through real prepare runs; unknown encodings, corrupt archives, cross-issue evidence, malicious ZIP archives, and limit violations are all rejected."
  - id: T2
    title: "Restricted signed downloads exclusively for Gitea.com"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/gitea.py
      - tests/test_observation_transport.py
    scope: "Retain membership verification and same-origin direct downloads; allow only one specified R2 redirect from the authenticated attachment entry point; do not modify the general REST policy."
    acceptance: "Legacy self-hosted paths and valid hosted redirects pass; negative tests for API endpoints, spoofed domains, second redirects, bad statuses, budget violations, and token/cookie/netrc leakage pass."
  - id: T3
    title: "An actual reader capability command with no side effects"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - openagents/observations/capabilities.py
      - tests/test_observation_capabilities.py
      - tests/test_cli.py
    scope: "Register observation-capabilities and dispatch it early, before self-update, returning format/policy/budget JSON tied to the actual implementation."
    acceptance: "In an empty directory, with no credentials and networking disabled, return a single JSON value, with no files created or model/forge/git/uv calls; main(argv) behaves consistently with the real entry point, and ordinary commands show no regressions."
  - id: T4
    title: "Joint contract examples and upgrade acceptance testing"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - tests/fixtures/observation_transport_contract.json
      - scripts/check_observation_reader.py
      - tests/test_observation_reader_contract.py
      - docs/integrations/ahe-beta.md
      - docs/RELEASING.md
      - docs/cli.md
    scope: "Provide a stable cross-repository contract fixture and an entry point for real prepare checks; document the sequence of deploying the reader before enabling the writer, along with failure and rollback behavior."
    acceptance: "Verify interoperability between a pinned auto-designer producer and this reader; live testing uses synthetic probes only, verifies the actual scope/digest/read-only files, and does not count degradation notices as a pass."
---

# 0092 · Gitea.com-Compatible Evidence Reading and Capability Declarations

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Status: approved by the user; implementation and acceptance for T1–T4 are complete. The changes in the two repositories are coordinated candidates; the formal release has not yet been performed. The joint release SHA will be filled in after the reader is merged first.

Add ZIP support and Gitea.com signed attachment downloads to OpenAgents issue evidence reading, retain compatibility with historical gzip attachments on self-hosted Gitea, and provide a reader capability command with no side effects. The companion publisher specification is auto-designer `0070-gitea-com-evidence-transport.md`. This group extends only the boundaries of evidence acquisition and startup diagnostics; it does not change development phases, Issue permissions, the interpretation of historical files, or the semantics of returning supplemental diagnostics.

## Motivation

Currently, auto-designer builds JSON according to issue authorization, compresses it with gzip, uploads it as an attachment, and writes asset_id/sha256/bytes into an Issue machine comment. After verifying that the attachment belongs to that issue, the OpenAgents downloader requests the same-origin UUID URL; decode_package verifies the digest, always decompresses with gzip, and then validates the issue, session, paths, and manifest.

Tests on 2026-09-29 showed that Gitea.com rejects the current gzip attachment (422), accepts a valid ZIP (201), and redirects the attachment with a 303 to an R2 signed URL. The old downloader's NoRedirect policy and the old gzip-only parser block these two steps, respectively. prepare catches evidence acquisition exceptions and retains “Evidence unavailable” in the role context, so “the task can still run” does not mean that the evidence handoff succeeded.

The existing gzip round trip on internal Gitea already works and must remain supported. Adding ZIP does not require migrating old issues, nor does it allow the reader to acquire evidence from arbitrary external links.

## Guide-level explanation

The upgraded OpenAgents continues to read old gzip attachments and machine handles without a declared encoding from the original self-hosted instance. For Gitea.com experiments using the companion new version of auto-designer, it automatically reads explicitly marked ZIP attachments and provides the existing development roles with the same version-matched files and session scope.

Deployment programs can run `openagents observation-capabilities --json` in the actual runtime environment without model keys, repository configuration, or network access. It is a read-only machine interface: it does not initialize a project or trigger automatic updates. Ordinary vigil/issue command behavior remains unchanged. The publisher enforces this check only for new paths that require ZIP/R2; existing gzip users need no additional configuration.

Support for the new format must be deployed to the actual executable/image before enabling ZIP on the publisher. Merely modifying source code on a development machine or checking a version number is not evidence that the production runtime supports it.

## Reference-level explanation

### Shared Transport Contract for Both Repositories (This Section Must Remain Identical)

- The inner JSON `format` remains `auto-designer:observation-evidence-v1`; the semantics of issue, sessions, manifest, file paths, and digests remain unchanged. The Agent does not parse the transport protocol.
- Issue machine handles retain `asset_id/name/sha256/bytes`. Handles published using the old gzip format receive no additional fields; a missing `encoding` means gzip. New ZIP handles must include `encoding: "zip"`; the reader also permits explicit `encoding: "gzip"`. Unknown values or a mismatch between the declaration and the actual magic bytes must be rejected, with no automatic guessing or fallback.
- `sha256` and `bytes` always validate the compressed attachment actually downloaded. The transfer limit is 4,000,000 bytes, and the decompressed limit is 24,000,000 bytes. Limits must be enforced during actual reads; server or ZIP metadata alone cannot be trusted.
- A ZIP contains only one regular file, `evidence.json`, using UTF-8 and DEFLATE. Reject extra or duplicate entries, directories, links, encryption, and other compression algorithms. Read this entry only in memory, with bounds enforced; do not use extract/extractall. The publisher fixes the entry timestamp to 1980-01-01 00:00:00, fixes the file metadata, and uses compression level 6 to ensure that retries within the same fixed publishing runtime produce identical bytes. The internal JSON serialization rules remain unchanged.
- `same-origin-v1` retains the existing direct HTTP/HTTPS 200 path for self-hosted Gitea. The new `gitea-com-r2-v1` applies only to instances whose configured origin is exactly `https://gitea.com`, with the default port 443 and no subpath. Suffix matching must not be used to allow impersonating sites.
- Always first verify through the authenticated Gitea API that the attachment belongs to the current issue, then request the same-origin `/attachments/{uuid}`. Do not use external links in the body or `browser_download_url`. Only a 302/303/307/308 response for this authenticated attachment may enter a single restricted redirect. The target must use HTTPS and the default port 443, have no userinfo/fragment, and have a hostname that exactly satisfies the full rule `^[a-f0-9]{32}\.r2\.cloudflarestorage\.com$`. Reject other storage domains, IP literals, ports, and second redirects. This boundary is a fixed hosted-domain policy that relies on normal DNS/TLS and deployment proxies; it does not provide a general-purpose ability to download arbitrary URLs.
- Object storage uses a new request with no Gitea Authorization and no Cookie, and does not inherit session or .netrc authentication; explicitly configured network proxies are retained. The signed query is used only for this request and is not written to logs, exception bodies, or persistent state. Redirect hops share a total budget of 15 seconds for a single attachment download. Only a final 200 is accepted, and byte count and digest verification continue to apply. API requests still prohibit redirects.
- The capability command is `openagents observation-capabilities --json`, returning a single JSON object: `schema=openagents-observation-reader-capabilities-v1`, `marker=auto-designer:observation-evidence-v1`, `encodings=[gzip,zip]`, `zip_profile=single-evidence-json-v1`, `download_policies=[same-origin-v1,gitea-com-r2-v1]`, and the two byte limits above. Invocation requires no project, credentials, or network access, and does not self-update, create files, or call a model.
- The capability command must run inside the executable/image actually delivered. Set the existing switch `OPENAGENTS_NO_SELF_UPDATE=1` when querying so that older versions that do not yet recognize the command cannot self-update first. The formal delivery process for the new path likewise disables self-updates during execution and records the identity of the actual executable/image. The old pure gzip + same-origin path does not require the new command. Missing or unknown capabilities, timeouts, or mismatched budgets for ZIP or R2 paths must explicitly block execution before task dispatch/model invocation.

### Reading and Role Handoff

Add an optional encoding parameter to decode_package, defaulting to gzip, so existing calls remain valid. prepare reads encoding from the machine handle and uses the old gzip path when it is absent; download length/digest verification precedes decoding. After ZIP yields the original JSON, it enters the same issue, session, path, manifest, and file digest validation used by gzip, without duplicating content validation or depending on artifact log fields.

Each role invocation still writes a separate read-only copy and retains the authorized scope; deduplication and authorization for the old gap/outbox remain unchanged. Unknown formats, rejected downloads, or bad packages continue to use the existing “Evidence unavailable” handling, without presenting them as empty logs or success; errors must not expose signed URLs. Whether to block the entire development phase remains determined by the existing mechanism; this group adds no new general delivery gate. Combinations that require the new transport but have an unsupported runtime are intercepted by the publisher's startup preflight.

The download extension is confined to `utils.gitea.download_observation_asset` and does not change the policy of ordinary REST `_http`. The asset-list API retains its existing same-origin authentication and bounded reads; the external download client does not share Gitea authentication. Tests directly inspect the headers actually sent, the redirect count, and the budget, rather than merely checking that the configuration contains allow_redirects=False.

### Capability Command and Self-Update Boundary

`openagents/observations/capabilities.py` provides a stdlib-only JSON description and schema constants. The CLI performs exact early dispatch for this command before selfupdate.precheck, project resolve/init, forge configuration, or any network operation. It also registers the arguments in argparse to keep help and completion in sync. Both `main(argv=...)` and the actual sys.argv must be handled correctly; argument errors return only a usage error and do not fall through to self-update.

The selfupdate order for all existing ordinary commands remains unchanged. New capability-command test cases assert that selfupdate, git, uv, forge, and models are never called, and obtain a single line of valid JSON in an empty directory with no credentials and network access disabled, without creating any new files in the directory. When querying older versions for compatibility, the publisher still sets OPENAGENTS_NO_SELF_UPDATE to prevent an unknown command from triggering a self-update first.

Capability fields describe the reader implementation in this installation. Unit tests and cross-repository tests must tie the declarations to actual gzip/ZIP decoding and hosted download policies; tests that only return constants are insufficient. A budget or profile mismatch must cause the publisher to reject the new path; capabilities must not be guessed by comparing version strings.

### Task DAG and File Allocation

| Task | Responsibility | File ownership | Dependencies |
|---|---|---|---|
| T1 | Dual gzip/ZIP formats and handle validation | observations/evidence.py, existing evidence tests | None |
| T2 | Restricted R2 downloads for the current issue | utils/gitea.py, new transport tests | None |
| T3 | Capability command with no side effects | cli.py, new capabilities.py, new capability tests, CLI tests | T1, T2 |
| T4 | Joint contract examples, end-to-end scripts, and release notes | New contract fixture/cross-repository scripts, AUTO_DESIGNER/RELEASING/CLI documentation | T1, T2, T3 |

This repository does not edit auto-designer proxy configuration or image pins. The companion repository is responsible for on-demand egress in the two proxy templates, container public addresses, actual image builds, reader preflight checks, and publisher ZIP selection; this repository exposes verifiable capabilities and provides a readback script. The release order is this repository's reader → capability verification in the actual deployment → auto-designer publisher. Before rolling the writer back to the old version, first check whether the site supports gzip; if Gitea.com does not support it, stop new task dispatches rather than pretending a fallback is possible.

### Acceptance Criteria and End-to-End Entry Points

Implement `scripts/check_observation_reader.py`: offline by default, using contract fixtures to validate old gzip, explicit gzip, ZIP, incorrect encoding declarations, digests, sizes, issues, paths, and malicious ZIP files. Explicit live mode can invoke the real prepare against a test issue and requires scope to include the authorized session, a correct digest, and manifest/historical files that actually exist and are read-only. A return without an exception or a context containing “Evidence unavailable” must not count as success.

Cross-repository fixtures include an old handle, a ZIP handle with encoding, the expected contents of the same JSON, and expected reasons for rejection cases. The companion auto-designer cross-repository script must use real build/publish/decode/prepare operations, rather than merely comparing constants. CI may control network responses offline, followed by human-run probes to verify self-hosted/Gitea.com instances and actual containers/E2B.

Negative redirect cases cover unconfigured sites, impersonations of gitea.com, incorrect ports/userinfo, object-storage domain spoofing, API redirects, second redirects, non-200 targets, slow responses and exceeded limits, and cases where object storage receives Gitea token/cookie/netrc authentication. Negative ZIP cases cover multiple files, duplicate names, directories, links, encryption, non-DEFLATE compression, truncation/CRC errors, and actual decompressed data exceeding the limit. Existing negative cases for cross-issue access, digests, paths, and unauthorized supplementation remain valid.

### Actual Acceptance Record for 2026-09-29

- The full test suite in this repository reported 1440 passed; after the final addition of ZIP UTF-8 checks, the evidence-related suites reported 58 passed. Repository-wide Ruff, spec validate/render/graph, and diff check passed.
- Using the real publisher from a fixed auto-designer candidate and this reader, gzip/same-origin downloads from self-hosted Gitea and ZIP/R2 signed downloads from Gitea.com were verified separately on the host, in a Docker container, and in an independent E2B environment. For each site, real prepare returned 7 files for authorized-session, with matching contents, digest, and 0400 read-only permissions; no model was invoked.
- The Docker hosted path verified Gitea.com and R2 redirects through Squid on an internal network; default egress rules still reject hosted paths that have not been enabled. E2B used only separate short-lived probe sandboxes, all released afterward, without replacing or modifying the running N1 experiment.
- The actual acceptance image was `sha256:34a9bcafe9850fb9d8e8ee46cc9c93b09a1360c2bcf42f78a7eee3238b7fd271`, and the OpenAgents source-tree digest at build time was `f8046d481e42448c0faea57704d6d62142fe00c52766fd6a768eeeff43f54325`. This section and the derived indexes are acceptance metadata added after the build; runtime code did not change. Retain the original build record, and do not misrepresent this digest as the digest of the entire worktree after those additions.
- The two repositories are coordinated candidates. The image here was built before commit; the image and source-tree digests are actual verification artifacts, not formal release pins. The release SHA must wait until the reader is merged first, then be updated in the joint release order. Successful evidence transport does not mean that either the five-round model experiment or the complete new-user Quick Start has been completed.

## Drawbacks

Supporting two formats adds a small, bounded amount of decoding work and test maintenance. The hosted-domain policy also requires explicit updates as the actual Gitea.com deployment changes. Continuing to reject unknown targets sacrifices automatic adaptability, but prevents the originally restricted evidence retrieval entry point from becoming an arbitrary network downloader.

Capability declarations alone cannot prove actual network reachability or credential correctness; likewise, the reader's degradation notices cannot replace publisher-side startup failures and read-back acceptance testing in a real user's environment.

## Rationale and alternatives

Extend the smallest possible code surface within the existing, separate evidence and Gitea driver boundaries, preserving the inner JSON, original role context, and diagnostic loop. Explicitly treat a missing encoding as gzip to prevent new sniffing rules from changing the interpretation of old handles.

Changing only the publisher cannot address the old reader's gzip-only behavior and NoRedirect; replacing everything with ZIP would break older self-hosted combinations; globally enabling urllib redirects would affect ordinary API calls and could carry authentication along. Adding only a python -m capability module would provide a smaller entry point, but callers could easily use a different Python environment; instead, choose an early-dispatch command in the actual openagents executable, and verify it for self-update side effects. Having the business packages in the two repositories import each other as runtime dependencies would change the original CLI/forge boundary, so explicitly load the other repository's source only in a standalone joint-check script.

## Prior art

The existing artifact evidence handoff verifies historical files against the current issue's authorization, the manifest, and digests, and isolates read-only copies per invocation. The related 64 baseline tests and the joint gzip check using real functions have passed; a ZIP containing the same content produces BadGzipFile in the old reader. These facts show that content validation can be reused; they do not prove that the new ZIP/R2 implementation is complete.

The [Gitea configuration documentation](https://docs.gitea.com/1.22/administration/config-cheat-sheet/) describes attachment and signed-storage behavior; [Python zipfile](https://docs.python.org/3/library/zipfile.html) and [urllib.request](https://docs.python.org/3/library/urllib.request.html) provide interfaces for bounded decoding and independent downloads. The scope of site support is governed by actual probe results and the fixed policy in this document.

## Unresolved questions

The user has approved this document's formats, download boundaries, capability command, and reader-before-publisher sequence. The compatible commit SHA and actual image digest will be filled in after joint acceptance testing; version evidence will not be fabricated in advance.

## Future possibilities

Independently reviewed hosted-storage profiles may be added in the future; arbitrary cross-domain URLs will not be allowed in this set of changes. Keep the core evidence envelope unaware of events inside artifacts, so that future changes to the harness's log format do not require changes to this transport layer.
