#!/usr/bin/env python3
"""Verify immutable NexAU Git pins and optional installed/paired project provenance."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit


def check(project: Path) -> dict[str, str]:
    """The declaration, lock and release manifest must agree on a full Git commit."""
    config = tomllib.loads((project / "pyproject.toml").read_text())
    lock = tomllib.loads((project / "uv.lock").read_text())
    dependencies = [
        *config["project"].get("dependencies", []),
        *config["project"].get("optional-dependencies", {}).get("nexau", []),
    ]
    declarations = [value for value in dependencies if value.startswith("nexau @ git+")]
    if len(declarations) != 1 or "nexau" in config.get("tool", {}).get("uv", {}).get("sources", {}):
        raise ValueError("NexAU must have one immutable Git dependency without a source override")
    package = next(item for item in lock["package"] if item["name"] == "nexau")
    if set(package["source"]) != {"git"}:
        raise ValueError("NexAU must resolve from Git, not a directory or registry")
    parsed = urlsplit(package["source"]["git"])
    repository = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    revision = parsed.fragment
    if (
        not re.fullmatch("[a-f0-9]{40}", revision)
        or parse_qs(parsed.query) != {"rev": [revision]}
        or declarations[0] != f"nexau @ git+{repository}@{revision}"
    ):
        raise ValueError("NexAU declaration and lock must agree on a full Git commit")
    if (project / "third_party/nexau").exists():
        raise ValueError("The obsolete embedded NexAU source must be removed")
    release = project / "release/compatibility.json"
    if release.is_file():
        pin = json.loads(release.read_text())["nexau"]
        if pin["commit"] != revision or pin["repository"].removesuffix(
            ".git"
        ) != repository.removesuffix(".git"):
            raise ValueError("NexAU release manifest disagrees with the locked Git dependency")
    return {"repository": repository, "revision": revision, "version": package["version"]}


def check_installed(expected: dict[str, str]) -> None:
    """PEP-610 records the commit actually installed by pip/uv from Git."""
    distribution = importlib.metadata.distribution("nexau")
    source = json.loads(distribution.read_text("direct_url.json") or "{}")
    vcs = source.get("vcs_info", {})
    if (
        distribution.version != expected["version"]
        or vcs.get("vcs") != "git"
        or vcs.get("commit_id") != expected["revision"]
        or source.get("url", "").removesuffix(".git") != expected["repository"].removesuffix(".git")
    ):
        raise ValueError("Installed NexAU does not match the locked Git source")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--other-project", type=Path)
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args()
    project = args.project or next(
        p for p in Path(__file__).resolve().parents if (p / "uv.lock").is_file()
    )
    expected = check(project)
    if args.other_project and check(args.other_project) != expected:
        raise ValueError("Paired repositories must use the same NexAU Git source and version")
    if args.installed:
        check_installed(expected)
    print(json.dumps({**expected, "installed_checked": args.installed}, indent=2))


if __name__ == "__main__":
    main()
