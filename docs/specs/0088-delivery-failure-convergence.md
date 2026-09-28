---
number: "0088"
title: 并行交付审批身份与失败收敛
issue: 0
slug: delivery-failure-convergence
summary: Spec 自引用重编号不撤销语义审批；合理设计变化回到已有评审（待实现），失败缺证据不自动复活。
tasks:
  - id: T1
    title: 版本化设计摘要和审批审计
    status: pending
    priority: P1
    depends-on: []
    files:
      - openagents/spec/model.py
      - openagents/runtime/gates.py
      - openagents/recipes/stages.py
      - openagents/runtime/state.py
      - tests/test_spec_model.py
      - tests/test_runtime_gates.py
      - tests/test_recipe_stages.py
      - tests/test_runtime_state.py
    scope: 摘要归一和原始审批审计已实现；2026-09-09 修订验收要求，摘要变化回到已有架构评审的衔接尚未实现。本次仅修改要求，不改变运行中实验。
    acceptance: 自引用改号不撤销审批；摘要失配表示旧审批未覆盖当前设计，回到已有架构评审而非反复尝试合并。依据原始需求、约束、旧设计与当前主干和候选改动判断；复用主干实现不得丢失原验收要求，合理调整经评审通过后更新现有审批并继续原交付流程。未确认的目标、约束或验收弱化不得放行；证据不足须说明缺口并返工。旧审批不猜测迁移，不直接用当前摘要替换，不新增角色、阶段或审批台账。
  - id: T2
    title: 失败标记读写一致与缺证据保守收敛
    status: done
    priority: P1
    depends-on: [T1]
    files:
      - openagents/recipes/vigil.py
      - tests/test_recipe_vigil.py
      - tests/test_recipe_vigil_act.py
      - scripts/e2e-spec-0088.sh
    scope: 代码修改完毕。审批摘要随运行持久化；failure marker 按 subject 所属 issue 或 PR 读取，不复用 attempt 评论路由。
    acceptance: 关联 PR 的 issue 失败后同事实不重排；缺失或无效标记保持终态；真实事实变化恢复一次；裸 PR 兼容。
---

# 0088 · 并行交付审批身份与失败收敛

## Summary

初版代码修改完毕。修复双用户实验发现的两项交付框架问题，不更换已归档实验的源码或镜像。
2026-09-09 本次仅修订 T1 的验收要求：允许合理设计变化经已有评审重新确认；
对应评审回流尚未实现，T1 重新标记 pending，T2 的既有实现保持 done。下述测试结果属于初版，
不作为新验收要求已经实现的证据。
离网集成回归入口：`bash scripts/e2e-spec-0088.sh`；覆盖真实 Spec 读写、审批闸、状态持久化、
失败标记读写与调度。forge 和模型使用替身，不声称这是新镜像真实模型闭环。
2026-09-09 最终全量回归 1223 passed，以上集成入口 235 passed，Ruff check 与 Spec/graph 校验通过。
全量回归中本地 HTTP 测试需要可创建 loopback socket 的环境；沙箱权限拒绝不作产品失败归因。

真实归档的 rebase 后历史 `e5dc3fc`（0002）与 `b65184a`（0005）原始摘要分别为
`e1221dd3b7bfa9c45281ee1600de9d2eeadb1727a40622651ec6289f5c71bef0`、
`71b06698f1550998dffd46cb79a8dca7b62051fb7646580240a9a3578a88b41d`，与人工核验审计吻合。
新语义摘要均为 `v2:b96ed7ffbce8e4163cc147c61050d8cbd237d9827ab26c473ebcd1befda79c4d`；
在内存中修改验收条件会改变新摘要。原实验归档没有被修改。

## Motivation

2026-09-08 spec61 双用户实验的 issue #8 从 Spec-0002 改到 0005，仅任务说明中的
自引用变化便使已批准 digest 失配；失败标记写在 issue，读取却跟随 PR，造成缺标记反复复活。
证据在相邻 auto-designer-experiments/spec61-two-user-glm53-glm52-20260908 的
archive/harness.bundle、telemetry/gitea-snapshot.json 和 manual-interventions.jsonl。

## Guide-level explanation

新审批使用版本化语义摘要；明确自引用改号属于身份迁移，不是新设计。原始设计摘要仍落盘，
原文由 Git 和架构输入审计保留。旧审批保持原始精确匹配；没有可信旧快照不能自动重新批准。
失败态只在找到所属对象的有效标记且事实确有变化时解除；缺标记明确保留失败，不循环重试。

修订后的验收要求（评审回流待实现）：摘要只标识审批覆盖的版本，不判断变化是否合理。
摘要变化后复用已有架构评审，对照原始需求、约束、原批准设计及当前主干与候选的差异判断。
例如另一张票已在主干实现同一能力，本票可以复用而非重复实现，但必须证明最终版本仍满足
本票原来的验收要求，不能通过删除要求或测试降低标准。合理调整通过后，更新现有审批记录，
继续原有代码评审和合并流程；不把新阶段、角色或审批台账引入框架。审批及测试结果仍须对应
实际被检查的候选版本，不能凭 rebase 成功自动放行。

## Reference-level explanation

design_digest v2 只归一 prose 中独立的 Spec-NNNN/Tn，且 NNNN 是当前组号、Tn 存在。
归一为带类型的片段，避免普通文本占位符碰撞；文件声明与依赖原样参加摘要。
legacy_design_digest 保留原算法；合并按审批版本选择算法，不从当前源码重写审批。
design_raw_digest 伴随新审批保存，后续状态变化不得覆盖丢失。
失败读取单独按 subject 分流，与已有 attempt-stamp 的 PR 优先路由解耦。
继续沿用已有 identity 标记识别约定，不把文字标记声称为密码学身份认证。
上述是初版已实现的摘要和失败收敛机制。修订要求中的评审回流需补入既有交付流程；
本次没有修改运行时代码，也没有修改任何运行中或已归档实验的审批状态。

## Drawbacks

当前实现中的旧版失配审批仍需人工核验，不能靠升级自动复活。按修订要求接通评审回流后，
由已有架构评审依据可信原始上下文确认变化；无法取得原需求或旧批准设计时不能猜测通过。
仅明确语法可自动归一，其他变化交评审判断；合理变更可能增加一次现有评审调用。

## Rationale and alternatives

不自动接受新摘要、不关闭架构闸、不全局替换数字，也不为重编号引入共享编号分配服务。
缺标记选择保留失败，优于将读取缺口当作真实新事实。

## Prior art

本仓设计摘要与 assert_design_approved 的现有实现，以及 Spec-0081 的事实指纹失败收敛契约。
外层识别 automation-failed 由 auto-designer Spec-0062 独立修复。

## Unresolved questions

源码回归不等于新镜像真实闭环验证；部署必须重新构建并冻结新的镜像，不替换旧实验制品。

## Future possibilities

先验证既有评审回流能处理复用主干、设计合理调整和验收弱化的正反例；不扩展一套猜测语义等价
的数字替换规则。尚未获得有效审批时仍不得合并。
