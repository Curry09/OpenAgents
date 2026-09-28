# 轻量前置验证 — 2026-09-11

代码基线：OpenAgents `b4b334f`；Auto Designer 初始 `e26accc`，随后兼容集成 `72afc00` 的 Designer 分组。本次没有运行真实开发 A/B、创建实验 issue/PR 或启动开发者容器。

## 结果

局部正确性检查未发现新死锁、重复执行、漏派或质量闸绕过。软关系成环、全热点重叠、坏输出、超时、损坏缓存、进程重启后的缓存复用、锁占用和 FIFO 老化均覆盖。
不能由此推出真实开发耗时、冲突率或返工率一定改善；这次验证的是前置成本与调度风险。

## 前两轮真实前置调用

| 输入 | issue 数 | 成功耗时 | 输入 token | 输出 token | 合计 |
|---|---:|---:|---:|---:|---:|
| 第一轮 | 27 | 55.326 s | 15,839 | 3,832 | 19,671 |
| 第二轮 | 25 | 20.737 s | 15,659 | 1,438 | 17,097 |

生产入口 `preflight.refresh` → 单轮、禁工具的 ClaudeCodeBackend → 原配置模型 `glm52_250k_yzx_fork_wr_0907`。只提供原始 issue 的限长视图，没有后续 PR 结果或 benchmark。成功调用合计 36,768 token；每次都在 90 秒墙钟与 8,192 输出 token 的限额内完成。

三次先行尝试在 90 秒回退（一次受限环境，两次宿主代理配置错误）；失败调用未返回 token 用量，不能当作零成本。确认内部模型接口可直连后，仅为验证进程补上其主机的 NO_PROXY；没有改变项目网络策略。所有失败都只留下前置 fallback，不写 forge、不设置 automation-failed。

第一轮得到 8 组共享机制、8 条软顺序、7 条提示；第二轮为 5/6/3。模型仍会出现“先实现/依赖于/用统一提案实现”等措辞；它们不会被编译成硬边，开发提示明确要求忽略拆票、替代或跳过独立验收的建议。没有把自然语言建议当成已验证源码事实。

[调用指标](api-metrics.json)、[第一轮建议](round-1-plan.json)、[第二轮建议](round-2-plan.json)。

## 改动前后的本地队列对照

使用真 SQLite WAL、BEGIN IMMEDIATE、flock 和并发线程。基线直接运行 `b4b334f` 的原始认领函数；软调度运行新函数。每个 worker 首次认领后通过 barrier，证明所有槽位可同时填满；任务随后立即完成，故这是极端的写锁压力，不是 LLM 工作负载。

| issue / worker | 原函数排空 | soft 排空 | 原函数认领中位数 | soft 认领中位数 | soft P95 |
|---|---:|---:|---:|---:|---:|
| 30 / 8 | 1.026 s | 1.027 s | 4.166 ms | 5.011 ms | 134.583 ms |
| 300 / 8 | 2.825 s | 2.929 s | 4.086 ms | 4.890 ms | 5.743 ms |
| 3000 / 8 | 13.684 s | 16.066 s | 1.976 ms | 3.053 ms | 5.022 ms |
| 3000 / 32 | 16.498 s | 18.106 s | 1.976 ms | 3.057 ms | 5.062 ms |

全部 8 个场景零重复、零漏领，全部 worker 填满。前两轮既有 API 规划输出也在真实队列中回放：27/25 张票全部可领取，首批都可填满 8 槽。

负面开销存在：本次 3,000 张瞬时任务下，soft 排空较原函数约多 1.6–2.4 秒；典型认领约多 1 ms。极端竞争中两边单次认领都有约 9–11 秒长尾，说明 SQLite 写锁仍是高频瞬时任务下的瓶颈。单次对照会受 I/O 和线程调度影响，另一组 off/soft 对照的 32-worker soft P95 为 29.7 ms，不能把某一轮吞吐数字当稳定收益。

对分钟级真实开发，毫秒级排序成本较小；仍建议维持当前 K=4 或 8，观察正常开发的冲突/返工数据后再加并发。前置不会主动更改 K，也不能把未观测的质量收益计作已实现。

[原函数对照数据](stress-baseline.json)、[关闭模式对照数据](stress-off-comparison.json)。

复现（无需网络或模型）：

```bash
python tools/preflight_stress.py --baseline-revision b4b334f --output /tmp/preflight-stress.json
```

## 回归与检查

- OpenAgents 全量测试：1,358 passed；最终开发上下文修订的交付/前置/引擎定向回归 149 passed。首次沙盒运行因 3 个已有 HTTP socket 测试受限失败，允许本地 socket 后全量通过。
- Auto Designer 配置和 Owner 测试：53 passed；与最新 Designer 分组集成后相关测试 99 passed；生成的 soft 配置已用真实 OpenAgents schema 加载。
- 本次修改的 Python 文件 Ruff lint/format 和 git diff --check 均通过。
- 全仓 lint/format 检查还存在基线遗留：tests/test_fleet.py、tests/test_runtime_state_converge.py 两处导入排序，以及 21 个未修改文件的格式问题；未把它们混入功能改动。

## 启用与退回

Auto Designer 新生成的 YAML 默认 `coordination: soft`。需同时使用包含 spec-0091 的 OpenAgents；容器需重建 vigil 镜像，旧镜像不认识新配置键。现有运行中实验不自动切换。

`VIGIL_COORDINATION=off` 后重新启动，可关闭前置与自动排边；仍尊重 forge 既有真实依赖。`dependencies` 才显式恢复旧 Curator。软模式失败本身即回退到普通队列，不需要人批准或修复规划。

本地兼容镜像已离线构建并通过无网络容器配置加载冒烟：
`auto-designer-vigil:preflight-26cbe45`，ID
`sha256:f3ecbc8b1e9d387483e0a9060c658e695534f1f0e4a10bdbb434bec04948cac1`。
代码 revision 为 `26cbe45`；基底镜像 ID 为
`sha256:e092fd2ba48a9698ff7a5809c1b78bc4a2ef878fe618b6fdce336b7d59449be9`。
普通入口设置 `AUTO_DESIGNER_VIGIL_IMAGE=auto-designer-vigil:preflight-26cbe45`。
没有覆盖 latest 标签或修改运行中实验。
