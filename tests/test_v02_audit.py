import json

from openagents.v02.audit import write_result
from openagents.v02.model import BatchResult, NodeResult, Plan


def test_audit_records_are_append_only_and_machine_readable(tmp_path):
    result = BatchResult(
        plan=Plan(blocked_by={2: (1,), 1: ()}, batches=((1,), (2,))),
        nodes={1: NodeResult(1, "PASS", head_sha="abc", pr_number=10)},
        specs={1: {"spec_digest": "digest-1", "spec_path": "/w/1/spec.md"}},
    )
    first = write_result(work_dir=tmp_path, result=result)
    second = write_result(work_dir=tmp_path, result=result)
    assert first != second
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["result"]["nodes"]["1"]["status"] == "PASS"
    assert payload["result"]["plan"]["batches"] == [[1], [2]]
    assert payload["result"]["specs"]["1"]["spec_digest"] == "digest-1"
