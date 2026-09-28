# 交付恢复与评审版本一致性修复

状态：代码修改完毕。本地回归与后续并发压力验收通过，连续远端换版误挂起已修复；未部署。
详见 [并发故障注入压测](2026-09-09-delivery-recovery-stress-design.md)。补充 Spec-0056 /
Spec-0017；此前 snapshot-tests 文档保留为修复前证据。

## 核心契约

开发尚未收尾不是已经交付；已提交但未 push 不是必须重新写代码；评审通过只认证实际检查
的候选。复用现有 Implementer、Deliver、Reviewer、run.status 与调度队列，不新增角色、
队列、数据库字段或审批台账。

## 流程

1. 调用开发者前，以现有 run.status=iterating 记录尚未完成的交接；成功交付后才回到
   pr-open。发生中断，恢复同一个 PR、同一个工作区，继续核对任务与自测，不调用 prepare
   强制重建。缺少明确完成结果时，允许已有开发者核验收尾，但不能强求额外空提交。
2. 开发返回后，检查成果是否已提交并推送。只差 Git 交付时调用现有 Deliver；只有本地
   HEAD 与远端相等且没有未交付文件才算成功。交付角色的完成判据不再是本次 HEAD 必须变化。
3. pending 开发在等待 CI/评审/合并之前恢复；回复人类、终态、依赖和 in-flight 优先级保留。
   正常 draft 转正仍可进行，不把 Gitea draft mergeable=false 引入死锁。
4. 评审前确认工作区是远端候选：干净且仅落后时只作 fast-forward 同步；有本地改动或分叉
   则交回现有开发/交付，不 reset、clean、重建，也不静默丢掉任何提交。
5. 评审后再次检查工作区与远端 HEAD。期间候选变化则丢弃这次裁决，回到现有调度重判；
   合并前实时核对 PR HEAD 和审批标签，并将同一 SHA 传入 forge 的原生合并条件，覆盖
   检查到执行之间的时间差；合并失败不得关闭 issue。REWORK 分支不得被前置 clean 检查挡住。
6. Git 已忽略的缓存不影响交付；未忽略的新文件不能一概豁免。网络、权限等 Git 读取错误
   不当作“已交付”或自动派模型修源码。原有有界异常恢复仍负责真正失败的收敛。
7. `delivery_heads` 复用已检查的 Git 事实，不把本地/远端不同提前定性为交付失败。评审时
   原候选遇到合法换版，走既有 `MergeNotReady` 重新感知，不消耗执行失败预算；未推送的
   评审提交、未提交源码和读取错误仍有界失败。开发交付的相等性硬闸不放宽。

## 实施与验收

