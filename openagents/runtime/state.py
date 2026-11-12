# Spec-0060/T5
"""Persist delivery run state and comment cursors in a project-local namespace."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from openagents.runtime import research

# Spec-0060/T5: New Barn Status File Name - Independent Namespace with old state.json to avoid conflict with file level.
RUNTIME_STATE_FILENAME = "runtime-state.json"

# Spec-0063/T1: Authoritative Status Glossary - Moved from Old state.py as the sole source of statuslist for release and subsequent consumer
# (The volume of the text corresponds to the old state.py; the old STATUS_* copy was removed from service with state.py.)
STATUS_SOLVING = "solving"
STATUS_RFC_REVIEW = "rfc-review"
STATUS_PR_OPEN = "pr-open"
STATUS_ITERATING = "iterating"
STATUS_DONE = "done"
STATUS_CLOSED = "closed"
STATUS_FAILED = "failed"


class RuntimeState:
    """# Spec-0060/T5: New stack status reader (formulated by status file path, independent namespace).

    # Spec-0065/T2: ** Also write to serial + the atom for the drop drive.** K workser threads from Vigil, which share the same Runtestate
    # Example and write (`set_run`/ `set_cursor`). Write ”Read the whole JSON # Change a key # # All back:
    # - Unlocked ** unupdated**: two workingrs read the same old data, changed each key, then erased the former’s records
    # (Down with a `set_run(status=done)` or a comment cursor = repeat return / run backwards)
    # - Non-atom ** whole file is cut**: `write_text` cut and write, and the other thread is right at this point `_load` will read half of JSON,
    #`JSONDecodeError` is mistaken for ”empty” # and then it covers ** the whole status file ** with only one of its own.
    # So: `_LOCK` swath the ”Reread-reform-write” (class, with example/all writings of the document), `_save` go tmp + `os.replace`
    # (Rename in directory is atom, reader sees old or new files, never sees half of them)
    # This solves only the simultaneous hairs within** process** (the K watcher is a thread); cross-process and send the same state file outside this spec
    # (fleet is a case-by-story status file)
    """

    _LOCK = threading.RLock()

    def __init__(self, *, path: Path) -> None:
        self._path = Path(path)

    def get_run(self, *, issue_number: int) -> dict | None:
        """Take a run-off record of a particular issue (as it is: status/branch/pr_number [/ closed_at]]; None."""
        return self._load().get("runs", {}).get(str(issue_number))

    def set_run(
        self,
        *,
        issue_number: int,
        status: str,
        branch: str,
        pr_number: int | None,
        closed_at: str = "",
        design_digest: str = "",
        design_raw_digest: str = "",
        evidence_pack: list | None = None,
    ) -> None:
        """Write/ overwrite the run-off record of a particular issue (status/branch/pr_number).

        # Spec-0062/T3: `closed_at` Optional (for the Easter Window), Default ”” and ** only when empty** — Maintain 3 keys
        # The pattern and sequence remain unchanged (the drop-off of the closed_at when the caller is not passed is still 3 keys, the old assertion/old file is zero back).
        """
        with RuntimeState._LOCK:  # Spec-0065/T2: Read-reform-write full-processed lines (K-worker and copying will drop updates)
            data = self._load()
            previous = data.get("runs", {}).get(str(issue_number), {})
            record: dict = {"status": status, "branch": branch, "pr_number": pr_number}
            if closed_at:
                record["closed_at"] = closed_at
            if design_digest:
                record["design_digest"] = design_digest
            elif previous.get("design_digest"):
                record["design_digest"] = previous["design_digest"]
            # Spec-0088/T1: keep raw audit identity through later delivery status updates.
            if design_raw_digest:
                record["design_raw_digest"] = design_raw_digest
            elif design_digest in {"", previous.get("design_digest")} and previous.get(
                "design_raw_digest"
            ):
                record["design_raw_digest"] = previous["design_raw_digest"]
            if evidence_pack is not None:
                record["evidence_pack"] = research.normalize(evidence_pack)
            elif previous.get("evidence_pack"):
                record["evidence_pack"] = previous["evidence_pack"]
            data.setdefault("runs", {})[str(issue_number)] = record
            self._save(data=data)

    def execution_requirement(self, *, issue_number: int, required: bool) -> bool:
        """Spec-0093/T2: latch the trusted dispatch requirement across queue/recovery.

        Ordinary projects leave no new record. Once negotiated, a missing issue
        marker or later default configuration cannot silently erase the condition.
        """
        from openagents.observations.execution_contracts import ExecutionContractUnavailable

        if type(required) is not bool or type(issue_number) is not int or issue_number <= 0:
            raise ExecutionContractUnavailable("invalid trusted execution dispatch")
        with RuntimeState._LOCK:
            try:
                data = json.loads(self._path.read_text()) if self._path.exists() else {}
                policies = data.get("execution_requirements", {})
                previous = policies.get(str(issue_number), False)
                if not isinstance(policies, dict) or type(previous) is not bool:
                    raise ValueError("invalid policy")
            except (ValueError, OSError, AttributeError, TypeError):
                raise ExecutionContractUnavailable("execution dispatch state unavailable") from None
            effective = required or previous
            if effective and not previous:
                data.setdefault("execution_requirements", {})[str(issue_number)] = True
                self._save(data=data)
            return effective

    def find_run(self, *, pr_number: int) -> dict | None:
        """# Spec-0062/T3: Press PR Check. run（rfc_lifecycle refine/implement/iterate reuse;no rule None。

        Return value by `_with_issue` hydrate——- Yeah. `issue_number`(from runs Keys) with `closed_at`(in default) ””），
        You can read the issue to the upper level. You can return this reading only if you have the same type of drop-down.
        """
        for issue_key, record in self._load().get("runs", {}).items():
            if record.get("pr_number") == pr_number:
                return self._with_issue(issue_key=issue_key, record=record)
        return None

    def list_runs(self) -> list[dict]:
        """# Spec-0062/T3: All run-records of rows (all hydrate with issue_number/closed_at).

        The vigil watch thus projectes Run in flight as merge_pr Run (with issue to write back to merge/ close issue).
        """
        return [
            self._with_issue(issue_key=issue_key, record=record)
            for issue_key, record in self._load().get("runs", {}).items()
        ]

    def _with_issue(self, *, issue_key: str, record: dict) -> dict:
        """Put the wheel down. run Records hydrate Belt issue_number(from key) with closed_at(in default) ””）. The value of the readback value."""
        hydrated = dict(record)
        hydrated["issue_number"] = int(issue_key)
        hydrated.setdefault("closed_at", "")
        return hydrated

    def get_cursor(self, *, pr_number: int) -> str | None:
        """Take a PR comment cursor (finally processed comment id); None."""
        return self._load().get("cursors", {}).get(str(pr_number))

    def set_cursor(self, *, pr_number: int, comment_id: str) -> None:
        """Write some PR decision cursor."""
        with RuntimeState._LOCK:  # Spec-0065/T2: Same as set_run - Drop a cursor = Repeat response to the same human comment
            data = self._load()
            data.setdefault("cursors", {})[str(pr_number)] = comment_id
            self._save(data=data)

    def get_issue_cursor(self, *, number: int) -> str | None:
        """# Spec-0016/T2: Take a comment from a comment post (finally processed issue id); None.

        with `get_cursor`（PR The first edition of the book is the one I have written about.`cursors` Press pr_number）Horizontal but low**Independent Namespace Key** `issue_cursors`
        (Push issue number) -issue N and PR N are two different objects, and the same key will crash (respond to the issue N cursor overlay)
        PR N repeats/ slips back to the same comment. The default returns None (= from the beginning, any human comment is new).
        """
        return self._load().get("issue_cursors", {}).get(str(number))

    def set_issue_cursor(self, *, number: int, comment_id: str) -> None:
        """# Spec-0016/T2: Write a comment cursor (down `issue_cursors`) for a particular issue."""
        # Spec-0016/T2: Serial with set_cursor - Read-reform - Write the whole process (discard a cursor = repeat comments on the same human comment)
        with RuntimeState._LOCK:
            data = self._load()
            data.setdefault("issue_cursors", {})[str(number)] = comment_id
            self._save(data=data)

    def get_review_feedback(self, *, issue_number: int, head_sha: str) -> str | None:
        """Return reviewer feedback only when it belongs to the exact current head."""
        record = self._load().get("review_feedback", {}).get(str(issue_number), {})
        if record.get("head_sha") != head_sha:
            return None
        reason = record.get("reason")
        return reason if isinstance(reason, str) and reason.strip() else None

    def set_review_feedback(self, *, issue_number: int, head_sha: str, reason: str) -> None:
        """Persist the detailed REWORK reason, bound to the commit that was reviewed."""
        with RuntimeState._LOCK:
            data = self._load()
            data.setdefault("review_feedback", {})[str(issue_number)] = {
                "head_sha": head_sha,
                "reason": reason,
            }
            self._save(data=data)

    def get_agent_id(self) -> str | None:
        """# Spec-0063/T1: Read this instance of the dropped disk agent_id (input RFC-0011 syntax); no return of Noone set.

        agent_id is the runtime-state.json top-level optional key (a level with runs/cursors).
        identity.resolve_agent_id returns the existing value when env is not specified, ensuring cross-process/relaunch stabilization.
        _load Missing/ Damage Return () data.get None, Non-empty st Verify Return Noone.
        """
        data = self._load()
        agent_id = data.get("agent_id")
        return agent_id if isinstance(agent_id, str) and agent_id else None

    def set_agent_id(self, *, agent_id: str) -> None:
        """# Spec-0063/T1: Crashed-book instance agent_id (Consume RFC-0011 syntax)

        _load saves all existing keys on top floor so agent_id does not affect runs/cursors/ui_capable (and vice versa).
        """
        with RuntimeState._LOCK:  # Spec-0065/T2: Read-reform-write full-cycle serials
            data = self._load()
            data["agent_id"] = agent_id
            self._save(data=data)

    def get_ui_capable(self) -> bool:
        """# Spec-0063/T1: Read solid ” front-end e2e capacity” state (insume Spec-0055 syntax); missing keyback False.

        False = Conservative assumption that ”no browser” is available - i.e. no real run UI transcrib, RFC stage does not require a stopgap method
        (Better not to miss). _load missing/damage returning to () also falling False.
        """
        data = self._load()
        return bool(data.get("ui_capable", False))

    def set_ui_capable(self, *, value: bool) -> None:
        """# Spec-0063/T1: CrashBackend e2e Capacity ”state ” Quantity (Conduct) Spec-0055 Semantic) ,top key with agent_id Level.

        _load saves all with top keys, so ui_capable does not affect runs/cursors/agent_id (and vice versa).
        """
        with RuntimeState._LOCK:  # Spec-0065/T2: Read-reform-write full-cycle serials
            data = self._load()
            data["ui_capable"] = bool(value)
            self._save(data=data)

    def _load(self) -> dict:
        """Read status files; all missing/damages are considered empty (intolerant)."""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _save(self, *, data: dict) -> None:
        """**Atom**Crash: Write under directory tmp Documentation → `os.replace` Substitute (Present)rename It’s atoms on the same file system).

        # Spec-0065/T2: Direct `write_text` is ”cut first, write later” - the co-author will read half of JSON, while `_load`
        # Mistakes will be considered as ”empty” and then the reader will cover the whole status file with its own record. Atom replacement
        # Then the reader sees either the complete old document or the complete new document, without the middle.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(f"{self._path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)
