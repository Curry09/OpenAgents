"""Spec-0092/T3: offline declarations of this installation's evidence reader."""

import json

SCHEMA = "openagents-observation-reader-capabilities-v1"


def describe() -> dict:
    """Return the versioned contract without loading a project or reading credentials."""
    return {
        "schema": SCHEMA,
        "marker": "auto-designer:observation-evidence-v1",
        "encodings": ["gzip", "zip"],
        "zip_profile": "single-evidence-json-v1",
        "download_policies": ["same-origin-v1", "gitea-com-r2-v1"],
        # Spec-0093/T1: exercised by check_observation_reader, not just a module claim.
        "execution_evidence": {
            "schema_versions": [1],
            "required_dispatch": True,
            "context_projection": "all-delivery-roles-v1",
        },
        "max_transfer_bytes": 4_000_000,
        "max_expanded_bytes": 24_000_000,
    }


def emit() -> int:
    print(json.dumps(describe(), sort_keys=True))
    return 0
