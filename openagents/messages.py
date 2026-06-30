"""RFC-0001 T5 + RFC-0005 + RFC-0012: PR 消息机制 + CI 监控，按**阶段**路由 GitHub 事件。

poll 对每个 open 状态的 run 做一次扫描，先判 merge/close，再按 run 所处阶段路由
（RFC-0005 决策 5）。RFC-0012 把两处「等人」的判定换成「调 reviewer 闸 + 自动推进」，
让人的触点收敛到「提 issue」与「release」（Spec-0023：promote 改名 release）：

  1. github.is_merged：已合并 → State 置 done，跳过（决策 8）+ 合并后扇出 rebase（RFC-0009）。
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
        - 全票 PASS → github.merge_pr（合入 test）→ DONE → 扇出 rebase 其余 PR。
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

from openagents import (
    blocknote,
    conflict,
    conflictdiag,
    github,
    identity,
    indexheal,
    rebase,
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

# Spec-0032/T5: gate → 挂起评论「我试过什么」段的人类可读文案。messages 据持久化 gate 选一句
# 传给 blocknote.build（展示文案，不参与路由判定）；未知 gate 回落到通用句、绝不抛。
_TRIED_BY_GATE = {
    "rfc": "已按 reviewer 反馈多轮精炼 RFC，仍未通过评审",
    "code": "已按 reviewer 反馈多轮迭代代码，仍未通过评审",
    "rfc-unparseable": "多次重评仍无法解析 reviewer 对 RFC 的裁决",
    "code-unparseable": "多次重评仍无法解析 reviewer 对代码的裁决",
    "merge": "已尝试自动解冲突，但仍与目标分支存在冲突",
}
_DEFAULT_TRIED = "已反复尝试，仍未通过"

# Spec-0035/T5：merge 闸 armed 解冲突跑完后回应人类的「结论文案」（response 内容，非展示模板——
# 展示模板〔引用块 + 回应段布局〕在 replynote.build 里）。conflict.resolve 返回 bool 不带 summary，
# 故 merge 闸的回应正文由 messages 据 resolve 结果选一句结论；rfc/code 闸的回应正文则取 agent summary。
_RESOLVE_REPLY_SUCCESS = "已按你的指导解冲突并 push，PR 将重新跑 CI。"
_RESOLVE_REPLY_UNRESOLVED = "本轮未能自动解决冲突，已重新挂起，等待你进一步处理。"


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
        # RFC-0011 决策 7：本实例身份，由 CLI 接线处解析后注入；poll 合并分支时透传给
        # rebase.rebase_open_prs（冲突留言据此盖章、保持 rebase 无状态）。
        self._agent_id = agent_id
        # issue #48：work_dir + base 用于构造索引冲突自愈 heal（同步 base 后自动重渲 OVERVIEW）。
        # 二者缺一则不注入 heal——退回既有「冲突留言等人」行为（向后兼容老调用方/测试夹具）。
        self._work_dir = work_dir
        self._base = base
        # Spec-0028/T3：backend 用于构造 agent 语义解冲突 resolve（与 _make_heal 同款门控：
        # work_dir + base + backend 齐备才构造，缺一则不注入——退回 heal→人工 的既有降级，
        # 向后兼容老调用方/测试夹具）。只在自动 poll 扇出启用，手动 sync-prs 不注入（不偷烧 token）。
        self._backend = backend

    def poll(self, *, hold: Hold = NO_HOLD) -> list[dict]:
        """RFC-0001 T5：扫描所有 open 状态 run，按 merge → 阶段 路由。

        返回本轮事件列表，每个事件含 pr_number 与 reason（reason ∈ {"merged", "closed",
        "approved", "rfc-pass", "refine", "ci", "review", "review-invalid", "blocked",
        "resumed", "resolved", "unmergeable", "merge-retry", "hold-spec", "hold-merge"}），
        便于日志与测试断言。Spec-0021/T2：新增 "review-invalid"（评审无效本轮等下一轮重评，不吃
        round、不空转）。Spec-0031/T2：新增 "merge-retry"（armed 模式本轮派 agent 解冲突未成、
        未达上限，保持 pr-open 等下一轮再试，不重挂）。

        Spec-0020/T3：新增关键字参数 hold（Hold），默认「全不停」以保持现有调用与行为；
        poll 内部把 hold 下传给两道闸的私有处理函数，spec / merge 闸据 hold 选择「停在闸门
        等人」或现状自动推进分支。默认 Hold 下走原代码、行为逐字节不变（零回归）。
        """
        events: list[dict] = []
        for record in self._state.all_runs():
            # issue #49：blocked 也纳入扫描（用于解挂/reconcile），其余非 open 状态照常跳过。
            if record.status not in _OPEN_STATUSES and record.status != STATUS_BLOCKED:
                continue
            # Spec-0022/T2：单 record 错误隔离（沿用 RFC-0004 决策 8 / rebase_open_prs 风格）——
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
            # RFC-0009 决策 1/3：合并即信号——同一 poll 轮内扇出，把最新 base 并入其余
            # open PR（排除刚合并的这个），触发它们 CI 重跑；冲突的 PR 先试索引自愈（issue #48），
            # 自愈不了再由 rebase 层留言。
            # Spec-0028/T3：分层降级 heal → resolve → 人工——resolve 派 coding agent 语义解
            # indexheal 不适用的真冲突（只在自动 poll 扇出启用，故在此注入；手动 sync-prs 不注入）。
            # Spec-0034/T3：补传 diagnose 使扇出冲突评论带诊断（冲突文件清单 + 关键 hunk 摘要），
            # 并触发 T2 的重发收敛（对已 needs-human 的 PR 跳过留言）。
            synced = rebase.rebase_open_prs(
                merged_pr_number=pr_number,
                agent_id=self._agent_id,
                heal=self._make_heal(),
                resolve=self._make_resolver(),
                diagnose=self._make_diagnoser(),
            )
            return {"pr_number": pr_number, "reason": "merged", "synced": synced}

        # 1b. RFC-0006：人主动关闭（未合并）也是终止信号 → 置 closed 并跳过。merged 优先于 closed。
        if github.is_closed(pr_number=pr_number):
            self._state.update_status(issue_number=record.issue_number, status=STATUS_CLOSED)
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
        """Spec-0032/T5 + Spec-0035/T5：回评论解挂——摘标签 + 清回合预算 + 按 block_gate 喂评论给对应闸。

        路由（按持久化 block_gate）：
        - rfc/rfc-unparseable → refine_rfc(detail, announce=False)（内部置 rfc-review）+ 清残留
          block_gate + **引用原评论贴回 agent 回应**（Spec-0035/T5：announce=False 抑制泛化广播，
          换成一条针对性回应）。
        - code/code-unparseable → iterate(reason="human", detail)（内部置 iterating）+ 清残留
          block_gate + **引用原评论贴回 agent 回应**。
        - merge → 不直接喂解冲突器，按 armed 语义恢复 pr-open、**保留** block_gate="merge" 作标记
          （reset_rounds 已清 merge_attempts 给满预算），并 set_unblock_detail 把评论正文存进 state
          供下一轮 armed 解冲突当 guidance + 回应时引用（Spec-0035/T5）。**本轮不回应**（动作尚未发生，
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
        elif gate in ("code", "code-unparseable"):
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
        """Spec-0035/T5：引用触发解挂的那条人类评论，盖签名贴回一条 agent 回应（恰一条）。

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
            # Spec-0020/T3：merge 闸 hold——CI / reviewer 评审照跑，但 reviewer PASS 后不自动
            # merge_pr，停在「待人 merge」（PR 保持 open、本轮不动状态），把最后一下留给人。
            # 人手动 merge 后，下一轮 poll 的 is_merged 分支照常 reconcile 成 done（既有逻辑）。
            if hold.at_merge:
                return {"pr_number": pr_number, "reason": "hold-merge"}
            github.merge_pr(pr_number=pr_number)
            self._state.update_status(issue_number=record.issue_number, status=STATUS_DONE)
            # RFC-0017：合进 test 后显式关 issue（与上方已合并分支同理，幂等容错）。
            github.close_issue(number=record.issue_number)
            # Spec-0034/T3：合并扇出补传 diagnose（带诊断 + 触发 T2 重发收敛），与上方已合并分支同款。
            synced = rebase.rebase_open_prs(
                merged_pr_number=pr_number,
                agent_id=self._agent_id,
                diagnose=self._make_diagnoser(),
            )
            return {"pr_number": pr_number, "reason": "merged", "synced": synced}
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

    def _process_armed_conflict(self, *, record: RunRecord) -> dict:
        """Spec-0031/T2 + Spec-0035/T5：armed 模式下派 agent 解冲突的有界重试 + 引用原评论贴回结论。

        每轮 poll 进来一次（block_gate=="merge" 且回到 pr-open）：
        - resolve 成功 → 清 armed（block_gate="" + reset 预算）、返回 "resolved"，下一轮 CI 因
          synchronize 重排自然推进。
        - resolve is None（无 backend，重试无意义）→ 直接回落人工（_block），不空转重试。
        - resolve 失败 → merge_attempts +1：未达 MAX_MERGE_ATTEMPTS 返回 "merge-retry"、保持
          pr-open、**不重挂**（跨轮有界重试，给 agent「若干次」真正动手的机会）；达上限才 _block
          重新挂起等人（block_gate 再次置 "merge"，下次人解挂可再 arm）。

        Spec-0035/T5：record.unblock_detail（人解挂时存的评论正文）非空时——① 当作 guidance 透传给
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
        # 1. 解决了：清 armed 标记 + 重置预算；detail 非空则引用原评论贴回成功结论并清 detail。
        if resolve is not None and resolve(pr_number=pr_number, guidance=detail):
            self._state.set_block_gate(issue_number=issue_number, gate="")
            self._state.reset_rounds(issue_number=issue_number)
            self._reply_resolve_outcome(
                pr_number=pr_number,
                issue_number=issue_number,
                detail=detail,
                response=_RESOLVE_REPLY_SUCCESS,
            )
            return {"pr_number": pr_number, "reason": "resolved"}
        # 2. 无 backend（resolve is None）：重试无意义，直接回落人工兜底，不空转。
        if resolve is None:
            # Spec-0032/T5：挂起评论由 _block 经 blocknote 统一出（blocker = 冲突提示文案）。
            # Spec-0034/T3：blocker 改取 _conflict_blocker（有诊断器时带诊断）。
            self._block(
                record=record, gate="merge", blocker=self._conflict_blocker(pr_number=pr_number)
            )
            self._reply_resolve_outcome(
                pr_number=pr_number,
                issue_number=issue_number,
                detail=detail,
                response=_RESOLVE_REPLY_UNRESOLVED,
            )
            return {"pr_number": pr_number, "reason": "unmergeable"}
        # 3. 解不了：计数 +1，未达上限跨轮重试（保持 pr-open、不重挂、不回应、不清 detail）。
        attempts = self._state.increment_merge_attempts(issue_number=issue_number)
        if attempts < MAX_MERGE_ATTEMPTS:
            return {"pr_number": pr_number, "reason": "merge-retry"}
        # 达上限：重新挂起（blocker 带诊断），并引用原评论贴回未解结论 + 清 detail。
        self._block(
            record=record, gate="merge", blocker=self._conflict_blocker(pr_number=pr_number)
        )
        self._reply_resolve_outcome(
            pr_number=pr_number,
            issue_number=issue_number,
            detail=detail,
            response=_RESOLVE_REPLY_UNRESOLVED,
        )
        return {"pr_number": pr_number, "reason": "unmergeable"}

    def _reply_resolve_outcome(
        self, *, pr_number: int, issue_number: int, detail: str, response: str
    ) -> None:
        """Spec-0035/T5：merge 闸 armed 跑完后，detail 非空才引用原评论贴回结论并清空 unblock_detail。

        detail 空（手动摘标签解挂，无评论触发）→ 不回应、不清（逐字节同 Spec-0031 现状，零回归）。
        detail 非空 → 恰贴一条引用原评论的结论回应，随后清空 unblock_detail（避免重复回应 / 陈旧 guidance）。
        """
        if not detail:
            return
        self._post_comment_reply(pr_number=pr_number, original=detail, response=response)
        self._state.set_unblock_detail(issue_number=issue_number, detail="")

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

    def _latest_created_at(self, *, pr_number: int) -> str:
        """Spec-0032/T5：取 PR 当前最新评论的 createdAt（无评论返回 ""）——供 _block 落水位线。

        createdAt 是 GitHub 权威时序源（ISO 8601，字典序即时序，无需读系统时钟、hermetic 可测）。
        """
        return max(
            (comment.created_at for comment in github.list_comments(pr_number=pr_number)),
            default="",
        )

    def _make_heal(self):
        """issue #48：当 work_dir + base 都已注入时构造索引冲突自愈 heal，否则 None（退回留言）。"""
        if self._work_dir is None or self._base is None:
            return None
        return indexheal.make_healer(work_dir=self._work_dir, base=self._base)

    def _make_resolver(self):
        """Spec-0028/T3：work_dir + base + backend 三者齐备时构造 agent 语义解冲突 resolve，否则 None。

        与 _make_heal 同款门控（缺一即 None → 回落 heal→人工 的既有降级）；额外要求 backend
        （解冲突要真起一个 coding 后端）。手动 sync-prs 不注入 backend，故那里 resolve 恒为 None，
        不在人手动命令里偷烧 token（Spec-0028 Drawbacks：token 成本缓解）。
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

        镜像 _make_heal 的门控（缺一即 None）；不要求 backend——诊断只读冲突（merge-tree + git show），
        不起 coding 后端。供合并扇出 rebase_open_prs(diagnose=…) 与 merge 闸 _conflict_blocker 复用。
        手动 sync-prs 路径下 messages 不参与（CLI 直调 rebase 不传 diagnose），故那里恒退回静态文案。
        """
        if self._work_dir is None or self._base is None:
            return None
        return conflictdiag.make_diagnoser(work_dir=self._work_dir, base=self._base)

    def _conflict_blocker(self, *, pr_number: int) -> str:
        """Spec-0034/T3：merge 闸三处 _block 统一取 blocker——有诊断器则带诊断，否则退回静态文案。

        有诊断器（work_dir+base 齐备）→ diagnose(pr_number) 产出带冲突文件清单 + 关键 hunk 摘要的
        「卡在哪」段（诊断为空时 conflictdiag.format_blocker 已内部退回 rebase.CONFLICT_COMMENT）；
        无诊断器（老夹具/缺 work_dir）→ 直接退回 rebase.CONFLICT_COMMENT，逐字节保持既有体验。
        """
        diagnose = self._make_diagnoser()
        if diagnose is None:
            return rebase.CONFLICT_COMMENT
        return diagnose(pr_number=pr_number)

    def _has_open_pr(self) -> bool:
        """是否还有 rfc-review/pr-open/iterating 的 run（watch 循环的退出条件）。"""
        return any(r.status in _OPEN_STATUSES for r in self._state.all_runs())
