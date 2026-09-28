# 交付恢复并发故障注入压测

状态：代码修改完毕。连续换版与常规压力复测全部通过，未部署。历史失败证据保留如下。
补充 Spec-0056 / Spec-0017 / Spec-0065。

## 验证问题

版本一致性修复能否在并发、重试和远端变化同时发生时，保持正确合并与正常任务推进？
不把“全部拒绝”算作成功，不把刻意注入的持续故障算成普通任务误拦。

## 构造

- 每批一个临时 bare remote、一个共享 checkout、每 issue 独立 worktree，共享原生 Git 元数据。
- 保留真实 engine、Vigil 感知/分类/生产入队/worker/claim/reconcile、SQLite、flock、RuntimeState、
  Git 交付闸及评审前后检查。仅替换模型 backend 与外部 forge；故障注入在 backend 或 Git IO 边界。
- fake forge 合并不是简单更新状态：在串行的本地集成工作区执行真实 Git merge，汇入同一个 main，
  合并前检查调用携带的 SHA 是否仍等于远端。逐任务核验评审 SHA、候选内容与最终 main 文件。
- 1/4/8/16 worker 对照；固定随机种子打乱任务，正常基线与混合故障分开统计。重试上限保持生产值。
- 临时数据只写新建目录，不访问凭证、外部 API，不修改运行中实验。不调用真实模型，因此耗时不代表
  真实模型吞吐；超时用相同异常注入验证恢复，不声称在本测试重测了 1800 秒进程终止机制。

## 场景和判据

正常已交付、尚未实现、未提交、已提交未推送、已推送丢返回、开发过程中分别在 commit 前/后超时、
review 一次改脏候选、review 期间远端换版、merge 检查后远端换版、一次 Git fetch 失败、普通缓存、
一次未忽略日志、正常 REWORK。另有持续 review 污染与持续 fetch 失败两个负向对照。

扩展边界：同一任务连续三次在评审期间被合法更新远端、之后不再变化。候选变化不等同模型/
网络持续失败，预期应在稳定后继续评审，而非误用重试预算冻结任务。此项单独运行并报告，不把
它归入持续故障负向对照来掩盖误拦。

要求：可恢复任务最终合并且内容正确；持续故障有界失败、不合并、不影响同批其它任务；无重复认领、
无失去已有实现、无用旧版本审批合并新版。记录任务状态、角色调用、认领/重试、P50/P95、队列残留、
并发峰值和完整失败日志。出现异常保留现场并报告，不通过提高重试上限或关闭门禁使测试变绿。

## 复现与结果

入口为 `scripts/stress_delivery_recovery.py`，结果保存在新建的 `delivery-stress-*` 目录中。
首轮先用小批校验压测器，再扩大重复量；生产代码不随测试结果自动修补。

## 正式常规压力结果（2026-09-09）

```sh
.venv/bin/python scripts/stress_delivery_recovery.py --workers 1 4 8 16 --repeats 8 --baseline 32 --seed 59 --deadline 180
.venv/bin/python scripts/stress_delivery_recovery.py --workers 4 16 --repeats 8 --baseline 32 --seed 83 --deadline 180
```

总计 1008 个任务：912 个正常或可恢复任务全部合并、内容核验通过；96 个持续故障任务均在
3 次认领后失败退出且未合并。错误合并、重复认领、意外阻断、生产者错误、队列残留均为 0。
单次超时、一次远端换版、只差 push、缓存、未忽略日志、返工等各场景均不是只测拒绝，而是要求最终完成。

第一组（seed=59）的分档结果：

| worker 配置/实际峰值 | 正常基线合并 | 混合场景合并 | 预期持续故障停止 | 基线耗时 | 混合耗时 |
| --- | --- | --- | --- | --- | --- |
| 1 / 1 | 32/32 | 120/120 | 16/16 | 6.82s | 47.78s |
| 4 / 4 | 32/32 | 120/120 | 16/16 | 2.44s | 16.34s |
| 8 / 8 | 32/32 | 120/120 | 16/16 | 2.44s | 15.00s |
| 16 / 16 | 32/32 | 120/120 | 16/16 | 2.38s | 14.36s |

