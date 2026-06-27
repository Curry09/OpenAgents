"""Spec-0028/T1：overview_digest_for_group 单元测试。

只读 spec 组 markdown（model.dump_group 落盘的真实文件），不触达 git / GitHub。
覆盖：三段齐全渲染、超行截断附续接提示、缺段跳过、三段全空 → None、
非文件 / 不可读 → None（零回归）。
"""

from pathlib import Path

import pytest

from openagents.spec import model as spec_model
from openagents.spec.model import Group, Metadata, Overview, Task
from openagents.spec.signpost import (
    _DIGEST_MAX_LINES,
    _DIGEST_TRUNCATED_HINT,
    overview_digest_for_group,
)


def _dump(*, root, overview, number="0028", slug="pr-digest-and-conflict-agent"):
    group = Group(
        number=number,
        metadata=Metadata(title="示例", issue=79, slug=slug, summary="TL;DR"),
        tasks=[Task(id="T1", title="t", status="pending", priority="P1")],
        overview=overview,
    )
    path = spec_model.group_path(specs_root=Path(root), number=number, slug=slug)
    spec_model.dump_group(group=group, path=path)
    return path


def test_digest_renders_three_sections(tmp_path):
    path = _dump(
        root=tmp_path,
        overview=Overview(
            summary="一句话总结。",
            motivation="为什么要做。",
            reference_level="技术方案怎么做。",
            # 下面这些段不进 digest。
            drawbacks="缺点（不应出现在 digest）。",
        ),
    )
    digest = overview_digest_for_group(group_path=path)
    assert digest is not None
    assert digest.startswith(f"## spec 总览（摘自 docs/specs/{path.name}）")
    assert "### Summary\n一句话总结。" in digest
    assert "### Motivation\n为什么要做。" in digest
    assert "### Reference-level explanation\n技术方案怎么做。" in digest
    # 只取三段，不含 Drawbacks。
    assert "Drawbacks" not in digest
    assert "缺点" not in digest


def test_digest_truncates_long_section(tmp_path):
    long_body = "\n".join(f"行 {i}" for i in range(_DIGEST_MAX_LINES + 5))
    path = _dump(root=tmp_path, overview=Overview(summary=long_body))
    digest = overview_digest_for_group(group_path=path)
    assert digest is not None
    # 保留前 N 行 + 续接提示，超出的行被截掉。
    assert "行 0" in digest
    assert f"行 {_DIGEST_MAX_LINES - 1}" in digest
    assert f"行 {_DIGEST_MAX_LINES}" not in digest
    assert _DIGEST_TRUNCATED_HINT in digest


def test_digest_skips_empty_sections(tmp_path):
    # 只有 summary，motivation/reference-level 空 → 只渲染 Summary 块。
    path = _dump(root=tmp_path, overview=Overview(summary="只有摘要。"))
    digest = overview_digest_for_group(group_path=path)
    assert digest is not None
    assert "### Summary" in digest
    assert "### Motivation" not in digest
    assert "### Reference-level explanation" not in digest


def test_digest_none_when_all_three_empty(tmp_path):
    # 三段全空（如总览未填）→ 不渲染空块，返回 None（回退到无 digest，零回归）。
    path = _dump(root=tmp_path, overview=Overview(guide_level="只有 guide-level。"))
    assert overview_digest_for_group(group_path=path) is None


def test_digest_none_when_not_a_file(tmp_path):
    assert overview_digest_for_group(group_path=tmp_path / "missing.md") is None


def test_digest_none_when_unreadable(tmp_path, monkeypatch):
    path = _dump(root=tmp_path, overview=Overview(summary="x"))

    def _boom(*, path):
        raise ValueError("坏掉的 spec")

    monkeypatch.setattr(spec_model, "load_group", _boom)
    assert overview_digest_for_group(group_path=path) is None


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
