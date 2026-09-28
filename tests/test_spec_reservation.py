"""A shared Git remote must issue distinct spec numbers to concurrent worktrees."""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from openagents.spec.cli import main
from openagents.spec.mutate import create_group


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=path, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    bare = tmp_path / "origin.git"
    bare.mkdir()
    _git(bare, "init", "--bare", "--initial-branch=main")
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", str(bare), str(seed))
    _git(seed, "config", "user.name", "Test")
    _git(seed, "config", "user.email", "test@example.invalid")
    (seed / "README.md").write_text("seed\n")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "push", "origin", "main")
    first = tmp_path / "first"
    second = tmp_path / "second"
    _git(tmp_path, "clone", str(bare), str(first))
    _git(tmp_path, "clone", str(bare), str(second))
    return bare, first, second


def test_concurrent_worktrees_reserve_distinct_numbers(tmp_path: Path) -> None:
    bare, first, second = _repository(tmp_path)

    def create(repo: Path, issue: int) -> Path:
        return create_group(
            specs_root=repo / "docs/specs",
            slug=f"issue-{issue}",
            title="Test",
            issue=issue,
            summary="Summary",
            number=None,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(create, first, 10)
        b = pool.submit(create, second, 11)
        paths = {a.result(), b.result()}
    assert {path.name[:4] for path in paths} == {"0001", "0002"}
    refs = _git(bare, "for-each-ref", "--format=%(refname)", "refs/heads/spec-reservations")
    assert refs.splitlines() == [
        "refs/heads/spec-reservations/0001",
        "refs/heads/spec-reservations/0002",
    ]


def test_explicit_number_cannot_bypass_remote_reservation(tmp_path: Path) -> None:
    _, first, second = _repository(tmp_path)
    create_group(
        specs_root=first / "docs/specs",
        slug="first",
        title="First",
        issue=10,
        summary="A",
        number="0001",
    )
    with pytest.raises(FileExistsError, match="已被"):
        create_group(
            specs_root=second / "docs/specs",
            slug="second",
            title="Second",
            issue=11,
            summary="B",
            number="0001",
        )
    assert not (second / "docs/specs").exists()


def test_shared_remote_failure_does_not_create_spec(tmp_path: Path) -> None:
    _, first, _ = _repository(tmp_path)
    _git(first, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    with pytest.raises(RuntimeError, match="编号预留失败"):
        create_group(
            specs_root=first / "docs/specs",
            slug="first",
            title="First",
            issue=10,
            summary="A",
            number=None,
        )
    assert not (first / "docs/specs").exists()


def test_reserve_number_command_supports_existing_group_renumber(tmp_path: Path, capsys) -> None:
    bare, first, _ = _repository(tmp_path)
    create_group(
        specs_root=first / "docs/specs",
        slug="first",
        title="First",
        issue=10,
        summary="A",
        number=None,
    )
    assert (
        main(
            argv=[
                "reserve-number",
                "--issue",
                "10",
                "--slug",
                "first",
                "--specs-root",
                str(first / "docs/specs"),
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == "0002"
    refs = _git(bare, "for-each-ref", "--format=%(refname)", "refs/heads/spec-reservations")
    assert refs.splitlines()[-1] == "refs/heads/spec-reservations/0002"
