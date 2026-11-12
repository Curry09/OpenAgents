"""runtime.gates.assert_writes_owned unit test - Excessive writing of hardlock (Spec-0071/T3).

Overwrite: All changes are released in the statements; change the generator (spec md/ overVIEW/ ARCHETECTURE) is released;
Change the orphan file  → raise GateError and message lists the ultra-powerful files; empty changeset  →  release; custom specs_root overwrite.
Pure logic, zero IO.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openagents.runtime import gates
from openagents.spec.model import Group, Metadata, Task


def _group() -> Group:
    return Group(
        number="0071",
        metadata=Metadata(title="s", issue=71, slug="single-writer-ownership-guard", summary="x"),
        tasks=[
            Task(id="T1", title="t1", status="pending", priority="P1", files=["a.py", "b.py"]),
            Task(id="T2", title="t2", status="pending", priority="P1", files=["c.py"]),
        ],
    )


def test_declared_files_pass() -> None:
    gates.assert_writes_owned(group=_group(), changed_paths=["a.py", "c.py"])


def test_generated_artifacts_pass() -> None:
    gates.assert_writes_owned(
        group=_group(),
        changed_paths=[
            "docs/specs/0071-single-writer-ownership-guard.md",
            "docs/specs/OVERVIEW.md",
            "docs/specs/ARCHITECTURE.md",
        ],
    )


def test_empty_changeset_passes() -> None:
    gates.assert_writes_owned(group=_group(), changed_paths=[])


def test_unowned_write_raises_and_lists_offenders() -> None:
    with pytest.raises(gates.GateError) as excinfo:
        gates.assert_writes_owned(group=_group(), changed_paths=["a.py", "evil.py"])
    msg = str(excinfo.value)
    assert "evil.py" in msg
    assert "0071" in msg


def test_custom_specs_root_is_passed_through() -> None:
    # specs_root has changed and the old default path OVERVIEW.md no longer counts as the generator overstepping power.
    with pytest.raises(gates.GateError):
        gates.assert_writes_owned(
            group=_group(),
            changed_paths=["docs/specs/OVERVIEW.md"],
            specs_root=Path("other/specs"),
        )