- workspace.py：交付含工作区检查、安全同步干净且落后的候选。
- stages.py、agents/deliver.py：实际推送结果优先，补 push 不强求空提交。
- recipes/vigil.py：现有开发状态恢复、统一开发交接、评审前后校验。
- runtime/gates.py：合并时核对实时 HEAD。
- forge / merge-pr：透传已有候选 SHA，不新增锁或版本台账。GitHub 使用
  [--match-head-commit](https://cli.github.com/manual/gh_pr_merge)，Gitea 使用
  [head_commit_id](https://docs.gitea.com/api/operations/repo-merge-pull-request/)；Gitea 的
  幂等验证命令也须携带同一条件，不能在复查时无条件重试合并。
- 复跑 33 个既有回归场景并移除已修复的 xfail；补真实本地 Git 回归、恢复调度和正常流程
  保护测试。测试替身要模拟新的 IO，不能通过关闭目标检查来换绿。

本地验收入口为 scripts/e2e-delivery-review-recovery.sh。它使用假模型与本地 Git，
不声称已验证真实模型的大批任务完成率；不更换运行中实验或旧归档。

## 验收记录（2026-09-09）

执行目录：`/root/src/OpenAgents`。

| 检查 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest -q` | 1304 passed，18.49 秒；无 xfail；桌面测试需要本地 loopback socket 权限 |
| `bash scripts/e2e-delivery-review-recovery.sh` | 489 passed，14.08 秒；无需模型、外部 Git 服务或凭证 |
| 真实本地 Git 专项 | 20 passed；包含 4 个完整恢复→评审→合并场景，6 个 minimal/generate-only 恢复交付场景 |
| 原 33 个 snapshot 回归 | 全部作为普通测试通过，原 20 个 strict xfail 已移除 |
| 本次修改文件的 Ruff check / format | 通过 |
| Spec validate、graph --check、git diff --check | 通过；Spec 仍有历史 warning |

完整恢复测试实际使用本地 bare remote、独立 worktree、真实 Git 和 RuntimeState；只替换
模型与 forge IO，不替换分类、调度、交付检查或评审后的版本检查。测试最终读取 remote main
上的 `entry.py`，确认实现进入最终候选，而不只是看到 PASS 标签。

| 中断时留下什么 | 已验证的恢复路径 |
| --- | --- |
| 只有已推送 Spec/基础候选，尚未实现 | 原开发者继续实现 → Deliver → Reviewer → merge |
| 实现写到一半且未提交 | 原工作区续写 → Deliver → Reviewer → merge |
| 实现已 commit，但未 push | 开发者核验收尾 → 只补 push → Reviewer → merge；HEAD 不必变化 |
| 实现已 push，但超时丢失完成返回 | 开发者核验一次 → Reviewer → merge；不调用 Deliver、不制造空提交 |

可推进性保护还覆盖：pending 开发在 CI pending 时能进入原队列且不受旧零进展戳压制；
保留依赖、人类回复、终态、in-flight 和 draft-ready 的优先级；正常 REWORK 可以修改非干净
工作区；skip 阶段不意外触发开发；干净落后分支可以 fast-forward；分叉/本地领先不丢提交；
Git 忽略的缓存不引发重复开发；网络读取失败不能靠陈旧 ref 冒充已交付；合并报告失败不关闭 issue。

边界：这是离网正确性和恢复可达性的证明，不是线上吞吐率保证。尚未运行真实模型批量
对照或修改实验容器。历史 run 若已错误标记 pr-open 且工作区只有干净 Spec，没有足够信息
自动重建丢失的阶段事实；它仍会进入针对准确远端候选的评审，不能声称已自动修复所有旧归档。

全仓 Ruff 尚有本次未触碰的历史问题：`tests/test_fleet.py`、
`tests/test_runtime_state_converge.py` 的导入排序，以及其它未改文件的格式漂移。
本次没有为获得全仓 lint 绿灯而批量改写无关文件；原先已有的 Spec-0088 / OVERVIEW 编辑也保留不动。

## 后续连续换版修复验收

最终全套 **1322 passed**，专项脚本 **507 passed**。使用修复前相同命令复跑 1152 个压力任务：
40 个换版目标、104 个边界正常对照、912 个常规可恢复任务全部合并；96 个持续故障按原三次
预算停止且未合并。意外阻断、错误合并、重复认领、队列残留均为 0；未增加角色、队列、状态字段
或重试上限。详细历史对比、原始报告路径与离网验证限制见上述并发故障注入压测文档。

## 正式 Spec 与提交验收

本次按仓库 `spec-driven-development` 规范整理为
[Spec-0089](0089-delivery-review-recovery.md)：9 段总览、架构选择、正反行为验收、单一 Task 与
精确文件清单，状态 done。已有日期记录作为历史证据保留，不把 Spec-0088 的未完成要求算进交付。

从 Git 暂存区导出独立快照，再由该快照生成 OVERVIEW；生成物只暂存本次 Spec 的变化，
原工作区 Spec-0088 及其派生视图编辑继续保留。对该独立快照重跑全量测试 **1322 passed**；
12 个修改的生产文件覆盖率（含分支）合计 **88%**，每文件 **83%–100%**。覆盖率工具复用
相邻已安装环境的 coverage 包，不新增项目依赖、不替换测试环境已有包。报告在本地临时快照
`/tmp/openagents-spec0089-submit-qZTdxJ/coverage.data`，不将其声称为远端 CI 结果。

本次 24 个 Python 文件 Ruff check / format 通过；Spec validate、graph --check、文件归属、
本地编号冲突及暂存区 diff 检查通过。全仓仍有上述历史 Ruff 问题，未关闭 CI 或修改无关文件
来掩盖失败；远端编号/分支与 CI 状态需要 GitHub 可用身份才能确认。目前 origin HTTPS 缺少
可用认证，fetch 无法完成；推送或部署只有实际成功后才可另行报告。
