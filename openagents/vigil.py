"""RFC-0004: openagents vigil —— 守夜人模式（自主 issue→PR 全流程循环）。

Vigil 是一个**薄调度循环**，本身不实现「解 issue」或「轮询 PR」——这些分别由
Orchestrator 与 Messages 提供（决策 1）。它唯一新增的业务能力是**issue 发现**
（决策 2/3）：去 GitHub 列出带约定标签、且尚未处理过的 open issue，逐个派单
Orchestrator.start_rfc 起草 RFC、开 draft PR（决策 5 串行、决策 8 错误隔离），
再调 Messages.poll 推进已开 PR。RFC-0005 把一站式 solve 拆成原子步骤后，发现段只
负责「起草 RFC」这一步，后续 refine→implement→iterate 整条 RFC-first 循环由守候段
Messages.poll 按 rfc-approved 标签 / 评论 / CI 自动分流驱动——vigil 无需感知这些步骤。
每轮循环都从 GitHub + 本地 State 重新推导「现在该做什么」，不持有不可重建的内存
状态——这是 issue #9「代码即 checkpoint、agent 一次性」的落点：vigil 被 kill/崩溃
后重跑即从断点继续（去重三道闸据 State+远端重新推导，RFC-0003 决策 7/8）。

依赖注入：orchestrator（Orchestrator）、messages（Messages）、state（State）、
work_dir（repo 根，供发现段去重闸 (c) 的 git ls-remote）。time.sleep 可在测试中 mock。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from openagents import github, identity
from openagents.github import GithubError
from openagents.hold import NONE as NO_HOLD
from openagents.hold import Hold
from openagents.messages import Messages
from openagents.orchestrator import Orchestrator, OrchestratorError
from openagents.skip import NONE as NO_SKIP
from openagents.skip import Skip
from openagents.state import STATUS_SOLVING

# 与 orchestrator 一致的分支命名：单 issue → 单分支。
_BRANCH_PREFIX = "openagents/issue-"

# Spec-0039/T2 + Spec-0049/T3：认领过期阈值（秒）——带认领标签但远端仍无分支、且**最近认领便签**
# 年龄超过它 → 判「僵尸认领」允许回收（视同 fresh 重新认领）。默认 1 小时：同后端崩溃已由本地
# begin_run + resume 兜住，过期回收只针对跨后端的死后端，误回收（把仍在慢速起草的活后端判过期）
# 代价只是重复派单一次，故取「足够大于最坏起草时长」的保守值。Spec-0049 把数据源从「标签时间线
# labeled 事件年龄」迁到「署名认领便签的 created_at 年龄」（同 now-created_at 语义、跨后端共享时钟）。
# 模块级常量、单处可配（理念 1，见 spec Unresolved）。
CLAIM_EXPIRY_SECONDS = 3600


class Vigil:
    """RFC-0004：守夜人——主动发现新 issue 并派单，同时守候已开 PR。"""

    def __init__(
        self,
        *,
        orchestrator: Orchestrator,
        messages: Messages,
        state,
        work_dir: Path,
        agent_id: str = "",
    ) -> None:
        self._orchestrator = orchestrator
        self._messages = messages
        self._state = state
        self._work_dir = Path(work_dir)
        # Spec-0049/T3：本实例身份——发现段认领闸据此判「最近认领便签是不是别人的」。默认 ""
        # 使既有 Vigil(...) 构造（未传 agent_id 的测试夹具）零改动：空 id 永不等于任一真实 owner，
        # 故任何他人活认领都被当「别人的」保守跳过（安全侧），生产由 cli 注入真实 id 精确判归属。
        self._agent_id = agent_id

    def run(
        self,
        *,
        interval: int,
        labels: list[str],
        base: str,
        once: bool,
        hold: Hold = NO_HOLD,
        skip: Skip = NO_SKIP,
    ) -> None:
        """守夜人主循环：每轮先发现+派单，再 poll 已开 PR；持续到 Ctrl-C（决策 6）。

        Spec-0023/T2：base 由调用方（CLI）传入，默认值随 CLI/orchestrator 改回 main
        ——派单起草的 spec/改动以 main 为基线/PR base，守候段 poll 的 reviewer 闸驱动其
        自动合回 main。本方法签名不变，仅默认值随上游 CLI 调整。

        Spec-0020/T3：新增关键字参数 hold（Hold），默认取「全不停」实例以保持现有调用与
        行为逐字节不变；vigil 自身不消费 hold，仅把人的意图逐轮透传给 messages.poll，由
        真正分流的 messages 层在 spec / merge 闸据 hold 决定停或照常（vigil 仍是薄调度循环）。

        Spec-0054/T2：新增关键字参数 skip（Skip），默认「全不关」实例以保持现有调用与行为
        逐字节不变（零回归）。skip 与 hold 并列逐轮透传：发现段本层消费 skip.at_issue（跳过
        precheck_issue 直接放行派单），守候段把 skip 下传 messages.poll，由 messages 层在
        spec / code / ci / evidence 四道闸把 skip 中命中的闸当 PASS 直接放行。

        once=True 跑一轮即返回（适配 cron/CI 周期触发）；否则 sleep(interval) 续循环。
        KeyboardInterrupt 是人类的停止信号 → 干净退出，不抛出（决策 8）。

        RFC-0010 决策 5/6：长驻（once=False）模式下，单轮 `_run_one_round` 失败记日志并
        进下一轮，不掀掉整个守夜进程——单点偶发（如 gh 504 穿透重试、git/orchestrator 异常）
        不该让无人值守的守夜整夜阵亡。once 模式（cron/CI 周期触发）则不吞异常、照旧上抛，
        让调度器从非零退出码看见真实失败。`except Exception` 天然放行 KeyboardInterrupt
        （非 Exception 子类），Ctrl-C 仍走既有干净退出分支。
        """
        try:
            while True:
                try:
                    self._run_one_round(labels=labels, base=base, hold=hold, skip=skip)
                except Exception as exc:  # noqa: BLE001 —— 决策 6：守夜第一要务是「活着进下一轮」
                    if once:
                        raise  # 决策 5：once 模式不吞，让 cron/CI 得到非零退出
                    self._log(message=f"✗ 本轮守夜失败，跳过、{interval}s 后再扫一轮：{exc}")
                if once:
                    return
                self._log(message=f"… 守夜中，{interval}s 后再扫一轮（Ctrl-C 停止）")
                time.sleep(interval)
        except KeyboardInterrupt:
            self._log(message="✓ 守夜人已停止（Ctrl-C）")
            return

    def _run_one_round(
        self, *, labels: list[str], base: str, hold: Hold, skip: Skip = NO_SKIP
    ) -> None:
        """RFC-0010 T2：单轮——发现+派单，再 poll 已开 PR。

        从既有 run 循环体中机械抽取的私有方法，行为不变；抽出后供长驻模式 try/except
        包裹（单轮失败兜底）与 once 模式直接调用（异常上抛）复用。

        Spec-0020/T3：把本次运行的 hold 透传给 messages.poll，让分流落到真正的闸门处。
        Spec-0054/T2：skip 一并透传——发现段 discover_and_dispatch 消费 skip.at_issue，
        守候段 messages.poll 消费 spec / code / ci / evidence 四道闸的 skip 短路。
        """
        self.discover_and_dispatch(labels=labels, base=base, skip=skip)
        # Spec-0058/T5：发现段之后、守候段之前调一次跨 issue 调度保鲜——每轮可能新增 issue / 上游可能
        # 刚合并，保鲜一次即让标签真值（blocked-by / sched-ready）追上现实、自动剪边解封。best-effort：
        # 保鲜失败只记日志、不掀翻整轮（含 once 模式也不上抛），故守候段（poll）永远照常推进。
        try:
            self._orchestrator.schedule()
        except Exception as exc:  # noqa: BLE001 — 保鲜是旁路优化，失败绝不阻断本轮守候段
            self._log(message=f"⚠ 跨 issue 调度保鲜失败（已忽略，标签下轮再追）：{exc}")
        self._messages.poll(hold=hold, skip=skip)

    def discover_and_dispatch(
        self, *, labels: list[str], base: str, skip: Skip = NO_SKIP
    ) -> list[int]:
        """发现段：列出标签门控的 open issue，按本地 State 三路分流派单（RFC-0004/0007）。

        RFC-0007 决策 1/3：用 `_dispatch_kind` 取代原 `_is_new`，对每个 issue 区分：
          - "fresh"  → start_rfc(resume=False)：无 run 记录且远端无分支，建全新 worktree。
          - "resume" → start_rfc(resume=True) ：solving/pr=0 的孤儿 run，复用残留 worktree 续跑。
          - None     → 跳过：已开 PR / rfc-review / pr-open / iterating / done / closed，交 poll 推进。
        RFC-0005：派单只调 start_rfc（开 RFC draft PR）；后续 refine/implement/iterate
        由守候段 Messages.poll 驱动。返回本轮实际派单（fresh+resume）的 issue 编号列表。
        """
        dispatched: list[int] = []
        for issue in github.list_issues(labels=labels):
            kind = self._dispatch_kind(issue=issue)
            if kind is None:
                continue
            resume = kind == "resume"
            verb = "恢复孤儿 run" if resume else "派单起草 RFC"
            try:
                # Spec-0043/T3：fresh issue 派单起草前先自检修法方向是否自洽；命中冲突则冻结
                # （precheck_issue 已打 needs-human + 贴对齐评论），本轮跳过、不派单。只对 fresh
                # 判读——resume 是已 precheck 过的孤儿 run，续跑即可、不重判。precheck 的异常纳入
                # 本 per-issue except 隔离（判读/贴评论失败只跳过该 issue、下轮重试，不拖垮整轮）。
                # Spec-0054/T2：issue 自检闸 skip——skip.at_issue 为真时把该闸当 PASS 直接
                # 放行，不调 precheck_issue（不判读、不冻结、不贴对齐评论），照常派单起草。
                # 仍只对 fresh 判读（resume 是已 precheck 过的孤儿 run）。
                if (
                    not resume
                    and not skip.at_issue
                    and self._orchestrator.precheck_issue(issue_number=issue.number)
                ):
                    self._log(
                        message=f"⏸ issue #{issue.number}：检出修法方向冲突，"
                        "已打 needs-human 待对齐，跳过起草"
                    )
                    continue
                self._log(message=f"▶ issue #{issue.number}：{issue.title} → {verb}")
                self._orchestrator.start_rfc(issue_number=issue.number, base=base, resume=resume)
                dispatched.append(issue.number)
            except (OrchestratorError, GithubError) as exc:
                # 决策 8：单个 issue 失败记录并跳过，不拖垮整轮守候。
                self._log(message=f"✗ issue #{issue.number} {verb}失败，跳过：{exc}")
        return dispatched

    def _dispatch_kind(self, *, issue: github.Issue) -> str | None:
        """RFC-0007 决策 1/3/6 + Spec-0039/T2 + Spec-0049/T3：据本地 State + 远端分支 + 认领便签归属归类。

        返回 "fresh" | "resume" | None，无 run 记录时按三道去重闸依次判定：
          - 闸 2——远端已有分支 → None（在途，交 poll；resume 路径不受此闸约束）。
          - 闸 3（Spec-0039 引入，Spec-0049 归属化）——issue 带 DISPATCH_LABEL 认领标签（便宜的
            粗信号，已随 issue 拉下）才读**署名认领便签**判归属：最近便签是**他人**且未过期 → None
            （别的后端在起草，跳过）；已过期（僵尸认领，便签龄 > CLAIM_EXPIRY_SECONDS）/ 无有效便签
            / 是**自己**的残留 → 落到 "fresh" 回收重新认领。
          - 三闸都不命中 → "fresh"。
        solving 且 pr_number==0 → "resume"（崩在起草/push/建 PR 段的孤儿 run）；该分支先于
        record is None 判定，故 resume 语义完全不受认领闸影响（决策 6(c)）。
        """
        record = self._state.find_by_issue(issue_number=issue.number)
        if record is None:
            if self._remote_branch_exists(branch=f"{_BRANCH_PREFIX}{issue.number}"):
                return None
            if github.BLOCKED_LABEL in issue.labels:
                # Spec-0043/T3：已因修法冲突冻结、待人对齐——不再重跑非确定判读（防 issue 级复审
                # 震荡）。needs-human 是持久冻结信号，人摘掉标签后该 issue 才重新成 fresh 触发重判。
                # 放在 record is None 分支内是安全的：有 run 记录（已开 PR）的 issue 的 needs-human
                # 由 messages.poll 处理，_dispatch_kind 对它们本就返回 None。
                return None
            if github.DISPATCH_LABEL in issue.labels and not self._claim_reclaimable(issue=issue):
                # 已被**别的**后端有效认领（最近便签他人且未过期）→ 跳过；他人已过期 / 无便签 /
                # 自己的残留 → _claim_reclaimable 判 True，落下去视同 fresh 回收重认领。
                return None
            return "fresh"
        if record.status == STATUS_SOLVING and record.pr_number == 0:
            return "resume"
        return None

    def _claim_reclaimable(self, *, issue: github.Issue) -> bool:
        """Spec-0049/T3：带认领标签的 issue 是否**可被本后端回收重认领**（读署名认领便签判归属+年龄）。

        仅在「带认领标签且远端无分支」（_dispatch_kind 上一闸已确认）这一罕见路径调用（与今日
        过期回收同频，不拖慢常态扫描）。语义：
          - 无有效认领便签 → True（可认领：只有粗标签、没归属凭证，落 fresh）。
          - 最近便签是**自己**的残留 → True（重认领：可能是上轮退让 / begin_run 失败的残留）。
          - 最近便签是**他人**且已过期（僵尸，龄 > CLAIM_EXPIRY_SECONDS）→ True（回收死后端占坑）。
          - 最近便签是**他人**且未过期 → False（他人在起草，跳过让路）。

        读评论失败（GithubError，权限/限流/gh 抖动）**不上抛**、保守判 False（不可回收 → 跳过）：
        本方法经 _dispatch_kind 在 discover_and_dispatch 的 per-issue try/except **之外**被调用，
        在此抛错会掀翻整轮发现、饿死其后所有 issue 与本轮 PR 轮询（破坏决策 8）。保守取「他人活认领」
        侧——宁可占坑多留一轮，也不误回收把活后端的认领抢掉（重复派单），更不阵亡整轮。
        """
        try:
            comments = github.list_issue_comments(number=issue.number)
        except GithubError as exc:
            self._log(message=f"… issue #{issue.number} 认领便签查询失败，保守跳过：{exc}")
            return False
        claim = identity.latest_claim(comments=comments)
        if claim is None:
            return True  # 无有效认领便签 → 可认领
        owner, age_seconds = claim
        if owner == self._agent_id:
            return True  # 自己的残留 → 重认领
        return self._claim_expired(age_seconds=age_seconds)  # 他人：仅当已过期才回收

    def _claim_expired(self, *, age_seconds: float) -> bool:
        """Spec-0049/T3：认领便签年龄是否超过过期阈值（僵尸认领判定，数据源 = 便签 created_at 龄）。

        纯判定（阈值比较），数据源由 _claim_reclaimable 从 identity.latest_claim 取好后传入——
        由「标签时间线 labeled 事件龄」（Spec-0039）迁到「署名认领便签 created_at 龄」（Spec-0049）。
        """
        return age_seconds > CLAIM_EXPIRY_SECONDS

    def _remote_branch_exists(self, *, branch: str) -> bool:
        """决策 3(c)：远端是否已存在该 issue 分支（State 丢失时的兜底）。"""
        result = subprocess.run(
            ["git", "-C", str(self._work_dir), "ls-remote", "--heads", "origin", branch],
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())

    def _log(self, *, message: str) -> None:
        """守夜进度打到 stderr，保证无人值守时仍有可观测的运行轨迹。"""
        print(message, file=sys.stderr, flush=True)
