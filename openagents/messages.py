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

from openagents import github, identity, indexheal, rebase
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

    def poll(self, *, hold: Hold = NO_HOLD) -> list[dict]:
        """RFC-0001 T5：扫描所有 open 状态 run，按 merge → 阶段 路由。

        返回本轮事件列表，每个事件含 pr_number 与 reason（reason ∈ {"merged", "closed",
        "approved", "rfc-pass", "refine", "ci", "review", "review-invalid", "blocked",
        "resumed", "hold-spec", "hold-merge"}），便于日志与测试断言。Spec-0021/T2：新增
        "review-invalid"（评审无效本轮等下一轮重评，不吃 round、不空转）。

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
            synced = rebase.rebase_open_prs(
                merged_pr_number=pr_number, agent_id=self._agent_id, heal=self._make_heal()
            )
            return {"pr_number": pr_number, "reason": "merged", "synced": synced}

        # 1b. RFC-0006：人主动关闭（未合并）也是终止信号 → 置 closed 并跳过。merged 优先于 closed。
        if github.is_closed(pr_number=pr_number):
            self._state.update_status(issue_number=record.issue_number, status=STATUS_CLOSED)
            return {"pr_number": pr_number, "reason": "closed"}

        # 1c. issue #49：blocked 不再是死胡同。PR 被合/被关已在上面统一 reconcile（人合掉修好的
        # PR → done；人关掉 → closed）。若 PR 仍 open 但人已摘掉 needs-human 标签（语义：「我处理
        # 好了，继续跑」），则解挂——rounds 清零，按是否已过 RFC 闸回到对应阶段重新流转；标签仍在
        # 则保持挂起（返回 None，不动状态）。这消除了「进得去、出不来、release 被永久焊死」。
        if record.status == STATUS_BLOCKED:
            if github.has_label(pr_number=pr_number, name=BLOCKED_LABEL):
                return None
            self._state.reset_rounds(issue_number=record.issue_number)
            resumed = (
                STATUS_PR_OPEN
                if github.has_label(pr_number=pr_number, name=APPROVAL_LABEL)
                else STATUS_RFC_REVIEW
            )
            self._state.update_status(issue_number=record.issue_number, status=resumed)
            return {"pr_number": pr_number, "reason": "resumed"}

        # 2. 按阶段路由（决策 5）。
        if record.status == STATUS_RFC_REVIEW:
            return self._process_rfc_review(record=record, hold=hold)
        return self._process_coding(record=record, hold=hold)

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
                return self._block(record=record, gate="rfc")
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
            # 真冲突：发一次 rebase 提示（复用 rebase.CONFLICT_COMMENT 单一文案来源，避免漂移），
            # 再走既有 _block 置 BLOCKED+needs-human。「恰一条评论」由状态机短路天然保证：blocked
            # 后下一轮 poll 经 _process_run 的 blocked 分支 return None，永不再进 _process_coding。
            identity.post_signed_comment(
                pr_number=pr_number, body=rebase.CONFLICT_COMMENT, agent_id=self._agent_id
            )
            self._block(record=record, gate="merge")
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
            synced = rebase.rebase_open_prs(merged_pr_number=pr_number, agent_id=self._agent_id)
            return {"pr_number": pr_number, "reason": "merged", "synced": synced}
        # Spec-0021/T2：非 PASS 按 decision.actionable 分流（与 spec 闸同构）。
        # 真 REWORK（actionable）：回合 +1，未超 K 则按 reviewer 反馈迭代代码，超 K 则挂起（决策 5，行为不变）。
        if decision.actionable:
            rounds = self._state.increment_rounds(issue_number=record.issue_number)
            if rounds >= MAX_ROUNDS:
                return self._block(record=record, gate="code")
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
            return self._block(record=record, gate=gate)
        return {"pr_number": record.pr_number, "reason": "review-invalid"}

    def _block(self, *, record: RunRecord, gate: str) -> dict:
        """RFC-0012 决策 5：评审超 K 轮 → 置 STATUS_BLOCKED + 打 needs-human + PR 不关。

        STATUS_BLOCKED 不在 _OPEN_STATUSES，下一轮 poll 自动跳过（软挂起）；needs-human
        标签是给人/release 预检看的「求救」信号。PR 保持 open，等人修完再恢复流转。
        """
        pr_number = record.pr_number
        # issue #47：GitHub 副作用先行、state 落盘后行。add_label 失败（gh 瞬时错误 / 标签缺失）
        # 时异常上抛，但此时 state 尚未变 blocked——下一轮 poll 仍把它当 open，自然重试整个 _block，
        # 避免「state=blocked 但 PR 无 needs-human 标签」的双源发散（release 预检与人的可观测性都依赖标签）。
        github.add_label(pr_number=pr_number, name=BLOCKED_LABEL)
        self._state.update_status(issue_number=record.issue_number, status=STATUS_BLOCKED)
        return {"pr_number": pr_number, "reason": "blocked", "gate": gate}

    def _make_heal(self):
        """issue #48：当 work_dir + base 都已注入时构造索引冲突自愈 heal，否则 None（退回留言）。"""
        if self._work_dir is None or self._base is None:
            return None
        return indexheal.make_healer(work_dir=self._work_dir, base=self._base)

    def _has_open_pr(self) -> bool:
        """是否还有 rfc-review/pr-open/iterating 的 run（watch 循环的退出条件）。"""
        return any(r.status in _OPEN_STATUSES for r in self._state.all_runs())