正常基线每任务均为 Tester/Reviewer/Merger 各一次，没有 Implementer/Deliver 的额外调用。
并发达到 4 后收益趋平，受本地串行 Git 合并、Python/Git 进程与生产扫描成本影响；该数字不能用于
预测真实模型/网络服务吞吐。第二组与边界复测存在同机同时执行，不与第一组作精确性能比较。

原始报告：

- `/tmp/delivery-stress-lbm7p4md/summary.json`：672 个任务，seed=59。
- `/tmp/delivery-stress-13d6acmg/summary.json`：336 个任务，seed=83。
- 各批目录内保留 `result.json`、`scheduler.log`、逐次测试证据、bare remote、原工作区与运行状态。

## 未通过的边界：合法换版消耗了执行失败预算

```sh
.venv/bin/python scripts/stress_delivery_recovery.py --workers 4 16 --repeats 4 --baseline 16 --scenarios clean remote-churn-3 --seed 61 --deadline 60
.venv/bin/python scripts/stress_delivery_recovery.py --workers 1 16 --repeats 16 --baseline 16 --scenarios clean remote-churn-3 --seed 83 --deadline 90
```

两组共 144 个任务：104 个正常对照全部合并；40 个连续三次合法换版任务 **40/40 被误挂起**，
均认领 `[1, 2, 3]` 后写入 `automation-failed`。无错误合并、无重复认领；两条命令退出码均为 1。
16-worker 大批边界复测的实际并发峰值为 16。小批任务数少时实际峰值低于配置，报告如实记录。

故障注入不是源码损坏或持续网络故障：每次更新都发布有效实现且保留 `value = 1`，只更换一次合法
候选；第三次之后远端保持稳定，本应继续检查新版本。此项不属于 NEGATIVE，不将其失败美化为成功。

根因链条：

1. `vigil._verify_candidate` 先调用 `Workspace.assert_delivered`。
2. 评审期间远端前进、本地仍是所评审的旧提交，`assert_delivered` 抛 `WorkspaceError`。
3. 后面的 `MergeNotReady`（候选变化 → 正常重判）分支来不及执行。
4. `_run_claimed` 按普通失败累计重试；第三次写失败标签，而不是重读第四个稳定候选。

代码位置：`openagents/recipes/vigil.py:3052`、`openagents/utils/workspace.py:136`、
`openagents/recipes/vigil.py:2167`。可复核日志：
`/tmp/delivery-stress-ja1pjm6c/mixed-w4/scheduler.log:79`，随后第 87、95、98 行记录第二次、第三次与挂起。

边界报告：

- `/tmp/delivery-stress-ja1pjm6c/summary.json`：8 个目标失败，40 个正常对照通过。
- `/tmp/delivery-stress-0ctcl838/summary.json`：32 个目标失败，64 个正常对照通过。

额外因果复查（不计入上述 40 个正式目标）：
`/tmp/delivery-stress-snmo74wv/summary.json`，1 个目标再次失败、1 个正常对照通过。压测器在终态后
调用真实 `_refresh_failure_projection` 重查稳定事实，日志 `terminal recheck issue 2: failed=True`，
确认不是下一 tick 就会自动恢复的瞬态。

下一步修复应区分“候选已变化”与“执行失败”：前者作废旧裁决、重新评审，不烧普通失败预算；
未提交源码、读取失败等仍保留原检查。需覆盖检查之间再次换版的时间窗口，不能仅吞掉所有
WorkspaceError，也不能提高重试上限。此处只给出诊断，本次尚未修改生产代码修这个边界问题。

## 验收解释与限制

新增 `tests/test_delivery_recovery_stress.py` 覆盖小批并发和压测裁判自身：故意给脏候选盖 PASS
会被独立检查判为失败。普通测试套最后一次运行 1306 passed；这 **不代表连续换版压力已通过**。
完整压测命令的失败保留在上面，不新增 xfail、不关闭门禁，也不将失败目标移出统计。

本测试证明离线调度/Git 的可达性与误阻断边界；不是实际模型推理能力、真实 forge 服务可用性或
线上总体发生率的证明。所有实验为临时隔离仓库，没有提交/部署修复，也没有触碰运行中实验。

