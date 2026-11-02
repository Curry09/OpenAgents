"""Spec-0093/T3: actual NexAU + Anthropic HTTP boundary, no external model/credentials.

Run with ``uv run --locked --extra dev --extra nexau pytest``. The server replaces
only the remote endpoint; AgentConfig, Agent, execution loop and SDK remain real.
"""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from openagents.backends.nexau import NexAUBackend


@pytest.mark.parametrize("http_status", [200, 500])
def test_advisory_performs_exactly_one_real_http_attempt(monkeypatch, tmp_path, http_status):
    pytest.importorskip("nexau", reason="install the nexau extra for real client integration")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.delenv("OPENAGENTS_NEXAU_AUDIT_DIR", raising=False)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    requests = []
    expected = {"verdict": "PASS", "reason": "the single request reached the endpoint"}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"path": self.path, "body": body})
            response = (
                {
                    "id": "msg-controlled-advisory",
                    "type": "message",
                    "role": "assistant",
                    "model": "controlled-model",
                    "content": [{"type": "text", "text": json.dumps(expected)}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 12, "output_tokens": 18},
                }
                if http_status == 200
                else {
                    "type": "error",
                    "error": {"type": "api_error", "message": "controlled failure"},
                }
            )
            encoded = json.dumps(response).encode()
            self.send_response(http_status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        backend = NexAUBackend(
            model="controlled-model",
            base_url=f"http://127.0.0.1:{server.server_port}",
            api_key="synthetic-test-only",
        ).for_advisory()
        if http_status == 200:
            result = backend.run(
                work_dir=tmp_path, task="Return the requested JSON.", context="contract-123"
            )
            assert json.loads(result.raw_output) == expected
        else:
            with pytest.raises(RuntimeError, match="controlled failure"):
                backend.run(
                    work_dir=tmp_path, task="Return the requested JSON.", context="contract-123"
                )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert len(requests) == 1
    assert requests[0]["path"] == "/v1/messages"
    payload = requests[0]["body"]
    assert payload["model"] == "controlled-model"
    assert payload["max_tokens"] == 8192
    assert not payload.get("tools")
    assert "contract-123" in json.dumps(payload["messages"])
