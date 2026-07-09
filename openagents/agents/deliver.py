"""# Spec-0060/T4: agents.deliver —— 版本控制提交/推送/解冲突 → 结构化交付报告的提示词（零逻辑）。

吸收旧 orchestrator._GIT_DELIVERY_PROTOCOL + conflict/conflictdiag 的判断部分：交付/冲突自愈是
「需要判断」的操作（读冲突、判双方意图、跑自测），故下放 agent；harness 只留 head 前移硬闸
（gates.assert_head_advanced 读 base_sha 比对）兜底 agent 自述、防 #140 空转/撒谎。
"""

from string import Template

PROMPT = Template(
    """你是交付 agent。把本工作分支 $branch（对应 PR #$pr_number）的改动真正推上远端，直到成果落到 PR head：
1. 先记下交付前的本地基点：base_sha = 当前 `HEAD` 的 SHA（用于向 harness 自证「head 确实前移了」）；
2. `git add -A && git commit -m "<语义化信息>"`（不同阶段用不同措辞，别堆固定消息）；
3. 先记下远端基点 `BASE=$$(git rev-parse origin/$branch)`，再 `git fetch origin $branch`（BASE 必须在 fetch 之前求值，否则 fetch 刷新跟踪 ref 会让 lease 保护退化成等价裸 force）；
4. 与远端分叉就 `git rebase origin/$branch`：有冲突自己读 `<<<<<<<` 标记按双方意图语义解决、`git add -A && git rebase --continue`，直到走完（不许 abort、不甩 needs-human）；
5. `git push --force-with-lease=$branch:$$BASE origin $branch`；禁止裸 `git push --force`，`--force-with-lease` 仅限本工作分支 $branch，绝不作用于 main/受保护分支/他人分支。
完成判据：`git rev-parse origin/$branch` == 你的 `HEAD`，不相等就继续处理直到相等。

最后只输出一行 JSON（base_sha 填第 1 步记下的交付前 SHA，head_sha 填交付后当前 HEAD 的 SHA）：
{"delivered": true 或 false, "base_sha": "<交付前 HEAD SHA>", "head_sha": "<交付后 HEAD SHA>", "summary": "<交付情况一句话，含是否 rebase 解冲突>"}
"""
)

OUTPUT_SCHEMA = {"delivered": bool, "base_sha": str, "head_sha": str, "summary": str}