## 连续换版修复设计（后续开发）

把现有 `assert_delivered` 中的 Git 事实读取抽为 `Workspace.delivery_heads`：检查工作区干净、
成功 fetch、成功读取非空的本地与远端 SHA，返回二者，不判断用途；fetch/读取后再查工作区，
防止读取过程中产生未提交文件。只刷新跟踪 ref，不切换工作区、不提交推送。

开发交付仍由 `assert_delivered` 要求本地与远端严格相等。评审验收复用事实读取：本地仍是
原候选、远端合法前进，或本地与远端已经一起换版时，抛既有 `MergeNotReady`，作废旧裁决，
由既有生产者重新感知并评审；不消耗执行失败预算。评审者自己留下未推送的新提交、未提交文件、
Git/forge 读取失败依旧作为执行失败，不能伪装为合法换版。不增加异常类型、状态字段、队列或
重试次数，不捕获并吞掉 `WorkspaceError`。

回归必须覆盖 fetch 期间换版、Git 读取之后 forge 再换版、读取过程中改脏、未推送的评审提交、
读取失败，以及三次换版后第四次评审完成。原 40 个误挂起任务使用原命令、种子和重试上限复测；
再跑原 1008 个常规压力任务，验证正常推进与持续故障隔离均未退化。

## 修复后验收（2026-09-09）

以上四条正式压力命令原样重跑，种子、任务规模、并发配置、deadline 与生产重试上限均未改变。
仅追加了 Git 事实读取与验收分类的修复；压测裁判也明确将重复认领计入失败，不放宽判据。

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| 连续三次合法换版 | 40/40 误挂起 | 40/40 合并；均第四次评审成功 |
| 边界组正常对照 | 104/104 合并 | 104/104 合并 |
| 常规正常/可恢复任务 | 912/912 合并 | 912/912 合并 |
| 持续 Git 失败/持续污染 | 96/96 有界停止，未合并 | 96/96 有界停止，未合并 |

换版任务的认领 attempts 从 `[1, 2, 3]` 变为 `[1, 1, 1, 1]`：每次都重读真实候选，
只有第四个实际评审的稳定 SHA 得到批准并合入 main，没有旧裁决套到新版。持续故障仍是
`[1, 2, 3]` 后停止。全部 1152 个压力任务中错误合并、意外阻断、重复认领、生产者错误、
队列残留均为 0。常规 clean 场景共 240 个，均只调用一次 Tester/Reviewer/Merger，无额外开发/
交付调用。常规实际并发峰值覆盖 1/4/8/16；边界小批峰值按实际记录，不声称全达 16。

修复后报告（旧报告不覆盖）：

- `/tmp/delivery-stress-anmmashk/summary.json`：8 个换版目标与 40 个正常对照全部完成。
- `/tmp/delivery-stress-d0hhl1uc/summary.json`：32 个换版目标与 64 个正常对照全部完成。
- `/tmp/delivery-stress-0v0n4qia/summary.json`：常规 672 个任务全部符合预期。
- `/tmp/delivery-stress-5wj0s9pt/summary.json`：常规 336 个任务全部符合预期。

单元/集成回归：`pytest -q` 最终 **1322 passed，28.07 秒**；专项脚本
`bash scripts/e2e-delivery-review-recovery.sh` **507 passed，19.88 秒**，已纳入小批连续换版测试。
真实 Git 专项共 35 项，覆盖 fetch 期间及其后换版、读取时改脏、未推送的评审提交、空 SHA 与
Git/forge 读取异常。三次换版回归先在旧实现上实际失败，再在修复后通过，不使用 xfail。
修改文件 Ruff check/format、Spec validate / graph --check、git diff --check 通过；历史 Spec warning 保留。

成本与限制：读取后新增一次本地工作区检查，避免 fetch 期间的改脏漏检；正常任务无新增模型调用。
若远端持续产生真正的新候选，则仍需重新评审，无法承诺在候选永不稳定时完成；这不是通过
无限重试真实错误换来的成功。此次并行运行多个压力批次与回归，不将其耗时差当作严格性能对照。
未提交、推送、部署修改，也未恢复/改写正在运行或已归档的用户实验。
