"""# Spec-0066/T3: `oa report` CLI 子命令针对性单测（不触网络/仓库）。

覆盖：子命令注册进 argparse（--help 可见）；对造好的 timing.jsonl 输出单 subject 各阶段 duration + 跨
subject p50/p90，且出现「精度下限 = interval」字样与实际 interval 值；timing.jsonl 缺失/空时友好提示、退出
码 0（不抛栈）。
"""

from __future__ import annotations

import json
from pathlib import Path

from openagents.cli import _render_report, build_parser, main
from openagents.runtime import timing, tool_usage
from openagents.utils.config import ProjectContext


def _patch_report_ctx(monkeypatch, *, repo_root: Path) -> None:
    ctx = ProjectContext(repo_root=repo_root, remote=None)
    monkeypatch.setattr("openagents.cli.resolve_project", lambda: ctx)


def _write_events(repo_root: Path, events: list[dict]) -> None:
    path = repo_root / ".openagents" / timing.TIMING_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(ev) for ev in events) + "\n", encoding="utf-8")


def _seq(subject: str, issue, pr, phases_at):
    return [
        {"subject": subject, "issue": issue, "pr": pr, "phase": phase, "at": at}
        for phase, at in phases_at
    ]


# --------------------------------------------------------------------------------------------------
# 注册。
# --------------------------------------------------------------------------------------------------


def test_report_subcommand_registered():
    subparsers = next(a for a in build_parser()._actions if getattr(a, "choices", None))
    assert "report" in subparsers.choices


# --------------------------------------------------------------------------------------------------
# 有数据：单 subject 时间线 + 跨 subject p50/p90 + interval 精度下限标注。
# --------------------------------------------------------------------------------------------------


def test_report_prints_timeline_and_percentiles_and_interval(tmp_path, monkeypatch, capsys):
    _patch_report_ctx(monkeypatch, repo_root=tmp_path)
    monkeypatch.setattr("openagents.cli._report_interval", lambda *, ctx, args: 60)
    events = _seq(
        "issue:145",
        145,
        154,
        [
            ("solving", "2026-07-09T12:00:00Z"),
            ("awaiting-ci", "2026-07-09T12:03:00Z"),  # solving 3min
            ("review-or-fix", "2026-07-09T12:10:00Z"),  # awaiting-ci 7min
            ("merged", "2026-07-09T12:12:00Z"),  # review-or-fix 2min
        ],
    )
    _write_events(tmp_path, events)
    assert main(["report"]) == 0
    out = capsys.readouterr().out
    # 单 subject 时间线出现各阶段 duration。
    assert "issue:145" in out
    assert "solving" in out and "awaiting-ci" in out and "review-or-fix" in out
    assert "3m0s" in out  # solving 停留 3 分钟
    assert "7m0s" in out  # awaiting-ci 停留 7 分钟
    # 跨 subject 分布段。
    assert "p50" in out and "p90" in out
    # **精度下限 = interval** 标注 + 实际值。
    assert "精度下限" in out and "60s" in out


def test_report_distinguishes_ci_wait_from_review_wait(tmp_path, monkeypatch, capsys):
    """报告能对已合并 issue 分别列出 CI-wait 与 review-wait 段（不再糊成一段）。"""
    _patch_report_ctx(monkeypatch, repo_root=tmp_path)
    monkeypatch.setattr("openagents.cli._report_interval", lambda *, ctx, args: 60)
    events = _seq(
        "issue:9",
        9,
        20,
        [
            ("awaiting-ci", "2026-07-09T12:00:00Z"),  # CI-wait 5min
            ("review-or-fix", "2026-07-09T12:05:00Z"),  # review-wait 30min
            ("merged", "2026-07-09T12:35:00Z"),
        ],
    )
    _write_events(tmp_path, events)
    assert main(["report"]) == 0
    out = capsys.readouterr().out
    assert "awaiting-ci" in out
    assert "review-or-fix" in out
    assert "30m0s" in out  # review 长尾清晰可见


def test_report_includes_tool_lookup_budget_metrics(tmp_path, monkeypatch, capsys):
    _patch_report_ctx(monkeypatch, repo_root=tmp_path)
    monkeypatch.setattr("openagents.cli._report_interval", lambda *, ctx, args: 60)
    path = tmp_path / ".openagents" / tool_usage.TOOL_USAGE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"role":"implementer","tool_count":9,"lookup_before_first_edit":8,'
        '"lookup_budget_exceeded":true}\n',
        encoding="utf-8",
    )

    assert main(["report"]) == 0
    out = capsys.readouterr().out
    assert "工具与取证预算" in out
    assert "implementer" in out
    assert "8.0" in out
    assert "缺原因" in out


def test_report_includes_token_totals_and_coverage(tmp_path):
    text = _render_report(
        events=[],
        interval=60,
        path=tmp_path / "timing.jsonl",
        token_path=tmp_path / "token-usage.jsonl",
        token_events=[
            {
                "role": "implementer",
                "status": "success",
                "usage_source": "reported",
                "input_tokens": 10,
                "output_tokens": 2,
                "cache_read_input_tokens": 20,
                "cache_creation_input_tokens": 3,
                "reasoning_tokens": 1,
                "total_tokens": 36,
                "total_source": "derived-components",
            },
            {
                "role": "implementer",
                "status": "backend_error",
                "usage_source": "unavailable",
            },
        ],
    )
    assert "token 用量与采集覆盖率" in text
    assert "implementer" in text
    assert "missing" in text
    assert "      2         1        1" in text
    assert "missing 不计入 token 合计" in text


# --------------------------------------------------------------------------------------------------
# 空 / 缺文件：友好提示 + 退出码 0。
# --------------------------------------------------------------------------------------------------


def test_report_missing_file_is_friendly_and_returns_zero(tmp_path, monkeypatch, capsys):
    _patch_report_ctx(monkeypatch, repo_root=tmp_path)
    monkeypatch.setattr("openagents.cli._report_interval", lambda *, ctx, args: 60)
    assert main(["report"]) == 0  # 不抛栈
    out = capsys.readouterr().out
    assert "timing.jsonl" in out  # 友好提示指明文件


def test_report_empty_file_is_friendly_and_returns_zero(tmp_path, monkeypatch, capsys):
    _patch_report_ctx(monkeypatch, repo_root=tmp_path)
    monkeypatch.setattr("openagents.cli._report_interval", lambda *, ctx, args: 60)
    path = tmp_path / ".openagents" / timing.TIMING_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    assert main(["report"]) == 0
    assert "timing.jsonl" in capsys.readouterr().out


def test_report_interval_falls_back_to_60_when_no_config(tmp_path, monkeypatch, capsys):
    """无 openagents.yml 时 interval 回落 60（不让缺配置掀翻报告）。"""
    _patch_report_ctx(monkeypatch, repo_root=tmp_path)
    _write_events(
        tmp_path,
        _seq(
            "issue:1",
            1,
            None,
            [("solving", "2026-07-09T12:00:00Z"), ("merged", "2026-07-09T12:01:00Z")],
        ),
    )
    assert main(["report"]) == 0
    assert "60s" in capsys.readouterr().out
