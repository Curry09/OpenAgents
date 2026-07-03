"""RFC-0001 T5 + RFC-0005 + RFC-0012: PR 消息机制 + CI 监控，按**阶段**路由 GitHub 事件。

poll 对每个 open 状态的 run 做一次扫描，先判 merge/close，再按 run 所处阶段路由
（RFC-0005 决策 5）。RFC-0012 把两处「等人」的判定换成「调 reviewer 闸 + 自动推进」，
让人的触点收敛到「提 issue」与「release」（Spec-0023：promote 改名 release）：

  1. github.is_merged：已合并 → State 置 done + 关 issue，跳过（决策 8）。拉式同步重构后**不再**
     push 扇出：其余 open PR 各自轮到时在 _process_coding 的 BEHIND 分支由 update_branch 跟上集成。
  1b. github.is_closed：关闭未合并 → State 置 closed，跳过（RFC-0006，merged 优先）。
  2. 阶段 rfc-review（PR 为 draft、承载 RFC）—— RFC 评审闸（RFC-0012 决策 1/3）：
     a. 已带 rfc-approved 标签（人/agent 谁打都认，向后兼容）→ Orchestrator.implement。
     b. 否则调 Orchestrator.review_rfc：
        - 全票 PASS → 自动打 rfc-approved → implement（转入 coding）。
        - 非 PASS → rounds++；未超 K → refine_rfc（喂 reviewer 反馈）；超 K → BLOCKED+needs-human。
  3. 阶段 coding（pr-open / iterating）—— 代码评审闸（RFC-0012 决策 1）：
     a. CI 失败 → Orchestrator.iterate(reason="ci")（行为保持，CI 回合不计入 rounds）。
     b. CI 进行中 → 等待（本轮不动）。
     c. CI 全绿 → 调 Orchestrator.review_code：
        - 全票 PASS → github.merge_pr（合入 test）→ DONE + 关 issue（不再扇出；拉式同步见 1.）。
        - BEHIND（落后 main 无文本冲突）→ update_branch 拉最新 main 进来触发 CI 重跑（拉式同步）。
        - 非 PASS → rounds++；未超 K → iterate(reason="review")；超 K → BLOCKED+needs-human。

卡住兜底（RFC-0012 决策 5）：rounds（每个闸独立计，implement 时清零）达到 MAX_ROUNDS 时
置 STATUS_BLOCKED + 打 needs-human 标签 + **PR 不关**；STATUS_BLOCKED 不在 _OPEN_STATUSES，
下一轮 poll 自动跳过（软挂起），等人据标签介入。

watch：每隔 interval 秒循环调用 poll，无 open PR 或用户中断时退出（决策 6）。

依赖注入：orchestrator（Orchestrator）、state（State）由构造传入；GitHub 操作以模块
函数方式调用（测试里 monkeypatch github.*），time.sleep 同理可 mock。
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from openagents import (
    blocknote,
    conflict,
    conflictdiag,
    evidence_gate,
    executor,
    github,
    identity,
    replynote,
)
from openagents.backends.base import AgentBackend
from openagents.hold import NONE as NO_HOLD
from openagents.hold import Hold
from openagents.orchestrator import Orchestrator
from openagents.state import (
    BLOCKED_LABEL,
    STATUS_BLOCKED,
    STATUS_CLOSED,
    STATUS_DONE,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    RunRecord,
    State,
)

# 需要继续轮询的状态（决策 8：done 终止，solving 尚未开 PR）。rfc-review 也在轮询范围。
# RFC-0012：blocked（评审超 K 轮挂起）与 closed/done 一样不在此集合，poll 自动跳过。
_OPEN_STATUSES = {STATUS_RFC_REVIEW, STATUS_PR_OPEN, STATUS_ITERATING}

# RFC-0005 决策 4：批准信号——带这个标签即视为 RFC 通过。RFC-0012 决策 3：reviewer 闸
# 全票 PASS 时由 add_label 自动打它，与人工打标签走同一下游路径（向后兼容）。
# RFC-0015：字面量上移至 github（流程标签单一来源），此处改为别名引用，保留
# messages.APPROVAL_LABEL 公共名向后兼容，消除「同一字符串散落三处」的漂移风险。
APPROVAL_LABEL = github.APPROVAL_LABEL

# RFC-0012 决策 6：每个闸的最大评审回合数旋钮——env OPENAGENTS_MAX_ROUNDS，默认 3。
# 模块常量在 import 时定值；测试可 monkeypatch messages.MAX_ROUNDS 覆盖（方法内按全局取值）。
MAX_ROUNDS_ENV = "OPENAGENTS_MAX_ROUNDS"
_DEFAULT_MAX_ROUNDS = 3


def _configured_max_rounds() -> int:
    """读 OPENAGENTS_MAX_ROUNDS；缺省/非法/<1 回落到默认值（至少给一回合迭代机会）。"""
    raw = os.environ.get(MAX_ROUNDS_ENV)
    if not raw:
        return _DEFAULT_MAX_ROUNDS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_ROUNDS
    return value if value >= 1 else _DEFAULT_MAX_ROUNDS


MAX_ROUNDS = _configured_max_rounds()

# Spec-0021/T2：评审无效（裁决无法解析/无可操作反馈）的独立小重试上限旋钮——env
# OPENAGENTS_MAX_REVIEW_RETRIES，默认 2。镜像 _configured_max_rounds 的读取约定。独立于
# MAX_ROUNDS：评审无效不吃真 REWORK 的 round，达本上限后以「reviewer 输出无法解析」升级 needs-human。
MAX_REVIEW_RETRIES_ENV = "OPENAGENTS_MAX_REVIEW_RETRIES"
_DEFAULT_MAX_REVIEW_RETRIES = 2


def _configured_max_review_retries() -> int:
    """读 OPENAGENTS_MAX_REVIEW_RETRIES；缺省/非法/<1 回落到默认值（至少给一次重评机会）。"""
    raw = os.environ.get(MAX_REVIEW_RETRIES_ENV)
    if not raw:
        return _DEFAULT_MAX_REVIEW_RETRIES
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_REVIEW_RETRIES
    return value if value >= 1 else _DEFAULT_MAX_REVIEW_RETRIES


MAX_REVIEW_RETRIES = _configured_max_review_retries()

# Spec-0031/T2：armed 模式下 agent 解 merge 冲突的有界重试上限旋钮——env
# OPENAGENTS_MAX_MERGE_ATTEMPTS，默认 3（对齐 MAX_ROUNDS）。逐字镜像 _configured_max_rounds
# 的读取/兜底/可 monkeypatch 约定。独立于 MAX_ROUNDS / MAX_REVIEW_RETRIES：merge 解冲突重试
# 与评审回合 / 评审无效是不同性质的预算，互不偷吃、可分别调参。
MAX_MERGE_ATTEMPTS_ENV = "OPENAGENTS_MAX_MERGE_ATTEMPTS"
_DEFAULT_MAX_MERGE_ATTEMPTS = 3


def _configured_max_merge_attempts() -> int:
    """读 OPENAGENTS_MAX_MERGE_ATTEMPTS；缺省/非法/<1 回落到默认值（至少给一次解冲突机会）。"""
    raw = os.environ.get(MAX_MERGE_ATTEMPTS_ENV)
    if not raw:
        return _DEFAULT_MAX_MERGE_ATTEMPTS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_MERGE_ATTEMPTS
    return value if value >= 1 else _DEFAULT_MAX_MERGE_ATTEMPTS


MAX_MERGE_ATTEMPTS = _configured_max_merge_attempts()

# Spec-0042/T3：closed run 的「复活窗口」——只对 closed_at 在此秒数内的 closed run 每轮花一次
# gh 查 reopen，超窗口即硬化成真终态、poll 不再对它发任何 gh（成本有界；见 Spec-0042 Motivation
# 的成本约束）。默认 7 天。GitHub 的 PR close 可逆（可 reopen 回 OPEN），但历史累积的 closed run
# 越攒越多，若无界地每轮盲查会把 gh 调用数拖垮，故用时间窗口上界住。可按实际观测调（暂不暴露 env）。
REOPEN_REVIVE_WINDOW_SECONDS = 7 * 24 * 3600

# Spec-0032/T5: gate → 挂起评论「我试过什么」段的人类可读文案。messages 据持久化 gate 选一句
# 传给 blocknote.build（展示文案，不参与路由判定）；未知 gate 回落到通用句、绝不抛。
_TRIED_BY_GATE = {
    "rfc": "已按 reviewer 反馈多轮精炼 RFC，仍未通过评审",
    "code": "已按 reviewer 反馈多轮迭代代码，仍未通过评审",
    "rfc-unparseable": "多次重评仍无法解析 reviewer 对 RFC 的裁决",
    "code-unparseable": "多次重评仍无法解析 reviewer 对代码的裁决",
    "merge": "已尝试自动解冲突，但仍与目标分支存在冲突",
    # Spec-0040/T5：证据闸多轮 FAIL——独立 executor 真跑系统的证据始终对不上 RFC 意图。
    "e2e": "已多轮定稿说明书 + 独立 executor 真跑系统，证据仍未达成 RFC 批准的 e2e 意图",
}
_DEFAULT_TRIED = "已反复尝试，仍未通过"


class Messages:
    """RFC-0001 T5 + RFC-0005 + RFC-0012：按阶段轮询 PR 的 merge/CI/评审闸，路由回编排层。"""

    def __init__(
        self,
        *,
        orchestrator: Orchestrator,
        state: State,
        agent_id: str,
        work_dir: str | None = None,
        base: str | None = None,
        backend: AgentBackend | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._state = state
        # RFC-0011 决策 7：本实例身份，由 CLI 接线处解析后注入；解冲突 / 挂起留言据此盖章。
        self._agent_id = agent_id
        # work_dir + base 用于 _process_coding 的 BEHIND 拉式同步（update_branch）与冲突诊断器；
        # 缺一则退回「冲突留言等人」（向后兼容老调用方/测试夹具）。
        self._work_dir = work_dir
        self._base = base
        # backend 用于构造 agent 语义解冲突 resolve（work_dir + base + backend 齐备才构造，缺一则
        # 不注入——merge 闸冲突回落 needs-human；向后兼容老调用方/测试夹具）。
        self._backend = backend

    def poll(self, *, hold: Hold = NO_HOLD) -> list[dict]:
        """RFC-0001 T5：扫描所有 open 状态 run，按 merge → 阶段 路由。

        返回本轮事件列表，每个事件含 pr_number 与 reason（reason ∈ {"merged", "closed",
        "approved", "rfc-pass", "refine", "ci", "review", "review-invalid", "blocked",
        "resumed", "resolved", "unmergeable", "merge-retry", "hold-spec", "hold-merge",
        "e2e", "reopened"}），便于日志与测试断言。Spec-0021/T2：新增 "review-invalid"（评审无效
        本轮等下一轮重评，不吃 round、不空转）。Spec-0031/T2：新增 "merge-retry"（armed 模式本轮派
        agent 解冲突未成、未达上限，保持 pr-open 等下一轮再试，不重挂）。Spec-0040/T5：新增 "e2e"
        （reviewer PASS 后证据闸 FAIL，本轮走 iterate 回去改，未挂起）。Spec-0042/T3：新增 "reopened"
        （closed run 对应 PR 被 reopen → 复活到 rfc-review/pr-open、清 closed_at，当轮不续跑闸、
        下轮走既有路径）。

        Spec-0020/T3：新增关键字参数 hold（Hold），默认「全不停」以保持现有调用与行为；
        poll 内部把 hold 下传给两道闸的私有处理函数，spec / merge 闸据 hold 选择「停在闸门
        等人」或现状自动推进分支。默认 Hold 下走原代码、行为逐字节不变（零回归）。
        """
        events: list[dict] = []
        for record in self._state.all_runs():
            # issue #49：blocked 也纳入扫描（用于解挂/reconcile），其余非 open 状态照常跳过。
            # Spec-0042/T3：closed 不是真终态——「复活候选」（closed 且 closed_at 在复活窗口内）
            # 也放行进 _process_run，去查它对应的 PR 是否已被 reopen；超窗口/无 closed_at 的老
            # closed run 不是候选，照常跳过（不发任何 gh，成本有界）。
            if (
                record.status not in _OPEN_STATUSES
                and record.status != STATUS_BLOCKED
                and not self._revive_eligible(record=record)
            ):
                continue
            # Spec-0022/T2：单 record 错误隔离（沿用 RFC-0004 决策 8 的单 record 隔离风格）——
            # 单个 PR 处理失败（含 merge_pr 抛 GithubError）只追加一条 error 事件并 continue，绝不让
            # 异常冒泡掀翻整轮 poll。不改 state：失败可能是瞬时 gh 错误，记录可观测、下一轮自然重试。
            try:
                event = self._process_run(record=record, hold=hold)
            except Exception as error:  # noqa: BLE001 — 错误隔离：单 record 失败不拖垮整轮
                events.append(
                    {"pr_number": record.pr_number, "reason": "error", "error": str(error)}
                )
                continue
            if event is not None:
                events.append(event)
        return events

    def watch(self, *, interval: int) -> None:
        """RFC-0001 T5（决策 6）：每隔 interval 秒循环 poll，无 open PR 或中断时退出。"""
        try:
            while self._has_open_pr():
                self.poll()
                if not self._has_open_pr():
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            return

    def _process_run(self, *, record: RunRecord, hold: Hold) -> dict | None:
        """处理单个 run：merge/close 优先 reconcile，blocked 尝试解挂，其余按阶段路由。

        Spec-0020/T3：merge/close/blocked 的 reconcile 与 hold 无关（人已经合/关/解挂，
        是终态信号，照常收口）；hold 只影响仍在 rfc-review / coding 阶段的两道意图闸。
        """
        pr_number = record.pr_number
        # 1. 已合并优先于一切：置 done 并跳过（决策 8）。
        if github.is_merged(pr_number=pr_number):
            self._state.update_status(issue_number=record.issue_number, status=STATUS_DONE)
            # RFC-0017：合进 test（非默认分支）GitHub 不会自动关 issue，由框架显式关——
            # 与 STATUS_DONE「工作落进体验分支即完成」语义一致。close_issue 幂等，多轮 poll
            # 重复命中已合并分支重复调用安全（决策 2）。
            github.close_issue(number=record.issue_number)
            # 拉式同步取代 push 扇出：人手动合并后只做 reconcile（置 done + 关 issue），不再主动把
            # 最新 main 扇给其余 open PR——它们各自轮到时在 _process_coding 的 BEHIND 分支由
            # update_branch 跟上集成（只剩门2一个集成/冲突处理点，理念 1 奥卡姆）。
            return {"pr_number": pr_number, "reason": "merged"}

        # 1a2. Spec-0042/T3：本地已 closed 的复活候选（能走到这里说明已过 _revive_eligible 窗口
        # 守卫）——查它对应的 PR 是否被 reopen。merged 优先（上分支已收口，不可逆）；这里只处理
        # closed。放在 is_closed 之前，使已 closed 的 run 走复活分支而非重跑下面的 open→closed 逻辑
        # （从而下面的 is_closed 分支只会在 open→closed 这一次转移时命中、打戳一次，绝不重打戳）。
        if record.status == STATUS_CLOSED:
            return self._revive_if_reopened(record=record)

        # 1b. RFC-0006：人主动关闭（未合并）也是终止信号 → 置 closed 并跳过。merged 优先于 closed。
        # Spec-0042/T3：置 closed 的同时打 closed_at 时间戳（复活窗口起点）。此分支只在 open→closed
        # （或 blocked→closed）这一次转移时命中——已 closed 的 run 在上面的复活分支就 return 了，
        # 不会再落到这里，故这里的 set_closed_at 永远是首次打戳、天然满足「仅转移时打戳、不重打戳」。
        if github.is_closed(pr_number=pr_number):
            self._state.update_status(issue_number=record.issue_number, status=STATUS_CLOSED)
            self._state.set_closed_at(
                issue_number=record.issue_number,
                when=datetime.now(UTC).isoformat(),
            )
            return {"pr_number": pr_number, "reason": "closed"}

        # 1c. issue #49 / Spec-0032/T5：blocked 不再是死胡同。PR 被合/被关已在上面统一 reconcile。
        # 仍 open 的 blocked run 走两层解挂：① 回评论解挂主路径（人在 block 之后回新评论 = 解挂信号，
        # 把评论当 detail 喂给对应闸）；② 兜底人手动摘 needs-human 标签（既有路径，保留）。
        if record.status == STATUS_BLOCKED:
            return self._process_blocked(record=record)

        # 2. 按阶段路由（决策 5）。
        if record.status == STATUS_RFC_REVIEW:
            return self._process_rfc_review(record=record, hold=hold)
        return self._process_coding(record=record, hold=hold)

    def _revive_eligible(self, *, record: RunRecord) -> bool:
        """Spec-0042/T3：该 record 是否为「复活候选」——closed 且 closed_at 在复活窗口内。

        只有候选才被 poll 入口守卫放行去查 reopen（发 gh）；超窗口 / 无 closed_at（含缺该键的
        旧 closed 记录）的 closed run 硬化成真终态、返 False（照常跳过、不发任何 gh，成本有界）。
        窗口是墙钟判定：now 取 UTC，与 closed_at 时间戳比较；closed_at 无法解析（异常数据）→ False。
        """
        if record.status != STATUS_CLOSED or not record.closed_at:
            return False
        try:
            closed_at = datetime.fromisoformat(record.closed_at)
        except ValueError:
            return False
        elapsed = (datetime.now(UTC) - closed_at).total_seconds()
        return elapsed <= REOPEN_REVIVE_WINDOW_SECONDS

    def _revive_if_reopened(self, *, record: RunRecord) -> dict | None:
        """Spec-0042/T3：closed 复活候选的专属 reconcile——PR 被 reopen 则按现状复活，否则保持跳过。

        - PR 仍非 OPEN（还是 closed；merged 已在上游分支收口）→ return None：保持跳过、**不重打戳**
          （closed_at 不动，窗口不刷新，成本有界）。
        - PR 已 OPEN（reopened）→ 按 PR 现状推断阶段并复活：draft PR（RFC 未批/代码未写完）→
          rfc-review；已转正 PR → pr-open（走代码闸）。复活同时清 closed_at（退出复活窗口）+ 清回合
          预算 + 清 block_gate 残留（reopen = 重来，避免旧 armed "merge" 标记在复活到 pr-open 后被误判
          为「派 agent 解冲突」）。复活只做状态归位，**当轮返回 reopened 事件、不续跑闸**——下一轮 poll
          这个 run 已是正常 open run，走既有 rfc-review / coding 路径（评论 / CI / 冲突全由既有机制处理）。
        """
        pr_number = record.pr_number
        if not github.is_open(pr_number=pr_number):
            return None
        stage = STATUS_RFC_REVIEW if github.is_draft(pr_number=pr_number) else STATUS_PR_OPEN
        issue_number = record.issue_number
        self._state.update_status(issue_number=issue_number, status=stage)
        self._state.set_closed_at(issue_number=issue_number, when="")
        # reopen = 重来：清回合预算 + 清 armed 标记残留，避免陈旧状态渗进复活后的既有流程。
        self._state.reset_rounds(issue_number=issue_number)
        self._state.set_block_gate(issue_number=issue_number, gate="")
        return {"pr_number": pr_number, "reason": "reopened", "stage": stage}

    def _process_blocked(self, *, record: RunRecord) -> dict | None:
        """Spec-0032/T5：blocked run 的两层解挂——回评论解挂（主）+ 人手动摘标签（兜底）。

        主路径：identity.new_human_comments(since=block_watermark) 取「block 之后的无签名人类
        评论」（仅新评论 + 仅人类两道硬约束化解 RFC-0019 自循环顾虑）；命中即把最后一条评论正文当
        detail 自动解挂（_unblock_with_comment）。无新评论则退回兜底：needs-human 仍在 → 保持挂起
        （return None）；标签已被人手动摘 → 走既有 label 解挂（_unblock_by_label，零回归）。
        """
        pr_number = record.pr_number
        news = identity.new_human_comments(pr_number=pr_number, since=record.block_watermark)
        if news:
            return self._unblock_with_comment(record=record, detail=news[-1].body)
        if github.has_label(pr_number=pr_number, name=BLOCKED_LABEL):
            return None
        return self._unblock_by_label(record=record)

    def _unblock_with_comment(self, *, record: RunRecord, detail: str) -> dict:
        """Spec-0032/T5 + Spec-0036/T5：回评论解挂——摘标签 + 清回合预算 + 按 block_gate 喂评论给对应闸。

        路由（按持久化 block_gate）：
        - rfc/rfc-unparseable → refine_rfc(detail, announce=False)（内部置 rfc-review）+ 清残留
          block_gate + **引用原评论贴回 agent 回应**（Spec-0036/T5：announce=False 抑制泛化广播，
          换成一条针对性回应）。
        - code/code-unparseable/merge-hold → iterate(reason="human", detail)（内部置 iterating）+ 清残留
          block_gate + **引用原评论贴回 agent 回应**。Spec-0041/T1：merge-hold（hold-merge 夯住）与
          code* 同款——人在已通过 PR 上回评论 = 想据评论继续改。
        - merge → 不直接喂解冲突器，按 armed 语义恢复 pr-open、**保留** block_gate="merge" 作标记
          （reset_rounds 已清 merge_attempts 给满预算），并 set_unblock_detail 把评论正文存进 state
          供下一轮 armed 解冲突当 guidance + 回应时引用（Spec-0036/T5）。**本轮不回应**（动作尚未发生，
          下一轮 armed 跑完才回）。解冲突交 _process_armed_conflict（Spec-0031）。
        - ""（理论兜底）→ 按 rfc-approved 决定恢复阶段（不回应）。
        """
        pr_number = record.pr_number
        issue_number = record.issue_number
        # 自动摘 needs-human（remove_label 幂等：人可能已先手动摘）+ 清回合预算。
        github.remove_label(pr_number=pr_number, name=BLOCKED_LABEL)
        self._state.reset_rounds(issue_number=issue_number)
        gate = record.block_gate
        if gate in ("rfc", "rfc-unparseable"):
            summary = self._orchestrator.refine_rfc(
                pr_number=pr_number, detail=detail, announce=False
            )
            self._state.set_block_gate(issue_number=issue_number, gate="")
            self._post_comment_reply(pr_number=pr_number, original=detail, response=summary)
        elif gate in ("code", "code-unparseable", "merge-hold"):
            # Spec-0041/T1（决策 B）：merge-hold（hold-merge 夯住）与 code* 同款——人在这个已通过、
            # 健康的 PR 上回评论 = 想让写码 agent 据评论继续改，故 iterate(reason="human", detail)。
            summary = self._orchestrator.iterate(pr_number=pr_number, reason="human", detail=detail)
            self._state.set_block_gate(issue_number=issue_number, gate="")
            self._post_comment_reply(pr_number=pr_number, original=detail, response=summary)
        elif gate == "merge":
            self._state.update_status(issue_number=issue_number, status=STATUS_PR_OPEN)
            self._state.set_unblock_detail(issue_number=issue_number, detail=detail)
        else:
            resumed = (
                STATUS_PR_OPEN
                if github.has_label(pr_number=pr_number, name=APPROVAL_LABEL)
                else STATUS_RFC_REVIEW
            )
            self._state.update_status(issue_number=issue_number, status=resumed)
        return {"pr_number": pr_number, "reason": "resumed"}

    def _post_comment_reply(self, *, pr_number: int, original: str, response: str) -> None:
        """Spec-0036/T5：引用触发解挂的那条人类评论，盖签名贴回一条 agent 回应（恰一条）。

        路由核心只做「取数 + 引用原评论盖签名贴出」——展示模板（引用块 + 回应段布局）在
        replynote.build 里，回应正文（response）由调用方提供（rfc/code 取 agent summary、merge 取
        结论文案）。盖本实例签名 → 解挂读侧 new_human_comments 按签名滤掉它，不自触发。
        """
        body = replynote.build(original=original, response=response)
        identity.post_signed_comment(pr_number=pr_number, body=body, agent_id=self._agent_id)

    def _unblock_by_label(self, *, record: RunRecord) -> dict:
        """issue #49 / Spec-0031/T2：人手动摘 needs-human 标签后的解挂（无 detail 注入）——兜底路径。

        逐字节保持既有行为（零回归）：reset_rounds 后按 block_gate 区分——merge 闸进 armed（恢复
        pr-open、保留 block_gate="merge" 作标记）；其余闸按是否已过 RFC 闸恢复阶段并清残留 block_gate。
        """
        pr_number = record.pr_number
        issue_number = record.issue_number
        self._state.reset_rounds(issue_number=issue_number)
        if record.block_gate == "merge":
            self._state.update_status(issue_number=issue_number, status=STATUS_PR_OPEN)
            return {"pr_number": pr_number, "reason": "resumed"}
        resumed = (
            STATUS_PR_OPEN
            if github.has_label(pr_number=pr_number, name=APPROVAL_LABEL)
            else STATUS_RFC_REVIEW
        )
        self._state.update_status(issue_number=issue_number, status=resumed)
        self._state.set_block_gate(issue_number=issue_number, gate="")
        return {"pr_number": pr_number, "reason": "resumed"}

    def _process_rfc_review(self, *, record: RunRecord, hold: Hold) -> dict | None:
        """RFC 评审闸（RFC-0012 决策 1/3）：标签 / reviewer 全票 PASS → implement；非 PASS → refine 或 BLOCKED。"""
        pr_number = record.pr_number
        # 2a. 已带批准标签（人或上一轮 reviewer 打的）优先：直接转入实现（向后兼容）。
        if github.has_label(pr_number=pr_number, name=APPROVAL_LABEL):
            self._orchestrator.implement(pr_number=pr_number)
            return {"pr_number": pr_number, "reason": "approved"}
        # Spec-0020/T3：spec 闸 hold——跳过下面的自动 reviewer（2b），只认上面 2a 的人工
        # rfc-approved label。无 label 即本轮什么都不做、停在 spec 闸等人批（不评审、不打
        # 标签、不 refine、不 block、不进 coding）——把这道闸完全交给人，复用既有 label 门控。
        if hold.at_spec:
            return {"pr_number": pr_number, "reason": "hold-spec"}
        # 2b. 主动调 reviewer 评审 RFC（决策 3：不再等人打标签）。
        decision = self._orchestrator.review_rfc(pr_number=pr_number)
        if decision.passed:
            github.add_label(pr_number=pr_number, name=APPROVAL_LABEL)
            self._orchestrator.implement(pr_number=pr_number)
            return {"pr_number": pr_number, "reason": "rfc-pass"}
        # Spec-0021/T2：非 PASS 按 decision.actionable 分流。
        # 真 REWORK（actionable）：回合 +1，未超 K 则按 reviewer 反馈精炼 RFC，超 K 则挂起（决策 5，行为不变）。
        if decision.actionable:
            rounds = self._state.increment_rounds(issue_number=record.issue_number)
            if rounds >= MAX_ROUNDS:
                # Spec-0032/T5：超 K 挂起时把 reviewer 反馈原文当 blocker 喂进结构化挂起评论。
                return self._block(record=record, gate="rfc", blocker=decision.feedback)
            self._orchestrator.refine_rfc(pr_number=pr_number, detail=decision.feedback)
            return {"pr_number": pr_number, "reason": "refine"}
        # 评审无效（裁决无法解析/无可操作反馈）：不 rounds++、不 refine（不空转写码 agent），
        # 改用独立小重试上限。未超则本轮返回 review-invalid 事件、等下一轮重评（T1 的裁决前置+
        # 重解析使重评有相当概率拿到可解析裁决）；达上限说明 reviewer 输出持续无法解析 → 以
        # 真实理由升级 needs-human（gate=rfc-unparseable，区别于真 REWORK 攒满 MAX_ROUNDS 的假阳）。
        return self._handle_review_invalid(record=record, gate="rfc-unparseable")

    def _process_coding(self, *, record: RunRecord, hold: Hold) -> dict | None:
        """代码评审闸（RFC-0012 决策 1）：CI 失败→iterate(ci)；CI 绿+reviewer PASS→merge；非 PASS→iterate 或 BLOCKED。"""
        pr_number = record.pr_number
        # Spec-0022/T2：跑 reviewer 前先做可合并性预检——真冲突的 PR 连 CI 都不必等，越早短路越省。
        # 判定取「或」更稳：DIRTY 与 CONFLICTING 在冲突场景同时出现（实例 PR #61）。
        merge_state = github.mergeability(pr_number=pr_number)
        if merge_state.merge_state_status == "DIRTY" or merge_state.mergeable == "CONFLICTING":
            # Spec-0031/T2：按 block_gate=="merge"（armed）区分「人解挂后主动解冲突」与「系统首次
            # 发现冲突」两个入口。armed 只可能由人解挂一个 merge 冲突挂起的 run 产生（状态机不变式）。
            if record.block_gate == "merge":
                return self._process_armed_conflict(record=record)
            # 首次发现冲突（block_gate != "merge"）：逐字节保持 Spec-0028 现状——试一次 agent 语义
            # 解冲突（resolve 注入时），成功本轮不 block、push 后等下一轮重查；resolve=None / 失败
            # 才发一次 rebase 提示 + _block 置 BLOCKED+needs-human（此 _block 把 block_gate 置
            # "merge"，为将来人解挂铺好 armed 入口）。「恰一条评论」由状态机短路天然保证：blocked 后
            # 下一轮 poll 经 _process_run 的 blocked 分支 return None，永不再进 _process_coding。
            resolve = self._make_resolver()
            if resolve is not None and resolve(pr_number=pr_number):
                return {"pr_number": pr_number, "reason": "resolved"}
            # Spec-0032/T5：挂起评论统一由 _block 经 blocknote 出（取代这里单独贴 CONFLICT_COMMENT）；
            # merge 闸把冲突提示文案当 blocker 喂进结构化评论的「卡在哪」段。
            # Spec-0034/T3：blocker 改取 _conflict_blocker（有诊断器时带冲突文件清单 + 关键 hunk 摘要）。
            self._block(
                record=record, gate="merge", blocker=self._conflict_blocker(pr_number=pr_number)
            )
            return {"pr_number": pr_number, "reason": "unmergeable"}
        if merge_state.mergeable == "UNKNOWN":
            # GitHub 异步尚未算完（刚 push 常见）：本轮不评审也不 block，下个 interval 重查——
            # 避免「未就绪→误 block 正常 PR」与「白跑 reviewer」两头错。
            return None
        if merge_state.merge_state_status == "BEHIND":
            # 拉式同步（取代旧的「合并即 push 扇出」）：PR 落后于 main 但无文本冲突——轮到它自己时
            # 由 update_branch 服务端把最新 main 并进来，触发其 CI 在「集成后代码」上重跑；本轮不
            # 评审，下一轮以集成态推进（评审永远看的是最终要合的集成态）。已最新 → no-op。
            # update_branch 撞冲突抛 GithubError → 下一轮 mergeability 即 DIRTY，自然落到上面的
            # agent 解冲突路径，无需在此重复处理（脏活只此一个解冲突脑子）。
            try:
                github.update_branch(pr_number=pr_number)
            except github.GithubError:
                return {"pr_number": pr_number, "reason": "behind-conflict"}
            return {"pr_number": pr_number, "reason": "synced"}
        # 3a. CI 失败：以失败日志喂回 agent（决策 11，行为保持——CI 回合不计入 rounds）。
        status = github.check_status(pr_number=pr_number)
        if status.state == "fail":
            detail = "\n".join(status.failed_logs)
            self._orchestrator.iterate(pr_number=pr_number, reason="ci", detail=detail)
            return {"pr_number": pr_number, "reason": "ci"}
        # 3b. CI 进行中：等下一轮（不评审、不动状态）。
        if status.state == "pending":
            return None
        # 3c. CI 全绿 → 调 reviewer 评审代码（决策 1）。
        decision = self._orchestrator.review_code(pr_number=pr_number)
        if decision.passed:
            # Spec-0040/T5：代码 reviewer PASS 后、merge（及 merge 闸夯住）前插入**证据闸**——独立
            # executor 照定稿说明书真跑系统、证据闸拿 RFC 意图对照证据门控合并。代码 reviewer PASS
            # （看着对）但证据闸 FAIL（真跑跑不通）正是要抓的：短路返回其事件（iterate(reason="e2e")
            # / 超 K 挂起），不 merge、也不进 merge 闸。
            gate_event = self._evidence_gate(record=record)
            if gate_event is not None:
                return gate_event
            # Spec-0041/T1：merge 闸 hold——证据闸过后仍不自动 merge_pr，改为**夯住**：置 blocked +
            # needs-human + 贴成功文案（决策 A）。blocked 不在 _OPEN_STATUSES → 下一轮 poll 自动跳过、
            # 不再重审，从根上消除同码复审震荡（取代 Spec-0020/T3 的「停在 pr-open 空转、下轮重审」旧
            # 行为）。人点合并/回评论/撕标签三出口全复用既有机制（is_merged reconcile / merge-hold→
            # iterate / _unblock_by_label）。
            if hold.at_merge:
                return self._hold_merge_freeze(record=record)
            github.merge_pr(pr_number=pr_number)
            self._state.update_status(issue_number=record.issue_number, status=STATUS_DONE)
            # RFC-0017：合进 test 后显式关 issue（与上方已合并分支同理，幂等容错）。
            github.close_issue(number=record.issue_number)
            # 拉式同步取代 push 扇出：框架自己 merge 后不再同轮扇出，其余 open PR 各自轮到时在
            # _process_coding 的 BEHIND 分支由 update_branch 跟上集成（与 is_merged 路径同款，
            # 只剩门2一个集成/冲突处理点）。
            return {"pr_number": pr_number, "reason": "merged"}
        # Spec-0021/T2：非 PASS 按 decision.actionable 分流（与 spec 闸同构）。
        # 真 REWORK（actionable）：回合 +1，未超 K 则按 reviewer 反馈迭代代码，超 K 则挂起（决策 5，行为不变）。
        if decision.actionable:
            rounds = self._state.increment_rounds(issue_number=record.issue_number)
            if rounds >= MAX_ROUNDS:
                # Spec-0032/T5：超 K 挂起时把 reviewer 反馈原文当 blocker 喂进结构化挂起评论。
                return self._block(record=record, gate="code", blocker=decision.feedback)
            self._orchestrator.iterate(
                pr_number=pr_number, reason="review", detail=decision.feedback
            )
            return {"pr_number": pr_number, "reason": "review"}
        # 评审无效：不 rounds++、不 iterate，走独立小重试上限（gate=code-unparseable）。
        return self._handle_review_invalid(record=record, gate="code-unparseable")

    def _handle_review_invalid(self, *, record: RunRecord, gate: str) -> dict:
        """Spec-0021/T2：两道闸共用的「评审无效」收口——独立小重试上限 + 诚实升级。

        评审无效（裁决无法解析/无可操作反馈）独立于 rounds 计数：每轮 +1，未达
        MAX_REVIEW_RETRIES 就返回 review-invalid 事件、本轮不动 rounds/不 refine/iterate，
        等下一轮 poll 重评；达上限说明 reviewer 输出持续无法解析，以真实理由 _block 升级
        needs-human（gate 携带 *-unparseable 标记，与真 REWORK 攒满 MAX_ROUNDS 的假阳区分开）。
        """
        invalid = self._state.increment_review_invalid(issue_number=record.issue_number)
        if invalid >= MAX_REVIEW_RETRIES:
            # Spec-0032/T5：评审无法解析时无可操作的 reviewer 反馈正文，blocker 留空（blocknote
            # 占位「暂无更多细节」），其余四段仍由 gate→原因/试过短语填满。
            return self._block(record=record, gate=gate, blocker="")
        return {"pr_number": record.pr_number, "reason": "review-invalid"}

    def _evidence_gate(self, *, record: RunRecord) -> dict | None:
        """Spec-0040/T5：证据闸——定稿 runbook → executor 真跑 → 证据闸判 → 门控合并。

        插在代码 reviewer PASS 之后、merge 之前（_process_coding）。链路（Spec-0040 Reference-level）：
        ③ orchestrator.finalize_runbook（派实现者定稿 runbook.md 并 commit；**无 e2e 粗规划则返 None
        →证据闸空过**，非交互 PR 零回归）→ ④ executor.run_executor（独立 agent 读 runbook 按形态真跑、
        把证据写进 evidence_dir）→ ⑤ orchestrator.commit_evidence（证据 commit 进 PR）→
        ⑥ evidence_gate.review_evidence（拿 RFC 意图对照证据判 PASS/FAIL）。

        返回约定：
        - None → 放行（证据闸空过 / 证据 PASS），_process_coding 继续走 merge / hold-merge。
        - dict → 短路：证据 FAIL 走 iterate(reason="e2e")（回合 +1）；攒满 K 轮走 _block(gate="e2e")。

        门控绝不因缺 backend 误挡：无 backend（老夹具/未注入）→ 无法真跑 executor → 证据闸空过（None），
        与旧行为一致（真实编排 cli 必注入 backend，见 cli._messages_for）。executor/证据闸自身绝不抛错。
        """
        if self._backend is None:
            return None
        pr_number = record.pr_number
        handle = self._orchestrator.finalize_runbook(pr_number=pr_number)
        if handle is None:
            return None  # 无 e2e 粗规划：非交互 PR，证据闸空过。
        # ④ 独立 executor 照 runbook 真跑系统、把证据写进 evidence_dir（契约绝不抛错）。
        executor.run_executor(
            backend=self._backend,
            work_dir=handle.worktree,
            runbook_path=handle.runbook_path,
            evidence_dir=handle.evidence_dir,
            pr_number=pr_number,
        )
        # ⑤ 证据 commit 进 PR（durable、可被证据闸读、给人看成果）。
        self._orchestrator.commit_evidence(pr_number=pr_number)
        # ⑥ 证据闸拿 RFC 意图对照证据判达成与否（契约绝不抛错）。
        decision = evidence_gate.review_evidence(
            backend=self._backend,
            work_dir=handle.worktree,
            intent=handle.intent,
            evidence_dir=handle.evidence_dir,
            pr_number=pr_number,
        )
        if decision.passed:
            return None  # 证据真达成 RFC 意图 → 放行 merge。
        # 证据 FAIL：复用现成回合预算与 code 闸共用一份 K（Spec-0040 状态机影响：不新增 status）。
        rounds = self._state.increment_rounds(issue_number=record.issue_number)
        if rounds >= MAX_ROUNDS:
            return self._block(record=record, gate="e2e", blocker=decision.feedback)
        self._orchestrator.iterate(pr_number=pr_number, reason="e2e", detail=decision.feedback)
        return {"pr_number": pr_number, "reason": "e2e"}

    def _process_armed_conflict(self, *, record: RunRecord) -> dict:
        """Spec-0031/T2 + Spec-0036/T5：armed 模式下派 agent 解冲突的有界重试 + 引用原评论贴回结论。

        每轮 poll 进来一次（block_gate=="merge" 且回到 pr-open）：
        - resolve 成功 → 清 armed（block_gate="" + reset 预算）、返回 "resolved"，下一轮 CI 因
          synchronize 重排自然推进。
        - resolve is None（无 backend，重试无意义）→ 直接回落人工（_block），不空转重试。
        - resolve 失败 → merge_attempts +1：未达 MAX_MERGE_ATTEMPTS 返回 "merge-retry"、保持
          pr-open、**不重挂**（跨轮有界重试，给 agent「若干次」真正动手的机会）；达上限才 _block
          重新挂起等人（block_gate 再次置 "merge"，下次人解挂可再 arm）。

        Spec-0036/T5：record.unblock_detail（人解挂时存的评论正文）非空时——① 当作 guidance 透传给
        resolve（merge 闸也听人话，A 项）；② 解冲突**跑完**（终态：解决 / 重新挂起）后经
        _post_comment_reply 引用原评论恰贴一条结论回应，并 set_unblock_detail("") 清空（避免重复回应 /
        陈旧 guidance）。merge-retry（未达上限、保持 pr-open）不算跑完，**不回应、不清 detail**，下一轮
        仍喂同一 guidance。空 detail（手动摘标签解挂，无评论）→ resolve(guidance="") 且不回应，逐字节
        保持 Spec-0031 现状（零回归）。
        """
        pr_number = record.pr_number
        issue_number = record.issue_number
        detail = record.unblock_detail
        resolve = self._make_resolver()
        # detail（人解挂时的评论）作 guidance 喂 resolve；解冲突 agent 会**自己**用 reply-comment 工具
        # 回那条评论（带签名防自循环）——框架不再代发回复（根治「牛头不对马嘴」，见 conflict._REPLY_TOOL_SECTION）。
        outcome = resolve(pr_number=pr_number, guidance=detail) if resolve is not None else None
        # 1. 解决了：清 armed 标记 + 重置预算 + 清 unblock_detail（本轮跑完，避免下一轮重喂 guidance）。
        if outcome is not None and outcome.resolved:
            self._state.set_block_gate(issue_number=issue_number, gate="")
            self._state.reset_rounds(issue_number=issue_number)
            if detail:
                self._state.set_unblock_detail(issue_number=issue_number, detail="")
            return {"pr_number": pr_number, "reason": "resolved"}
        # 2. 无 backend（resolve is None）：重试无意义，直接回落人工兜底，不空转。
        if resolve is None:
            # Spec-0032/T5：挂起评论由 _block 经 blocknote 统一出（blocker = 冲突提示文案）。
            # Spec-0034/T3：blocker 改取 _conflict_blocker（有诊断器时带诊断）。
            self._block(
                record=record, gate="merge", blocker=self._conflict_blocker(pr_number=pr_number)
            )
            if detail:
                self._state.set_unblock_detail(issue_number=issue_number, detail="")
            return {"pr_number": pr_number, "reason": "unmergeable"}
        # 3. 解不了：计数 +1，未达上限跨轮重试（保持 pr-open、不重挂、不清 detail——下一轮仍喂同一 guidance）。
        attempts = self._state.increment_merge_attempts(issue_number=issue_number)
        if attempts < MAX_MERGE_ATTEMPTS:
            return {"pr_number": pr_number, "reason": "merge-retry"}
        # 达上限：重新挂起（blocker 带诊断）+ 清 detail（本轮跑完）。
        self._block(
            record=record, gate="merge", blocker=self._conflict_blocker(pr_number=pr_number)
        )
        if detail:
            self._state.set_unblock_detail(issue_number=issue_number, detail="")
        return {"pr_number": pr_number, "reason": "unmergeable"}

    def _block(self, *, record: RunRecord, gate: str, blocker: str) -> dict:
        """RFC-0012 决策 5 + Spec-0032/T5：超 K 轮挂起——留足信息的结构化评论 + 置 BLOCKED + 标签 + 水位线。

        STATUS_BLOCKED 不在 _OPEN_STATUSES，下一轮 poll 自动跳过（软挂起）；needs-human 标签是给人/
        release 预检看的「求救」信号。PR 保持 open，等人修完再恢复流转。

        Spec-0032/T5：挂起即按 gate 经 blocknote.build 贴**一条**结构化签名评论（统一所有闸——取代今天
        只有 merge 闸单独贴 CONFLICT_COMMENT、其余闸只甩标签的半张嘴体验）；blocker 由调用方按闸传入
        （rfc/code 传 reviewer 反馈原文、merge 传冲突提示、*-unparseable 留空）。贴完取当前最新评论
        createdAt 经 set_block_watermark 落盘作「解挂水位线」——含本实例刚贴的挂起评论，故解挂判定
        （只认水位线之后的无签名人类评论）天然不会读到自己这条评论自触发。
        """
        pr_number = record.pr_number
        # 先贴结构化挂起评论（沿用 merge 闸既有的「先评论、后 _block」次序）。盖本实例签名 →
        # 解挂读侧的 new_human_comments 会按签名把它滤掉，不会自触发。
        body = blocknote.build(
            gate=gate, tried=_TRIED_BY_GATE.get(gate, _DEFAULT_TRIED), blocker=blocker
        )
        identity.post_signed_comment(pr_number=pr_number, body=body, agent_id=self._agent_id)
        # issue #47：GitHub 标签副作用先行、state 落盘后行。add_label 失败（gh 瞬时错误 / 标签缺失）
        # 时异常上抛，但此时 state 尚未变 blocked——下一轮 poll 仍把它当 open，自然重试整个 _block，
        # 避免「state=blocked 但 PR 无 needs-human 标签」的双源发散（release 预检与人的可观测性都依赖标签）。
        github.add_label(pr_number=pr_number, name=BLOCKED_LABEL)
        self._state.update_status(issue_number=record.issue_number, status=STATUS_BLOCKED)
        # Spec-0031/T2：记录是哪道闸挂的（次序：add_label → update_status → set_block_gate）。merge 闸
        # 据此在人解挂时判 armed；gate=="merge" 的 _block 为将来人解挂铺好 armed 入口。
        self._state.set_block_gate(issue_number=record.issue_number, gate=gate)
        # Spec-0032/T5：落「解挂水位线」——挂起时刻 PR 上最新评论 createdAt（含上面刚贴的挂起评论）。
        self._state.set_block_watermark(
            issue_number=record.issue_number, watermark=self._latest_created_at(pr_number=pr_number)
        )
        return {"pr_number": pr_number, "reason": "blocked", "gate": gate}

    def _hold_merge_freeze(self, *, record: RunRecord) -> dict:
        """Spec-0041/T1（决策 A）：hold-merge PASS 后夯住待合并——成功文案 + 置 BLOCKED + 标签 + 水位线。

        复用 _block 的冻结骨架（同次序：先贴评论 → add_label → update_status(BLOCKED) →
        set_block_gate → set_block_watermark），但两处不同：
        1. 贴 blocknote.build_hold_merge_pass() 的「✅ 已通过评审，待你合并」成功文案（**非** _block 的
           「🤖 卡住了」失败模板），经 identity.post_signed_comment 盖签名（→ 解挂读侧 new_human_comments
           按签名滤掉它、不自触发）。
        2. gate 设自描述的 "merge-hold"（非复用 "code"——见 spec 决策 B/备选 4）：运维看 block_gate
           即知「这条 blocked 不是评审失败、而是通过后待合并」，且 _unblock_with_comment 据此走
           iterate(reason="human")。set_block_watermark 落挂起时刻最新评论 createdAt（含刚贴的成功
           评论），供解挂环只认水位线之后的新人类评论。

        STATUS_BLOCKED 不在 _OPEN_STATUSES → 下一轮 poll 自动跳过、不再重审（反震荡的根）。
        """
        pr_number = record.pr_number
        # 贴成功文案（沿用 _block 的「先评论、后置状态」次序）。盖本实例签名 → 解挂读侧滤掉、不自触发。
        body = blocknote.build_hold_merge_pass()
        identity.post_signed_comment(pr_number=pr_number, body=body, agent_id=self._agent_id)
        # 副作用先行、state 落盘后行（与 _block 同理，issue #47）：add_label 失败则 state 未变 blocked，
        # 下一轮仍当 open 自然重试，避免「state=blocked 但 PR 无标签」的双源发散。
        github.add_label(pr_number=pr_number, name=BLOCKED_LABEL)
        self._state.update_status(issue_number=record.issue_number, status=STATUS_BLOCKED)
        self._state.set_block_gate(issue_number=record.issue_number, gate="merge-hold")
        self._state.set_block_watermark(
            issue_number=record.issue_number, watermark=self._latest_created_at(pr_number=pr_number)
        )
        return {"pr_number": pr_number, "reason": "hold-merge", "gate": "merge-hold"}

    def _latest_created_at(self, *, pr_number: int) -> str:
        """Spec-0032/T5：取 PR 当前最新评论的 createdAt（无评论返回 ""）——供 _block 落水位线。

        createdAt 是 GitHub 权威时序源（ISO 8601，字典序即时序，无需读系统时钟、hermetic 可测）。
        """
        return max(
            (comment.created_at for comment in github.list_comments(pr_number=pr_number)),
            default="",
        )

    def _make_resolver(self):
        """Spec-0028/T3：work_dir + base + backend 三者齐备时构造 agent 语义解冲突 resolve，否则 None。

        门控：缺 work_dir / base / backend 任一即 None（解冲突要真起一个 coding 后端）。resolve 为
        None 时 _process_coding 的冲突分支回落「留言 + needs-human」。
        """
        if self._work_dir is None or self._base is None or self._backend is None:
            return None
        return conflict.make_resolver(
            work_dir=self._work_dir,
            base=self._base,
            backend=self._backend,
            agent_id=self._agent_id,
        )

    def _make_diagnoser(self):
        """Spec-0034/T3：work_dir + base 齐备时构造 worktree-free 冲突诊断器，否则 None（退回静态文案）。

        门控：缺 work_dir / base 任一即 None；不要求 backend——诊断只读冲突（merge-tree + git show），
        不起 coding 后端。供 merge 闸 _conflict_blocker 复用（拉式同步后扇出已撤，诊断器只服务挂起评论）。
        """
        if self._work_dir is None or self._base is None:
            return None
        return conflictdiag.make_diagnoser(work_dir=self._work_dir, base=self._base)

    def _conflict_blocker(self, *, pr_number: int) -> str:
        """Spec-0034/T3：merge 闸 _block 统一取 blocker——有诊断器则带诊断，否则退回静态文案。

        有诊断器（work_dir+base 齐备）→ diagnose(pr_number) 产出带冲突文件清单 + 关键 hunk 摘要的
        「卡在哪」段（诊断为空时 conflictdiag.format_blocker 已内部退回 conflictdiag.CONFLICT_COMMENT）；
        无诊断器（老夹具/缺 work_dir）→ 直接退回 conflictdiag.CONFLICT_COMMENT。
        """
        diagnose = self._make_diagnoser()
        if diagnose is None:
            return conflictdiag.CONFLICT_COMMENT
        return diagnose(pr_number=pr_number)

    def _has_open_pr(self) -> bool:
        """是否还有 rfc-review/pr-open/iterating 的 run（watch 循环的退出条件）。"""
        return any(r.status in _OPEN_STATUSES for r in self._state.all_runs())
