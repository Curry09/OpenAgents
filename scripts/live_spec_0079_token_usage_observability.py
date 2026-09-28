"""Spec-0079/T5: real ClaudeCodeBackend usage → AgentResult → ledger → report canary."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from string import Template

from openagents.backends.claude_code import ClaudeCodeBackend
from openagents.cli import _render_report
from openagents.runtime import engine, token_usage


class _CanaryAgent:
    PROMPT = Template('Return exactly this JSON object: {"verdict":"PASS","reason":"token-canary"}')
    OUTPUT_SCHEMA = {"verdict": str, "reason": str}


class _CapturingBackend:
    name = "claude-code"

    def __init__(self) -> None:
        self.inner = ClaudeCodeBackend()
        self.result = None

    def run(self, *, work_dir: Path, task: str, context: str):
        self.result = self.inner.run(work_dir=work_dir, task=task, context=context)
        return self.result


def _git_init(*, path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="openagents-spec0079-") as raw:
        repo = Path(raw)
        _git_init(path=repo)
        backend = _CapturingBackend()
        result = engine.run_agent(_CanaryAgent, backend=backend, work_dir=repo)
        if result != {"verdict": "PASS", "reason": "token-canary"}:
            raise RuntimeError(f"unexpected canary protocol result: {result!r}")
        if backend.result is None or backend.result.usage is None:
            raise RuntimeError("Claude Code result event did not provide parseable usage")

        usage = backend.result.usage
        ledger = repo / ".openagents" / token_usage.TOKEN_USAGE_FILENAME
        events = token_usage.load_events(path=ledger)
        if len(events) != 1 or events[0].get("usage_source") != "reported":
            raise RuntimeError(f"expected one reported ledger event, got {events!r}")
        row = events[0]
        fields = (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "reasoning_tokens",
            "total_tokens",
            "total_source",
            "model",
        )
        if any(row.get(field) != getattr(usage, field) for field in fields):
            raise RuntimeError("AgentResult usage and ledger usage differ")
        total = row.get("total_tokens")
        if not isinstance(total, int) or total <= 0:
            raise RuntimeError(f"expected positive token total, got {total!r}")

        report = _render_report(
            events=[],
            interval=60,
            path=repo / ".openagents" / "timing.jsonl",
            token_events=events,
            token_path=ledger,
        )
        if "_CanaryAgent" not in report or str(total) not in report:
            raise RuntimeError("oa report did not contain the canary role and token total")

        evidence = {
            "status": "passed",
            "backend": row.get("backend"),
            "model": row.get("model"),
            "usage_source": row.get("usage_source"),
            "input_tokens": row.get("input_tokens"),
            "output_tokens": row.get("output_tokens"),
            "cache_read_input_tokens": row.get("cache_read_input_tokens"),
            "cache_creation_input_tokens": row.get("cache_creation_input_tokens"),
            "reasoning_tokens": row.get("reasoning_tokens"),
            "total_tokens": total,
            "total_source": row.get("total_source"),
            "ledger_events": len(events),
            "agent_result_matched": True,
            "report_matched": True,
        }
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
