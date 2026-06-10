# OpenAgents RFCs

本目录包含项目的 RFC（Request for Comments）文档。

## RFC 是什么

RFC 是一种用于记录技术设计决策的文档格式。每个 RFC 描述一个特定的功能、架构变更或技术决策，包括：

- **问题背景**：为什么需要这个变更
- **设计方案**：如何解决问题
- **权衡取舍**：考虑过的替代方案
- **实现状态**：当前进度

## RFC 状态

| 状态 | 说明 |
|------|------|
| `draft` | 草稿，正在讨论 |
| `accepted` | 已接受，待实现 |
| `implementing` | 实现中 |
| `implemented` | 已实现 |
| `superseded` | 被更新的 RFC 取代 |
| `rejected` | 已拒绝 |

## RFC 列表

### 核心架构

| RFC | 标题 | 状态 | 优先级 |
|-----|------|------|--------|
| [RFC-0001](./0001-mvp-issue-to-pr-loop.md) | MVP：单 issue → 单 agent → 真实 PR 的最小自举闭环 | implemented | P0 |
| [RFC-0002](./0002-create-issue.md) | OpenAgents 主动提 issue | implemented | P1 |
| [RFC-0003](./0003-issue-worktree-isolation.md) | issue 求解隔离：每 issue 独立 worktree + 分支基线锁定最新 main | implemented | P1 |
| [RFC-0004](./0004-vigil-autonomous-loop.md) | openagents vigil —— 守夜人模式（自主 issue→PR 全流程循环） | implemented | P1 |
| [RFC-0005](./0005-solve-atomization-rfc-first-loop.md) | solve 原子化拆分 + RFC-first 评审循环 | implemented | P1 |
| [RFC-0006](./0006-closed-pr-issue-termination.md) | 守夜人识别 PR/issue 关闭作为终止信号 | implemented | P1 |
| [RFC-0007](./0007-vigil-solving-resume.md) | 守夜人恢复——激活 solving 为 resume 入口，修复 start_rfc 中途崩溃的孤儿 run | implemented | P1 |
| [RFC-0008](./0008-pr-e2e-signpost.md) | PR 正文「端到端验证」指路牌（从 RFC 自动生成） | implemented | P1 |
| [RFC-0009](./0009-auto-rebase-open-prs-on-merge.md) | 合并后自动 rebase 其他 open PR | implemented | P1 |
| [RFC-0010](./0010-gh-transient-retry-and-vigil-round-guard.md) | gh 瞬时错误重试 + 守夜循环单轮容错 | implemented | P1 |
| [RFC-0011](./0011-agent-identity-comment-signature.md) | 本地 Agent 身份 + 评论签名（区分自评论与真人评论，根治 poll 自循环） | implemented | P1 |
| [RFC-0012](./0012-test-branch-gated-flow.md) | test 分支门控流程——人只在「提 issue」与「promote」介入（reviewer agent 接管 RFC/代码评审闸） | implemented | P1 |
| [RFC-0013](./0013-implement-e2e-run-result-comment.md) | 实跑端到端脚本并把「合否 + 日志」作为 PR 评论（RFC-0008 指路牌 → 实跑结果延伸） | implemented | P1 |
| [RFC-0015](./0015-ensure-prerequisites-cold-start-bootstrap.md) | 冷启动兜底统一——`ensure_prerequisites` 自举 test 分支与流程标签（三入口幂等） | implemented | P0 |
| [RFC-0017](./0017-explicit-close-issue-on-test-merge.md) | PR 合进 test 后框架显式关 issue（`Closes #N` 对非默认分支失效的补偿） | implemented | P1 |

## RFC 编号规则

- 使用 4 位数字编号，如 `0001`
- 编号顺序分配，不跳号、不复用（CI 会校验本地与 open PR 之间的编号冲突）
- 被 superseded 的 RFC 保留原编号
- 文件名为 `NNNN-slug.md`，slug 用 kebab-case 英文短名
