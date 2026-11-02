# Releasing

English | [简体中文](RELEASING.zh-CN.md)

OpenAgents is versioned independently. A paired AHE-Beta release identifies a tested combination of repository commits and deployment artifacts; the two projects do not need matching version numbers.

## Prepare a candidate

Start from the intended `main` commit, update package versions and release notes, and run the [verification checks](VERIFICATION.md). Build the wheel and source distribution with `uv build`. Verify installation outside the source tree, including the optional NexAU backend when it is part of the release.

Use the committed lockfile for source verification. A uv tool install resolves package metadata in a separate environment; it does not reproduce the complete development lockfile. The NexAU extra contains a fixed Git dependency, so validate the distribution channel's direct-reference policy before selecting it for package publication.

For a paired release, record:

- Both repository commits or immutable tags.
- The pinned NexAU source and any other runtime dependency versions.
- The actual delivery image digest or installed package identity.
- Configuration profile, platform, and validation results.

[`release/compatibility.json`](../release/compatibility.json) is a historical preparation baseline, not a declaration that current main has been jointly released. Preserve its historical identifiers; write the actual candidate manifest into release assets rather than inventing future commit hashes.

## Validate the deployment

Run the cross-repository configuration and observation checks against the selected pair. For evidence-enabled deployments, query `observation-capabilities --json` in the actual executable or image, disable self-update, and verify synthetic evidence through the actual forge/network path. Enable a new publisher capability only after the deployed reader supports it.

Verify both successful delivery and expected refusal/recovery. Record blocked or unverified checks separately. Review release assets and logs for credentials and restricted third-party content, following [Security](../SECURITY.md) and [Third-party sources](../THIRD_PARTY.md).

## Publish

1. Freeze the tested candidate and build assets with checksums and a version manifest.
2. Test installation and downloads from a draft or prerelease.
3. Create the immutable version tag and publish the release notes and assets.
4. For a paired release, make the OpenAgents artifact available first, then pin and validate the controller against it; link the two releases.

`openagents release --bump patch|minor|major` is a **target-repository operation**: it checks runtime failures and main CI, then pushes a `release/vX.Y.Z` branch and tag from the local `main` ref. Ensure that ref is current. The command does not build wheels, create a GitHub Release, or change repository visibility.

If a candidate fails validation, fix it and issue a new candidate. Do not move a published tag or overwrite an existing experiment's frozen versions. When rolling back evidence transport, confirm that the selected forge accepts the previous format; otherwise stop new dispatches until a compatible path is available.
