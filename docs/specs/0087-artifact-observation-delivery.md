---
number: "0087"
title: 制品观测证据交接与开发补强回路
issue: 0
slug: artifact-observation-delivery
summary: 按 issue 获取版本匹配的受限诊断证据包；开发分别维护用户反馈与诊断观测影响并独立验收，仅维护者诊断缺口经认证运行器回传补强。
architecture:
  objective: 让开发各阶段按当前 issue 的授权范围读取历史版本观测，并可靠回传具体诊断缺口。
  constraints:
    - 不解析制品事件字段，不扩展 issue 的 session 权限，不改变冻结目标。
    - 历史证据只读副本与当前测试结果分开，不以日志存在代替行为验收。
    - 用户反馈与维护者诊断按服务对象和判断目标区分，可共享实现但独立验收，不按类别自动建立依赖。
  non-goals:
    - 不引入日志专职角色或运行时事件统一 schema。
  candidates:
    - id: scoped-forge-attachment
      layer: delivery runtime
      boundary: [configured Gitea origin, current issue attachment membership]
      evidence: [runtime.engine role binding, Gitea issue assets API, content digests]
      tradeoffs: 有界下载与副本开销；运输故障显式降级，保留其它证据路径。
  selected: scoped-forge-attachment
  affected-components: [runtime.engine, utils.gitea, observations.evidence, observations.gaps]
  failure-modes:
    - 外链、摘要不匹配或版本错配必须拒绝，不伪装成功。
    - 离线回传保留 outbox，同 ID 重试不能重复提交。
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: 授权 issue 带新格式观测包，开发角色启动。
      expected: 角色得到对应版本的阅读入口；可写具体缺口由运行器回传。
      observation: test_observation_evidence.py 与 auto-designer 受控跨版本实验。
    - id: BC2
      polarity: negative
      stimulus: 外部路径、跨 issue 包、篡改摘要或未授权的 session 请求。
      expected: 拒绝扩权或坏包，不能作为原始事实，也不生成越权补强。
      observation: 测试覆盖路径、摘要、身份和引用检查。
  repository-invariants:
    - GitHub 无此附件契约时不启动 Gitea 取证。
    - 制品内部事件字典不进入运行器解析逻辑。
  exemptions: []
tasks:
  - id: T1
    title: 受限附件读取、角色职责和补强回传
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/observations/evidence.py
      - openagents/observations/gaps.py
      - openagents/runtime/engine.py
      - openagents/utils/gitea.py
      - openagents/recipes/stages.py
      - openagents/recipes/vigil.py
      - openagents/v02/openagents_adapter.py
      - openagents/runtime/context.py
      - tests/test_observation_evidence.py
    scope: 代码修改完毕。固定传输壳，不解释制品事件；仅当前 issue 证据，维护者诊断缺口经认证运行器回传；角色契约区分用户反馈目标和诊断目标。
    acceptance: 格式更换、版本保留、无外链、篡改与越权负例通过；真实启用角色收到证据入口和补强路径。
---

# 0087 · 制品观测证据交接与开发补强回路

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

代码修改完毕。配合 auto-designer spec-0061，开发运行器从当前 issue 的受限附件中取证，
为既有 Spec Writer/Drafter、Architect、Developer/Executor、Reviewer/Acceptance 提供
版本匹配的阅读入口和补强请求路径。不新增角色，不改变 Objective Contract 的冻结语义。

2026-09-08 全量回归 1196 passed；功能代码提交为 `1dda04ab2de550685b7bc181f6b61b26f8972b51`。
固定镜像 `auto-designer-vigil:observability-spec61-1dda04a` 已在无宿主挂载容器中验证私有 Gitea
附件读取；需求与开发两侧补强经过受控 Owner、真实 PR 合并及新版会话复查。角色决策使用脚本，
不等同于真实模型自主采用观测或完整 vigil 工程闸验证。详细结果见 auto-designer
`docs/audits/0061-observation-lifecycle-validation.md`，旧实验和 latest 镜像未替换。

后续目标边界澄清已更新公共开发上下文，现有观测回归 15 项通过，覆盖所有接入角色的
上下文交接与诊断回传。该回归不证明真实模型已稳定区分用户反馈与诊断目标；上段镜像与
全量回归是此前生命周期实现的验证，边界澄清的新镜像以 auto-designer 部署 pin 为准。

