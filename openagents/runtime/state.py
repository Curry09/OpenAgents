"""# Spec-0060/T5: runtime.state —— 新栈 run 状态 + comment 游标持久化（独立命名空间）。

为**不碰**旧 `state.py`（439 行、被 11 个测试桩打），新栈自成一套状态：持久化到独立文件
`.openagents/runtime-state.json`，与旧 `.openagents/state.json` **文件级零冲突**。两套状态最终
如何统一（迁移还是弃旧）留承接 vigil 迁移的批次决定（见 spec Unresolved）。

极简键值形态（奥卡姆，理念 1）：
    {
      "runs": { "<issue_number>": {"status": ..., "branch": ..., "pr_number": ...,
                                   "closed_at": ...(可选)}, ... },
      "cursors": { "<pr_number>": "<last_comment_id>" }
    }
读写一律容错：文件缺失/损坏视为空状态。不含任何业务判断（判断在 agent），只做持久化机制。

# Spec-0062/T3: 为合并/RFC 流水线（recipes.merge_pr / rfc_lifecycle）补 by-PR 查询与富字段——
#   `find_run(pr_number=)` 让 rfc_lifecycle 的 refine/implement/iterate 落到真实 state（此前只有
#   测试 fake seam）；`list_runs()` 让 vigil 守候段把在飞 run 投影成 merge_pr 的 Run（携 issue 归属）；
#   读侧 hydrate `issue_number`（来自 runs 的键）与 `closed_at`（缺省 ""）——**只富化读返回值**，
#   `get_run`/`set_run` 的落盘 3 键形态与既有序列化不变（旧 runtime-state.json 无这些键仍可加载）。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from openagents.runtime import research

# Spec-0060/T5: 新栈状态文件名——与旧 state.json 独立命名空间，避免文件级冲突。
RUNTIME_STATE_FILENAME = "runtime-state.json"

# Spec-0063/T1: 权威状态词表——从旧 state.py 迁入，作为 release 及后续消费方的唯一状态词表来源
# （字面量与旧 state.py 完全一致；旧 STATUS_* 副本随 state.py 删除而退役）。
STATUS_SOLVING = "solving"
STATUS_RFC_REVIEW = "rfc-review"
STATUS_PR_OPEN = "pr-open"
STATUS_ITERATING = "iterating"
STATUS_DONE = "done"
STATUS_CLOSED = "closed"
STATUS_FAILED = "failed"


class RuntimeState:
    """# Spec-0060/T5: 新栈状态读写器（按状态文件路径构造，独立命名空间）。

    # Spec-0065/T2: **并发写要串行 + 落盘要原子。** 守夜起 K 个 worker 线程，它们共用同一个 RuntimeState
    # 实例并发写（`set_run` / `set_cursor`）。写是「读整个 JSON → 改一个键 → 整个写回」：
    #   - 无锁 → **丢更新**：两个 worker 各自读到同一份旧 data，各改各的键，后写的把前者的记录抹掉
    #     （丢一条 `set_run(status=done)` 或一条评论游标 = 重复回帖 / run 状态倒退）。
    #   - 非原子 → **整文件被截断**：`write_text` 先截断再写，另一个线程恰好此时 `_load` 会读到半截 JSON，
    #     `JSONDecodeError` 被容错成「空状态」{}，它接着一写就把**整个状态文件**覆盖成只剩自己那一条。
    # 故：`_LOCK` 串行化「读-改-写」的全程（类级，同实例/同文件的所有写共用），`_save` 走 tmp + `os.replace`
    # （同目录内的 rename 是原子的，读者要么看到旧文件、要么看到新文件，永远看不到半截）。
    # 这只解决**进程内**的并发（守夜的 K 个 worker 是线程）；跨进程并发写同一个 state 文件不在本 spec 范围内
    # （fleet 是每仓一进程、各写各的 state 文件）。
    """

    _LOCK = threading.RLock()

    def __init__(self, *, path: Path) -> None:
        self._path = Path(path)

    def get_run(self, *, issue_number: int) -> dict | None:
        """取某 issue 的 run 记录（落盘原样：status/branch/pr_number[/closed_at]）；无则 None。"""
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
        """写/覆盖某 issue 的 run 记录（status/branch/pr_number）。

        # Spec-0062/T3: `closed_at` 可选（复活窗口用），默认 "" 且**仅非空时落盘**——保持既有 3 键
        # 形态与序列化不变（既有调用方不传 closed_at 时落盘仍是 3 键，旧断言/旧文件零回归）。
        """
        with RuntimeState._LOCK:  # Spec-0065/T2: 读-改-写全程串行（K 个 worker 并发写会丢更新）
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

    def find_run(self, *, pr_number: int) -> dict | None:
        """# Spec-0062/T3: 按 PR 号查 run（rfc_lifecycle refine/implement/iterate 复用）；无则 None。

        返回值经 `_with_issue` hydrate——带 `issue_number`（取自 runs 键）与 `closed_at`（缺省 ""），
        供上层读 issue 归属 / 复活窗口。落盘形态不变，只富化本次读返回。
        """
        for issue_key, record in self._load().get("runs", {}).items():
            if record.get("pr_number") == pr_number:
                return self._with_issue(issue_key=issue_key, record=record)
        return None

    def list_runs(self) -> list[dict]:
        """# Spec-0062/T3: 列全部 run 记录（均经 hydrate 带 issue_number/closed_at）。

        vigil 守候段据此把在飞 run 投影成 merge_pr 的 Run（携 issue 归属回写合并/关 issue）。
        """
        return [
            self._with_issue(issue_key=issue_key, record=record)
            for issue_key, record in self._load().get("runs", {}).items()
        ]

    def _with_issue(self, *, issue_key: str, record: dict) -> dict:
        """把落盘 run 记录 hydrate 成带 issue_number（来自键）与 closed_at（缺省 ""）的读返回值。"""
        hydrated = dict(record)
        hydrated["issue_number"] = int(issue_key)
        hydrated.setdefault("closed_at", "")
        return hydrated

    def get_cursor(self, *, pr_number: int) -> str | None:
        """取某 PR 的 comment 游标（最后处理到的评论 id）；无则 None。"""
        return self._load().get("cursors", {}).get(str(pr_number))

    def set_cursor(self, *, pr_number: int, comment_id: str) -> None:
        """写某 PR 的 comment 游标。"""
        with RuntimeState._LOCK:  # Spec-0065/T2: 同 set_run——丢一条游标 = 对同一条人类评论重复回帖
            data = self._load()
            data.setdefault("cursors", {})[str(pr_number)] = comment_id
            self._save(data=data)

    def get_issue_cursor(self, *, number: int) -> str | None:
        """# Spec-0016/T2：取某 issue 的 comment 游标（最后处理到的 issue 页评论 id）；无则 None。

        与 `get_cursor`（PR 版，`cursors` 键按 pr_number）平级但落**独立命名空间键** `issue_cursors`
        （按 issue number）——issue N 与 PR N 是两个不同的对象，同键会撞（回复 issue N 的游标覆盖
        PR N 的游标 → 对同一条评论重复回帖 / 漏回）。缺省返回 None（=从头算，任意人类评论即算新）。
        """
        return self._load().get("issue_cursors", {}).get(str(number))

    def set_issue_cursor(self, *, number: int, comment_id: str) -> None:
        """# Spec-0016/T2：写某 issue 的 comment 游标（落 `issue_cursors` 键）。"""
        # Spec-0016/T2: 同 set_cursor——读-改-写全程串行（丢一条游标 = 对同一条人类评论重复回帖）
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
        """# Spec-0063/T1: 读已落盘的本实例 agent_id（承接 RFC-0011 语义）；未设过返回 None。

        agent_id 是 runtime-state.json 顶层可选键（与 runs/cursors 平级）。供
        identity.resolve_agent_id 在 env 未指定时复用既有值、保证跨进程/重启稳定。
        _load 缺失/损坏返回 {} 时，data.get 得 None，非空 str 校验回落 None。
        """
        data = self._load()
        agent_id = data.get("agent_id")
        return agent_id if isinstance(agent_id, str) and agent_id else None

    def set_agent_id(self, *, agent_id: str) -> None:
        """# Spec-0063/T1: 落盘本实例 agent_id（承接 RFC-0011 语义）。

        _load 保留顶层的全部既有键，故写 agent_id 不影响 runs/cursors/ui_capable（反之亦然）。
        """
        with RuntimeState._LOCK:  # Spec-0065/T2: 读-改-写全程串行
            data = self._load()
            data["agent_id"] = agent_id
            self._save(data=data)

    def get_ui_capable(self) -> bool:
        """# Spec-0063/T1: 读固化的「前端 e2e 能力」状态量（承接 Spec-0055 语义）；缺键回落 False。

        缺该键回落 False = 保守假设「不具备浏览器」——即无法真跑 UI 截图，RFC 阶段不硬要求截图测法
        （宁可不误挡）。_load 缺失/损坏返回 {} 时同样回落 False。
        """
        data = self._load()
        return bool(data.get("ui_capable", False))

    def set_ui_capable(self, *, value: bool) -> None:
        """# Spec-0063/T1: 落盘本机「前端 e2e 能力」状态量（承接 Spec-0055 语义），顶层键与 agent_id 平级。

        _load 保留全部既有顶层键，故写 ui_capable 不影响 runs/cursors/agent_id（反之亦然）。
        """
        with RuntimeState._LOCK:  # Spec-0065/T2: 读-改-写全程串行
            data = self._load()
            data["ui_capable"] = bool(value)
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
        """**原子**落盘：写同目录下的 tmp 文件 → `os.replace` 顶替（rename 在同一文件系统上是原子的）。

        # Spec-0065/T2: 直接 `write_text` 是「先截断、后写入」——并发的读者会读到半截 JSON，而 `_load` 的
        # 容错会把它当成「空状态」{}，接着那个读者一写就把整个状态文件覆盖成只剩它自己那一条记录。原子顶替
        # 之后，读者要么看到完整的旧文件、要么看到完整的新文件，不存在中间态。
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(f"{self._path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)
