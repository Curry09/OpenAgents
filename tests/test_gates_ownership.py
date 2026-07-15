"""runtime.gates.assert_writes_owned 单元测试 —— 越权写硬闸（Spec-0071/T3）。

覆盖：全部改动在声明 files 内 → 放行；改动生成物（spec md / OVERVIEW / ARCHITECTURE）→ 放行；
改动无主文件 → raise GateError 且消息列出越权文件；空 changeset → 放行；自定义 specs_root 透传。
纯逻辑、零 IO。
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
    # specs_root 变了，旧默认路径的 OVERVIEW.md 不再算生成物 → 判越权。
    with pytest.raises(gates.GateError):
        gates.assert_writes_owned(
            group=_group(),
            changed_paths=["docs/specs/OVERVIEW.md"],
            specs_root=Path("other/specs"),
        )