## Motivation

开发容器看不到宿主日志路径；源码当前版本也不等于历史事件版本。只改 prompt 或让 agent
自行搜索全部 session 既不可靠，也突破证据范围。功能开发必须同时维护诊断能力与随版说明。

## Guide-level explanation

两类目标按信息服务谁、支持什么判断区分，与发现者角色和底层事件来源无关：

- 用户侧状态反馈：用户在使用中理解当前状况并决定下一步。验收检查决策时刻真实可见的
  信息是否准确、及时、支持所需判断；后台日志或事后解释不能替代。需求沿用普通产品提案。
- 设计开发侧诊断观测：维护者还原经过、区分原因、验证改动。有具体问题时先读随版说明
  和获准记录；验收检查对应版本证据能否回答该诊断问题，进度提示存在不能替代。

Spec 在既有章节内分别说明“用户反馈影响”（何时知道什么、支持什么决定）和“诊断观测
影响”（需还原/区分什么、现有证据是否足够）及各自验证，无影响可简短说明理由。实现同步
维护受影响的用户输出/帮助、诊断记录/阅读说明和测试。可在同一票或交付中共享实现，但
保留独立验收及关联票各自状态；不能用一项通过关闭另一项，不强制拆票。

请求文件专用于维护者诊断取证缺口。question、impact、verification 应明确维护者的问题、
判断影响和诊断验证；开发角色发现用户反馈不足，在既有交付报告中保留具体需求及关联，
交由需求面按普通产品提案处理，不伪装为日志缺口，不宣称报告已经建票。若目标已在冻结
契约内则正常实现，否则不自行扩展冻结目标。两类需求不互相设前置门槛；只有实际无法
选方案或验证时才明确阻塞。
运行器校验诊断请求引用后通过认证 Gitea 注释回传，临时故障留 outbox，下一次调用重试。
`observation-gap` 与请求格式保留兼容；不新增语义分类器，不宣称文本校验能自动识别误投。

## Reference-level explanation

固定外壳为 `auto-designer:observation-evidence-v1`：issue body 中的机器句柄指定该 issue
附件 ID、摘要和大小。下载只向配置 Gitea origin 请求该 issue 的成员附件 UUID，不使用外链，
禁止重定向；压缩和解压均有界。JSON 包只包含获准 session 的文本文件、版本和摘要，不执行文件。
每次角色调用前验证缓存，隔离保存，不写 harness main。内部日志格式由制品决定。

缺口包含问题、已查范围、未知、影响、期望能力、验证和授权引用。运行器绑定真实 role/issue，
回传带稳定 request_id 的签名注释；auto-designer 只接收认证自动化身份并重新校验授权，落普通
proposal。framework scope 仅记基础设施诊断，实验中框架固定，不生成 harness 交付票。

重启和空闲时，vigil 的常规 tick / v0.2 adapter 启动触发单个有界后台补交，不等待新 agent
任务才有机会恢复，也不阻塞调度。回传去重按认证账号检查所有必要评论页；扫描触顶时保留 pending，
不猜测不存在而重复提交。运行器缓存通过 Git 本地 exclude 与制品源码隔离，不依赖制品的 .gitignore。

## Drawbacks

取证增加有界 I/O；附件不可用时明确降级到其它证据，不伪装空日志。私有实验仓的身份边界不等于多租户隔离。

## Rationale and alternatives

复用已有 forge 和角色，不引入公网日志服务、不挂载全量宿主 session、不强制共享事件字典。
运行器处理传输和校验，agent 保留按需读取和判断权。

## Prior art

0074 提供 Gitea 边界，0078 记录调用审计，0082/0083 保留独立目标验收；auto-designer 0059/0060
定义原生日志读取与双轨输入隔离，0061 定义制品自有日志的跨轮生命周期。

## Unresolved questions

发布壳版本变动须双方兼容测试；部署必须更新镜像 pin，源码修改不代表运行中容器更新。

## Future possibilities

比较具体诊断问题的可回答程度，不以日志数量衡量质量；更换 harness 无需改此传输层。
