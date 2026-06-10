#!/usr/bin/env python3
"""检查 spec 组编号是否在本地或其它 open PR 之间冲突。

Spec-0014/T5: 编号校验脚本（check-rfc 的 spec 版）

仓库约定：spec 源数据放在 docs/specs/NNNN-slug/ 目录下（metadata.yaml + tasks/ + history/）。
同一个编号 NNNN 不能被不同的 slug 复用（本地）；新建的组编号不能与其它 open PR 撞号。
匹配 docs/specs/(NNNN)-slug/ 目录形态，本地 + open PR 并集取下一号（决策 D11）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# Spec-0014/T5：匹配 docs/specs/NNNN-slug/ 下任意文件，抽组编号与 slug。
SPEC_PATH_RE = re.compile(r"^docs/specs/(?P<number>\d{4})-(?P<slug>[^/]+)/")
NEW_SPEC_CHANGE_TYPES = {"ADDED", "RENAMED"}


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


def _extract_spec_identity(path: str) -> tuple[str, str] | None:
    match = SPEC_PATH_RE.match(path)
    if not match:
        return None
    return match.group("number"), match.group("slug")


def _iter_repo_spec_groups(repo_root: Path) -> list[tuple[str, str]]:
    """本地 docs/specs/ 下的 (number, slug) 组目录列表。"""
    specs_dir = repo_root / "docs" / "specs"
    if not specs_dir.is_dir():
        return []
    groups: list[tuple[str, str]] = []
    for child in sorted(specs_dir.iterdir()):
        # 仅 NNNN-slug 目录形态视为 spec 组。
        if child.is_dir():
            identity = _extract_spec_identity(f"docs/specs/{child.name}/")
            if identity:
                groups.append(identity)
    return groups


def _find_local_conflicts(repo_root: Path) -> list[str]:
    by_number: dict[str, set[str]] = {}
    for number, slug in _iter_repo_spec_groups(repo_root):
        by_number.setdefault(number, set()).add(slug)

    conflicts: list[str] = []
    for number, slugs in sorted(by_number.items()):
        if len(slugs) > 1:
            joined = ", ".join(sorted(slugs))
            conflicts.append(f"spec-{number} 被多个 slug 复用：{joined}")
    return conflicts


def _pr_new_spec_numbers(pr: dict[str, Any]) -> dict[str, list[str]]:
    """PR 中新增（ADDED/RENAMED）的 spec 文件 → number -> [paths]。"""
    files = pr.get("files", [])
    if not isinstance(files, list):
        return {}

    numbers: dict[str, list[str]] = {}
    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        path = file_info.get("path")
        change_type = file_info.get("changeType")
        if not (isinstance(path, str) and change_type in NEW_SPEC_CHANGE_TYPES):
            continue
        identity = _extract_spec_identity(path)
        if identity:
            number, _slug = identity
            numbers.setdefault(number, []).append(path)
    return numbers


def _find_open_pr_conflicts(current_pr: int) -> list[str]:
    current = _pr_new_spec_numbers(_run_gh(["pr", "view", str(current_pr), "--json", "files"]))
    if not current:
        print("本 PR 无新增 spec 文件；跳过 open PR 冲突扫描。")
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
        for number in _pr_new_spec_numbers(pr):
            if number in current:
                current_paths = ", ".join(sorted(current[number]))
                conflicts.append(
                    f"spec-{number}（本 PR：{current_paths}）已被 open PR #{pr_number} 占用"
                )
    return conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="仓库根目录，默认当前工作目录。",
    )
    parser.add_argument(
        "--open-prs",
        action="store_true",
        help="同时用 gh 比对其它 open PR 的 spec 编号。",
    )
    parser.add_argument(
        "--current-pr",
        type=int,
        help="当前 PR 编号；与 --open-prs 一起使用。",
    )
    parser.add_argument(
        "--require-open-pr-scan",
        action="store_true",
        help="open PR 扫描失败时直接判失败。",
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
            message = f"Open PR spec 冲突扫描失败：{exc}"
            if args.require_open_pr_scan:
                print(f"::error::{message}")
                return 1
            print(f"::warning::{message}")

    if conflicts:
        for conflict in conflicts:
            print(f"::error::{conflict}")
        return 1

    print("✓ spec 编号冲突检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
