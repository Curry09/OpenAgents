"""# Spec-0060/T5: runtime.state —— 新栈 run 状态 + comment 游标持久化（独立命名空间）。

为**不碰**旧 `state.py`（439 行、被 11 个测试桩打），新栈自成一套状态：持久化到独立文件
`.openagents/runtime-state.json`，与旧 `.openagents/state.json` **文件级零冲突**。两套状态最终
如何统一（迁移还是弃旧）留承接 vigil 迁移的批次决定（见 spec Unresolved）。

极简键值形态（奥卡姆，理念 1）：
    {
      "runs": { "<issue_number>": {"status": ..., "branch": ..., "pr_number": ...}, ... },
      "cursors": { "<pr_number>": "<last_comment_id>" }
    }
读写一律容错：文件缺失/损坏视为空状态。不含任何业务判断（判断在 agent），只做持久化机制。
"""

from __future__ import annotations

import json
from pathlib import Path

# Spec-0060/T5: 新栈状态文件名——与旧 state.json 独立命名空间，避免文件级冲突。
RUNTIME_STATE_FILENAME = "runtime-state.json"


class RuntimeState:
    """# Spec-0060/T5: 新栈状态读写器（按状态文件路径构造，独立命名空间）。"""

    def __init__(self, *, path: Path) -> None:
        self._path = Path(path)

    def get_run(self, *, issue_number: int) -> dict | None:
        """取某 issue 的 run 记录；无则 None。"""
        return self._load().get("runs", {}).get(str(issue_number))

    def set_run(
        self, *, issue_number: int, status: str, branch: str, pr_number: int | None
    ) -> None:
        """写/覆盖某 issue 的 run 记录（status/branch/pr_number）。"""
        data = self._load()
        data.setdefault("runs", {})[str(issue_number)] = {
            "status": status,
            "branch": branch,
            "pr_number": pr_number,
        }
        self._save(data=data)

    def get_cursor(self, *, pr_number: int) -> str | None:
        """取某 PR 的 comment 游标（最后处理到的评论 id）；无则 None。"""
        return self._load().get("cursors", {}).get(str(pr_number))

    def set_cursor(self, *, pr_number: int, comment_id: str) -> None:
        """写某 PR 的 comment 游标。"""
        data = self._load()
        data.setdefault("cursors", {})[str(pr_number)] = comment_id
        self._save(data=data)

    def _load(self) -> dict:
        """读状态文件；缺失/损坏一律视为空状态（容错）。"""
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
        """原子性无关的最简落盘（建父目录、写 JSON）。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
