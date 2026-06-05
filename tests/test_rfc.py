"""RFC-0008 T1: rfc 模块（RFC 文档解析 + 指路牌渲染）的单元测试。

覆盖 extract_e2e / render_signpost / signpost_for 全分支：齐全、缺脚本、缺手动验证、
二者皆缺、畸形 Markdown、文件名编号解析、文件不可读。
"""

from openagents import rfc
from openagents.rfc import E2EHints, extract_e2e, render_signpost, signpost_for

# 一份「测试方案」齐全的最小 RFC（含集成测试脚本 + 手动验证首步预期）。
_FULL_RFC = """# RFC-0008: 示例

## 测试方案

### 单元测试

- 一些单测说明，里面也提到 scripts/not-this-one.sh 不应被选中。

### 集成测试

- `scripts/e2e-rfc-0008-pr-e2e-signpost.sh`：默认离线跑 ruff + pytest。

### 手动验证

1. `openagents rfc <issue>` → 检查生成的 draft PR 正文含「## 端到端验证」段。
2. 第二步不应被选中。

## 未解决的问题

无。
"""


def test_extract_e2e_full_rfc_picks_script_and_expected():
    hints = extract_e2e(rfc_text=_FULL_RFC)
    assert hints.script_path == "scripts/e2e-rfc-0008-pr-e2e-signpost.sh"
    # 取「→」之后的预期，而非整行行为部分。
    assert hints.expected == "检查生成的 draft PR 正文含「## 端到端验证」段。"


def test_extract_e2e_ignores_script_outside_integration_section():
    # 单元测试段里的脚本不应被误选，只认集成测试段内的。
    hints = extract_e2e(rfc_text=_FULL_RFC)
    assert hints.script_path != "scripts/not-this-one.sh"


def test_extract_e2e_missing_integration_script():
    text = """## 测试方案

### 集成测试

- 还没有脚本，只有文字说明。

### 手动验证

1. 跑命令 → 预期成功。
"""
    hints = extract_e2e(rfc_text=text)
    assert hints.script_path is None
    assert hints.expected == "预期成功。"


def test_extract_e2e_missing_manual_section():
    text = """### 集成测试

- `scripts/e2e-rfc-0009-x.sh`：跑测试。
"""
    hints = extract_e2e(rfc_text=text)
    assert hints.script_path == "scripts/e2e-rfc-0009-x.sh"
    assert hints.expected is None


def test_extract_e2e_both_missing():
    hints = extract_e2e(rfc_text="# 一个没有测试方案的 RFC\n\n正文。")
    assert hints.script_path is None
    assert hints.expected is None


def test_extract_e2e_malformed_markdown_does_not_raise():
    # 畸形 / 半截 Markdown 不应抛错。
    hints = extract_e2e(rfc_text="### 集成测试\n### 手动验证\n###")
    assert hints.script_path is None
    assert hints.expected is None


def test_extract_e2e_expected_without_arrow_takes_whole_step():
    text = """### 手动验证

1. 直接描述预期效果，没有箭头。
"""
    hints = extract_e2e(rfc_text=text)
    assert hints.expected == "直接描述预期效果，没有箭头。"


def test_render_signpost_full_hints():
    hints = E2EHints(script_path="scripts/e2e-rfc-0008-x.sh", expected="PR 正文含指路牌段")
    out = render_signpost(rfc_number=8, hints=hints)
    assert out.startswith("## 端到端验证")
    assert "- 跑：`bash scripts/e2e-rfc-0008-x.sh`" in out
    assert "- 预期：PR 正文含指路牌段" in out
    assert "- 详细手动步骤见 RFC-0008「手动验证」" in out


def test_render_signpost_degrades_missing_script():
    hints = E2EHints(script_path=None, expected="some expectation")
    out = render_signpost(rfc_number=8, hints=hints)
    assert "- 跑：见 RFC-0008「集成测试」" in out
    assert "- 预期：some expectation" in out


def test_render_signpost_degrades_missing_expected():
    hints = E2EHints(script_path="scripts/x.sh", expected=None)
    out = render_signpost(rfc_number=12, hints=hints)
    assert "- 跑：`bash scripts/x.sh`" in out
    assert "- 预期：见 RFC-0012「手动验证」" in out


def test_render_signpost_both_degraded():
    out = render_signpost(rfc_number=8, hints=E2EHints(script_path=None, expected=None))
    assert "- 跑：见 RFC-0008「集成测试」" in out
    assert "- 预期：见 RFC-0008「手动验证」" in out
    assert "- 详细手动步骤见 RFC-0008「手动验证」" in out


def test_signpost_for_reads_file_and_parses_number(tmp_path):
    rfc_file = tmp_path / "0008-pr-e2e-signpost.md"
    rfc_file.write_text(_FULL_RFC, encoding="utf-8")
    out = signpost_for(rfc_path=rfc_file)
    assert out is not None
    assert "## 端到端验证" in out
    assert "`bash scripts/e2e-rfc-0008-pr-e2e-signpost.sh`" in out
    assert "RFC-0008" in out


def test_signpost_for_unparseable_filename_returns_none(tmp_path):
    rfc_file = tmp_path / "README.md"
    rfc_file.write_text(_FULL_RFC, encoding="utf-8")
    assert signpost_for(rfc_path=rfc_file) is None


def test_signpost_for_unreadable_file_returns_none(tmp_path):
    missing = tmp_path / "0009-missing.md"
    assert signpost_for(rfc_path=missing) is None


def test_module_exposes_public_api():
    assert hasattr(rfc, "extract_e2e")
    assert hasattr(rfc, "render_signpost")
    assert hasattr(rfc, "signpost_for")
    assert hasattr(rfc, "E2EHints")
