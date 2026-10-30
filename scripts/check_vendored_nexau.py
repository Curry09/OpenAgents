#!/usr/bin/env python3
"""Check frozen SDK integrity and local lock resolution without third-party imports."""

from __future__ import annotations

import json
import runpy
import tomllib
from fnmatch import fnmatch
from pathlib import Path


def check(root: Path) -> dict:
    """Reject changed source bytes, unrecorded modules, or remote SDK resolution."""
    vendor = root / "third_party/nexau"
    namespace = runpy.run_path(str(vendor / "nexau/_vendor_info.py"))
    origin = namespace["verify_source"](vendor)
    project = tomllib.loads((root / "pyproject.toml").read_text())
    lock = tomllib.loads((root / "uv.lock").read_text())
    upstream = tomllib.loads((vendor / "pyproject.toml").read_text())
    patterns = upstream["tool"]["setuptools"]["package-data"]["nexau"]
    runtime = {
        name.removeprefix("nexau/"): digest
        for name, digest in origin["files"].items()
        if name.startswith("nexau/")
        and (
            name.endswith(".py")
            or any(fnmatch(name.removeprefix("nexau/"), pattern) for pattern in patterns)
        )
    }
    if origin["runtime_files"] != runtime:
        raise ValueError("NexAU runtime manifest differs from the upstream package contents")
    dependencies = [
        *project["project"].get("dependencies", []),
        *project["project"].get("optional-dependencies", {}).get("nexau", []),
    ]
    expected = f"nexau=={origin['version']}"
    if expected not in dependencies:
        raise ValueError("Root project must declare the vendored NexAU version")
    source = project["tool"]["uv"]["sources"]["nexau"]
    if source != {"path": "third_party/nexau"}:
        raise ValueError("NexAU must resolve from the checked-in source directory")
    package = next(item for item in lock["package"] if item["name"] == "nexau")
    if package["source"] != {"directory": "third_party/nexau"}:
        raise ValueError("uv.lock must resolve NexAU locally, without Git or PyPI")
    if (
        package["version"] != origin["version"]
        or upstream["project"]["version"] != origin["version"]
    ):
        raise ValueError("NexAU metadata and lock versions disagree")
    return {
        "revision": origin["revision"],
        "upstream_files_verified": len(origin["files"]),
        "runtime_files": len(origin["runtime_files"]),
        "source": "third_party/nexau",
    }


if __name__ == "__main__":
    root = next(
        p
        for p in Path(__file__).resolve().parents
        if (p / "third_party/nexau/UPSTREAM.json").is_file()
    )
    print(json.dumps(check(root), indent=2))
