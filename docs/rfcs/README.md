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
| [RFC-0007](./0007-doctor-environment-preflight.md) | openagents doctor —— 环境健康自检（pipeline 预检） | implemented | P2 |

## RFC 编号规则

- 使用 4 位数字编号，如 `0001`
- 编号顺序分配，不跳号、不复用（CI 会校验本地与 open PR 之间的编号冲突）
- 被 superseded 的 RFC 保留原编号
- 文件名为 `NNNN-slug.md`，slug 用 kebab-case 英文短名
