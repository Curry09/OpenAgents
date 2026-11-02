# 架构指南

[English](ARCHITECTURE.md) | 简体中文

OpenAgents 将交付决策、模型执行和 Forge 操作分开。[配置指南](CONFIGURATION.zh-CN.md)说明用户可选择的行为；自动生成的[模块映射](specs/ARCHITECTURE.md)记录 import 关系与实现归属。

## 组件划分

| 位置 | 职责 |
| --- | --- |
| `openagents/cli.py` | 参数解析、项目识别与配置接线 |
| `openagents/recipes/` | 持续交付、阶段组合与规格补录 |
| `openagents/agents/` | 角色提示词与结构化输出契约 |
| `openagents/runtime/` | 调用、共享上下文、门禁、状态、观测与用户测试 |
| `openagents/backends/` | Claude Code 与 NexAU 执行适配 |
| `openagents/observations/` | 授权证据下载与执行条件校验 |
| `openagents/utils/` | Git、GitHub/Gitea、工作区、配置与发布操作 |
| `openagents/v02/` | 显式有限批次的 DAG 调度及生产适配器 |
| `openagents/spec/` | Spec 编写、校验与视图生成 |
| `apps/desktop/` | 实验性的桌面观测界面 |

各交付流程使用的角色不同：标准流程包含起草、架构、实现、测试和评审；显式批次使用 Spec Writer、Spec Curator、Developer 和 Acceptance。它们共享执行及证据契约，不要求采用相同调度算法。

## 持续状态协调

Vigil 的调度单位是**工作对象**，例如 `issue:5` 或 `pr:12`。每个周期读取 Forge 当前事实，分类后派发动作、等待，或记录完成与失败。持久化 Worker 在 `--parallel K` 的上限内认领工作；一个慢任务不会让其他对象等待整批完成。

常见动作包括起草与实现、回复新的人工评论、解决冲突、修复 CI、采集验证证据、评审候选和合并。决策基于当前状态，进程重启后可以从漏掉的周期恢复；旧 PR head 上通过的检查或评审不能证明新 head 已通过。

默认标准流程由角色承担模型判断，由运行时门禁检查机械事实。提交前移、证据来源和轮次限制保持为确定性检查；跳过可配置阶段只改变交付策略，不改变远端分支保护。

## 状态与恢复

| 存储 | 职责 |
| --- | --- |
| Forge Issue、PR、评论、检查与标签 | 需求、依赖、交付改动及外部可见结论 |
| `.openagents/vigil-queue.db` | 工作队列、原子认领和未完成尝试计数 |
| `.openagents/claims/` | 通过 `flock` 持有的进程存活锁 |
| `.openagents/runtime-state.json` 及观测记录 | 运行记录、进度、耗时与用量 |

SQLite 和进程锁使它成为**单机调度器**，不要通过网络文件系统让多台机器共享队列数据库。模型 Worker 可以在独立仓库工作区操作，但这不意味着调度数据库支持分布式部署。

后端崩溃、输出格式错误、超时和反复无进展受有限重试预算约束。耗尽后，`automation-failed` 记录与相关事实绑定的机器失败。新的 PR head、修正后的 CI 或更新的 Issue 等实质变化允许重新判断；仍存活的持有者不会仅因租约看起来过期就被回收。必需执行证据缺失时阻止派发，材料修复后可再次尝试。

## 验证边界

实现角色可以修改候选；Tester 和 Reviewer 检查已交付提交，并将生成的证据保存在被忽略的目录或外部目录，不修改候选的受跟踪源码。证据缺失不等于检查通过。脚本化契约测试只能证明传输或控制行为，模型理解和真实任务完成需要单独验证。

读取端将历史对话当作数据，不当作角色指令。协商过执行合同时，原始目标、后续输入可用性、预算和安全验收摘要进入共享角色上下文；私有评分器和答案不进入。详见[联合使用](integrations/ahe-beta.zh-CN.md)和[验证指南](VERIFICATION.zh-CN.md)。
