# SPDX-License-Identifier: Apache-2.0
"""Local distribution provenance; no changes to the upstream agent runtime."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

UPSTREAM_COMMIT = "5cd791b1382f1163621c9ff0b50c2cf01c4ba923"
UPSTREAM_REPOSITORY = "https://github.com/nex-agi/NexAU.git"
UPSTREAM_TREE = "5023e7f8ad6fe44e4f9c7e794f3495ec3340e000"


def verify_source(root: str | Path) -> dict:
    """Verify recorded upstream bytes and explicit local metadata additions."""
    root = Path(root).resolve()
    record = json.loads((root / "UPSTREAM.json").read_text(encoding="utf-8"))
    if record.get("revision") != UPSTREAM_COMMIT or record.get("repository") != UPSTREAM_REPOSITORY or record.get("git_tree") != UPSTREAM_TREE:
        raise ValueError("NexAU provenance identity differs")
    expected = {**record["files"], **record["local_files"]}
    for name, digest in expected.items():
        relative = Path(name)
        path = root / relative
        if relative.is_absolute() or ".." in relative.parts or path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError("Missing or unsafe NexAU source: " + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("NexAU source checksum differs: " + name)
    actual_package = {
        p.relative_to(root).as_posix() for p in (root / "nexau").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    if actual_package != {name for name in expected if name.startswith("nexau/")}:
        raise ValueError("Unrecorded or missing NexAU package files")
    return record
