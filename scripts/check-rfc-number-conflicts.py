#!/usr/bin/env python3
"""检查 RFC 文件编号是否在本地或其它 open PR 之间冲突。

仓库约定：RFC markdown 文件放在 docs/rfcs/NNNN-slug.md，
可选的元数据放在 docs/rfcs/meta/NNNN-slug.json。
同一个 RFC 编号可以同时拥有这两个文件，但不能被不同的 slug 复用。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

RFC_PATH_RE = re.compile(r"^docs/rfcs/(?:meta/)?(?P<number>\d{4})-(?P<slug>[^/]+)\.(?:md|json)$")
NEW_RFC_CHANGE_TYPES = {"ADDED", "RENAMED"}


def _run_gh(args: list[str]) -> Any:
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh command failed")
    return json.loads(result.stdout or "[]")


def _extract_rfc_identity(path: str) -> tuple[str, str] | None:
    match = RFC_PATH_RE.match(path)
    if not match:
        return None
    return match.group("number"), match.group("slug")


def _iter_repo_rfc_paths(repo_root: Path) -> list[str]:
    paths: list[str] = []
    rfc_dir = repo_root / "docs" / "rfcs"
    meta_dir = rfc_dir / "meta"

    if rfc_dir.exists():
        paths.extend(
            str(path.relative_to(repo_root))
            for path in sorted(rfc_dir.glob("*.md"))
            if _extract_rfc_identity(str(path.relative_to(repo_root)))
        )
    if meta_dir.exists():
        paths.extend(
            str(path.relative_to(repo_root))
            for path in sorted(meta_dir.glob("*.json"))
            if _extract_rfc_identity(str(path.relative_to(repo_root)))
        )
    return paths


def _find_local_conflicts(repo_root: Path) -> list[str]:
    by_number: dict[str, dict[str, list[str]]] = {}
    for path in _iter_repo_rfc_paths(repo_root):
        identity = _extract_rfc_identity(path)
        if not identity:
            continue
        number, slug = identity
        by_number.setdefault(number, {}).setdefault(slug, []).append(path)

    conflicts: list[str] = []
    for number, paths_by_slug in sorted(by_number.items()):
        if len(paths_by_slug) <= 1:
            continue
        parts = []
        for slug, paths in sorted(paths_by_slug.items()):
            parts.append(f"{slug}: {', '.join(sorted(paths))}")
        conflicts.append(f"RFC-{number} is reused by multiple slugs: {'; '.join(parts)}")
    return conflicts


def _pr_new_rfc_paths(pr: dict[str, Any]) -> list[str]:
    files = pr.get("files", [])
    if not isinstance(files, list):
        return []

    paths: list[str] = []
    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        path = file_info.get("path")
        change_type = file_info.get("changeType")
        if isinstance(path, str) and change_type in NEW_RFC_CHANGE_TYPES:
            paths.append(path)
    return paths


def _get_current_pr_new_rfc_numbers(current_pr: int) -> dict[str, list[str]]:
    pr = _run_gh(["pr", "view", str(current_pr), "--json", "files"])
    numbers: dict[str, list[str]] = {}
    for path in _pr_new_rfc_paths(pr):
        identity = _extract_rfc_identity(path)
        if identity:
            number, _slug = identity
            numbers.setdefault(number, []).append(path)
    return numbers


def _find_open_pr_conflicts(current_pr: int) -> list[str]:
    current_numbers = _get_current_pr_new_rfc_numbers(current_pr)
    if not current_numbers:
        print("No new RFC files in this PR; skipping open PR RFC conflict scan.")
        return []

    open_prs = _run_gh(
        ["pr", "list", "--state", "open", "--json", "number,files", "--limit", "100"]
    )
    conflicts: list[str] = []
    for pr in open_prs:
        if not isinstance(pr, dict):
            continue
        pr_number = pr.get("number")
        if pr_number == current_pr:
            continue
        for path in _pr_new_rfc_paths(pr):
            identity = _extract_rfc_identity(path)
            if not identity:
                continue
            number, _slug = identity
            if number in current_numbers:
                current_paths = ", ".join(sorted(current_numbers[number]))
                conflicts.append(
                    f"RFC-{number} in current PR files ({current_paths}) "
                    f"is already used by open PR #{pr_number}: {path}"
                )
    return conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root. Defaults to the current working directory.",
    )
    parser.add_argument(
        "--open-prs",
        action="store_true",
        help="Also compare current PR RFC numbers with other open PR file lists via gh.",
    )
    parser.add_argument(
        "--current-pr",
        type=int,
        help="Current pull request number. Required when --open-prs is used.",
    )
    parser.add_argument(
        "--require-open-pr-scan",
        action="store_true",
        help="Fail if the open PR scan cannot be completed.",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    conflicts = _find_local_conflicts(repo_root)

    if args.open_prs:
        if args.current_pr is None:
            print("--current-pr is required with --open-prs", file=sys.stderr)
            return 2
        try:
            conflicts.extend(_find_open_pr_conflicts(args.current_pr))
        except (
            FileNotFoundError,
            json.JSONDecodeError,
            RuntimeError,
            subprocess.TimeoutExpired,
        ) as exc:
            message = f"Open PR RFC conflict scan failed: {exc}"
            if args.require_open_pr_scan:
                print(f"::error::{message}")
                return 1
            print(f"::warning::{message}")

    if conflicts:
        for conflict in conflicts:
            print(f"::error::{conflict}")
        return 1

    print("✓ RFC number conflict check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
