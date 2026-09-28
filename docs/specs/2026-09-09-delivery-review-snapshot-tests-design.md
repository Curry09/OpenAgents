# 交付与评审版本一致性：回归测试设计

> 以下为修复前的历史基线，保留当时的结果。修复实现与最新验收见
> [交付恢复与评审版本一致性修复](2026-09-09-delivery-review-recovery-design.md)。

状态：测试代码修改完毕；生产修复尚未实施。本文补充 RFC-0005、Spec-0056、Spec-0017
的既有工作区、交付和评审契约，不增加角色、阶段、队列或持久化记录。

## 问题与边界

2026-09-09 的 spec61-ronacher-next-20260909-retry2 实验中，开发已推送 Spec 提交
472621c，随后实现留在工作区；调用超时后，已有 draft PR 被转正。Reviewer 检查了
`git diff HEAD -- entry.py` 中的未提交实现，框架却给远端 Spec 提交贴上了审批标签。
证据：相邻实验目录 recovery-20260909/old-scheduler.log:3692–3821。

唯一核心约束：批准的候选必须就是实际检查的候选，不能把本地额外改动的通过结果
绑定给远端提交。本次只添加离网单元回归和正常通路保护，不修改运行中实验或生产逻辑。

## 同时验证安全与可推进性

| 情形 | 期望 |
| --- | --- |
| 工作区干净、本地与远端版本相同 | 正常评审、批准、合并，不额外调用交付角色 |
| 未暂存、已暂存、新增源码、删除或冲突 | 不把未交付改动算作已交付 |
| 已提交但未 push | 不能审批旧远端；通过已有交付路径继续 |
| 交付角色仅需补 push | 远端到达既有本地提交即完成，不强求额外空提交 |
| 调用超时，draft 与本地实现均保留 | 不重建或清空实现；恢复既有开发/交付，随后重新评审 |
| Reviewer 运行期间版本或源码变化 | 这次结果不能认证另一个候选 |
| 只有 Git 已忽略的测试缓存或观测产物 | 不因普通测试副产物阻断审批 |
| 修 CI 或评审返工时工作区非干净 | 仍允许开发角色继续，不把交付检查放在所有动作之前 |
| Gitea draft 的 mergeable=false | 保留转正的可达性，不能恢复旧死锁 |
| 正常 rebase 改变远端、旧工作区落后 | 需同步后重新评审，不能永久拒绝或直接审批旧工作区 |

不能只证明“拒绝了”。恢复测试还必须证明调用现有角色续交付、重新批准最新提交并最终
完成。被忽略的缓存由 Git ignore 规则判定；不能随意豁免所有 untracked 文件或按扩展名
猜测源码。被 Git 跟踪的测试/文档同样可能属于交付，不是缓存。

## 测试落点与执行

- tests/test_workspace.py：现有 assert_delivered 与 ensure 的单元边界，Git 子进程替身。
- tests/test_recipe_vigil_act.py：复用现有 rig，调用真实分类/动作/stage；模型与 forge 离网。
  快照场景恢复真实 Workspace.assert_delivered，不能用恒通过替身掩盖目标漏洞。
- 同时跑已有 stages、gates、vigil 回归，防止修复误伤正常调用顺序。
- tests/test_runtime_gates.py：合并前远端换版但旧标签仍在，不能只匹配传入的旧 SHA。
- tests/test_recipe_stages.py：真实 HEAD/证据闸下补 push 完成不能判零进展。

已确认的缺陷用严格 xfail 标注，`--runxfail` 将它们作为普通失败运行；这是显式登记未修复
问题，不是修复验收。未来实现后出现 XPASS 会使测试失败，要求移除对应 xfail 并检查断言。
正常通路不允许 xfail。

```sh
.venv/bin/python -m pytest tests/test_workspace.py tests/test_recipe_vigil_act.py tests/test_runtime_gates.py tests/test_recipe_stages.py -q
.venv/bin/python -m pytest tests/test_workspace.py tests/test_recipe_vigil_act.py tests/test_runtime_gates.py tests/test_recipe_stages.py -k delivery_snapshot --runxfail -q
```

这是组件级离网回归入口，不是模型/forge 真闭环。尚无修复实现，不能据此声称修复后的真实
批量阻断率为零。若恢复路径仍无法推进，须先梳理 solve → ready → CI/e2e → review/rework
→ merge 的交接，而不是提高重试次数或新增终止标签。

## 本次结果与开发流程审计

新增 33 个参数化用例：13 passed、20 strict xfailed。用 `--runxfail` 运行得到
13 passed、20 failed；失败均落在目标断言或已确认的交付异常，而非网络/模型/缺失替身。
20 是失败场景数，不是 20 个独立 bug，更不是线上阻断率。
完整测试套为 1246 passed、20 xfailed（16.53 秒）；Ruff check 与 git diff --check 通过。
初次受限环境运行有 3 个本地 HTTP 用例因 socket 权限失败，允许 loopback socket 后全量
重跑通过，不将环境权限错误计作产品缺陷。本次没有修改 openagents/ 生产代码。

| 现有交接 | 已核验的问题或须保留的行为 | 修复不能只做什么 |
| --- | --- | --- |
| solve 内 implement → deliver | 未提交会交给 deliver；HEAD 已前移但未 push 却直接异常 | 不能把 commit 等同 push，也不能只抛错终止 |
| deliver → 后续检查 | 目前强求本次调用产生新提交；只补 push 被判零进展 | 不能靠空提交让计数器前进 |
| 超时 → 已有 PR | 当前 ready 后跳过剩余交付，直接进入后续评审 | 不能把“PR 存在”当成实现已交付 |
| draft → ready | Gitea draft 会报 mergeable=false，提前转正防死锁 | 不能把转正简单移到所有门禁之后 |
| CI / review 返工 → implement | 非干净工作区仍须允许继续开发 | 不能在所有角色入口统一要求 clean |
| rebase / review → 审批 | ensure 复用旧目录；远端和工作区可能不是同一版本 | 不能永久拒绝落后的干净工作区，也不能审批旧内容 |
| 审批 → merge | 实时快照有 HEAD，但闸只使用标签和传入的旧 HEAD | 不能假设 push 会删除旧审批标签 |

第一轮的安全测试容许明确拒绝不一致候选；恢复测试不吞异常，并要求实际调用既有开发/
交付角色、复用 PR、重新审批最新提交、最终 done。这避免把“没合错”误当成“流程已修好”。
Git ignore 在这些单元测试中由替身建模；未对真实 harness 的全部日志产物作兼容性证明。
也不以“必须修改某种源码文件”判断实现完成，避免误拦合法文档任务。

实际修复后的验收：移除已修复场景的 xfail，所有适用用例正常通过，再用同一批真实任务
比较完成率、额外角色调用与持续重试；只测拦截数量不足以判断是否导致批量卡顿。
