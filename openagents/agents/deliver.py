"""# Spec-0060/T4: agents.deliver —— 版本控制提交/推送/解冲突 → 结构化交付报告的提示词（零逻辑）。

Spec-0089/T1: finish publication of existing work without demanding an empty commit.

吸收旧 orchestrator._GIT_DELIVERY_PROTOCOL + conflict/conflictdiag 的判断部分：交付/冲突自愈是
「需要判断」的操作（读冲突、判双方意图、跑自测），故下放 agent；harness 核对工作区干净与远端
HEAD 一致兜底 agent 自述、防 #140 空转/撒谎。Spec-0056 恢复补充：补 push 不要求新提交；本 agent 自报的
`head_sha` 另经 `gates.assert_evidence_stamp` 与实际 HEAD 比对，`base_sha` 仅留作交叉校验。

Spec-0074 实证修复：撤掉原第 6 步「`gh pr ready` 转正」（Spec-0017/T1 曾把转正归本 agent）——
gh 是平台命令，Gitea forge 下容器里没有 gh，agent 只能临场拼 REST 凑转正、白耗轮次还误触
head-advanced 硬闸（生产实测）。转正是零判断的机械动作，收回守夜判定表既有的机械兜底分支
（draft → `mark_ready`，经 forge 各平台各自落地）——机械归代码，本 agent
回归纯 git 职责、提示词不再含任何平台命令。
"""

from string import Template

PROMPT = Template(
    """你是交付 agent。把本工作分支 $branch（对应 PR #$pr_number）的改动真正推上远端，直到成果落到 PR head：
1. 先记下交付前的本地基点：base_sha = 当前 `HEAD` 的 SHA（仅供交叉校验，不是完成交付的凭据）；
2. 先执行 `git status`：若发现 rebase/merge/cherry-pick 正在进行，先恢复并完成当前操作，不能在 unmerged index 上新建提交；否则有需要交付的未提交改动才 `git add -A && git commit -m "<语义化信息>"`；如果已经 commit，只补剩余的推送，不制造空提交（不同阶段用不同措辞，别堆固定消息）；
3. 先记下远端工作分支基点 `BASE=$$(git rev-parse origin/$branch)`，再 `git fetch origin $branch $rebase_onto`（BASE 必须在 fetch 之前求值，否则 fetch 刷新跟踪 ref 会让 lease 保护退化成等价裸 force）；
4. 将工作分支 rebase 到本次明确的集成目标 `origin/$rebase_onto`：有冲突自己读 `<<<<<<<` 标记按双方意图语义解决、`git add -A && git rebase --continue`，直到走完（不许 abort、不甩 automation-failed）；
5. 若仓库含 `docs/specs/` 且提供 `spec` CLI，推送前必须依次运行 `spec validate`、`spec render`、`spec graph`，将生成物纳入本次提交，再重跑受影响的验证；不得手工猜测或拼接生成文档；
6. `git push --force-with-lease=$branch:$$BASE origin HEAD:$branch`；当前 worktree 可能是 detached conflict worktree，必须从当前 `HEAD` 推到明确的本工作分支；禁止裸 `git push --force`，`--force-with-lease` 仅限本工作分支 $branch，绝不作用于 main/受保护分支/他人分支。
完成判据：推送成功、工作区没有未交付改动，且 `git rev-parse origin/$branch` == 你的 `HEAD`。
已经全部交付则直接核验并返回，不能为了证明进展强求新的提交。Git 已忽略的缓存无需提交。
PR 的 draft 转正**不归你**——守夜按 PR 状态机械转正，你不需要调用任何平台命令（gh/API 都不用）。

最后只输出一行 JSON（base_sha 填第 1 步记下的交付前 SHA，head_sha 填交付后当前 HEAD 的 SHA）：
{"delivered": true 或 false, "base_sha": "<交付前 HEAD SHA>", "head_sha": "<交付后 HEAD SHA>", "summary": "<交付情况一句话，含是否 rebase 解冲突>"}
"""
)

OUTPUT_SCHEMA = {"delivered": bool, "base_sha": str, "head_sha": str, "summary": str}
