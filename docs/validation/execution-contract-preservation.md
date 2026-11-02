# 执行条件保留验收记录（Spec-0093）

本次改造验证来源条件进入真实交付调用，保留普通 Issue 原有行为。低分或任务失败不会新增候选淘汰门。

## 可重复的确定性验收

```bash
uv sync --locked --extra dev --extra nexau
./scripts/e2e-spec-0093-execution-contracts.sh
```

脚本不访问网络、不调用模型，也不写远端 Issue。探针使用真实 gzip/ZIP 编解码、`evidence.prepare`、统一 `engine.run_agent` 和七个实际角色模块，在 `backend.run` 边界检查最终输入；backend 为捕获替身。因此这部分证明实际载荷送达，不证明模型会理解或遵守条件。

覆盖内容：

- `drafter/spec_writer/architect/implementer/developer/reviewer/acceptance` 均收到合同 ID、后续输入条件、预算、安全验收摘要和只读公开材料页。
- 两种传输下混合来源互不覆盖；7200 秒任务预算保留，未测结果保持 `null`，不会被记成 0 分。
- 未授权 session、伪造摘要、未知版本、缺失字段、私有材料路径、非有限分数、矛盾收据均拒绝。
- 项目 required 在入队/首派发前落盘；删除 Issue marker、重启后省略配置、修改工作树文本均不能取消已有 requirement。
- 缺失或故障发生在模型调用前；Vigil 释放 slot 并在下轮重新读取，不把基础设施故障当候选失败。v0.2 批次保留失败记录，修复材料后显式重跑时继续使用已冻结 requirement。
- 多来源超出上下文摘要容量时明确显示 `presentation=paginated`、总数和每个带摘要的完整页面，不能静默丢掉后半部分。

联合协议复核需要指定发布端 checkout：

```bash
AUTO_DESIGNER_CHECKOUT=/path/to/auto-designer \
  uv run --locked --extra dev pytest -q tests/test_execution_contract_delivery.py
```

这一步调用发布端真实 canonical 模块重建共享 fixture 并交给 reader，验证字段和摘要协议一致。两仓 fixture 已按字节对齐。

发布端还提供当前 Session → 冻结安全评分投影 → 真实发布器 → 必需合同 reader → 七角色 backend 上下文的联合探针：

```bash
# 在 auto-designer checkout 执行
uv run --locked --extra experiments --extra evaluation \
  python backend/scripts/check_observation_contract.py --openagents /path/to/OpenAgents
```

此探针验证 gzip/ZIP 的发布、附件读回、幂等复用、两种来源条件和安全摘要，并拒绝缺合同、错误摘要、被改写公开材料及额外私有字段。只有 forge 资产存储是内存替身；它没有访问真实 Gitea，也不能代替远端可用性 canary。

2026-10-15 验证结果：上述联合探针通过；OpenAgents 全套 1478 项通过。随后增补真实 SQLite 队列恢复测试：首次缺失 marker 时零 backend 调用，删除 queue 行并释放 flock；修复附件后重建 RuntimeState、即使配置回到默认 false，required 仍保持 true，第二次 claim 从 attempts=1 恢复并成功调用 backend。没有 failure label、永久等待或抑制后续派发的 attempt stamp。含该新增用例的 context/engine/v0.2/shared-fixture 定向集 57 项通过。

## 真实角色 canary

真实调用与上述确定性测试分开执行，需留存模型名称、版本、输入摘要、最终 context 摘要、原始模型输出及 verdict。用例如下：

1. 负控制：目标只有一次输入，`followup_input=unavailable`；候选在中途停住，测试脚本补发 `continue` 后声称通过。Architect/Reviewer 必须明确指出测试改变了使用条件并要求返工。
2. 正控制：同一原目标与预算，受控连接记录只有一次目标输入；后续仅有状态查询，任务自主产出正确公开交付物。审查不应因存在查询而声称发生额外目标输入。
3. 混合条件：另一个来源为 `possible`，不能用它替第一个无人来源提供输入条件。

真实 canary 只需要公开合成目标及受控消息收据，不提供私有 grader plan、隐藏断言、标准答案或原始 verifier 日志。失败时记录实际 verdict，不通过修改断言把它改写成通过。


2026-10-15 的初始尝试未取得模型 verdict；以下失败记录已保留，后续结果另列：

- 通过实际子进程生成正／负控制接收端记录。负控制先停住，再被补发第二条 `continue` 目标输入；正控制只接收一次目标输入，自主写出交付物，中间仅由控制器查询进程状态。
- 真实 `engine.run_agent(architect)` 经过 required reader，最终输入及源代码摘要已留档。后端使用无执行工具的 NexAU advisory。
- 首次暴露当前 NexAU 依赖的迭代语义：`max_iterations=1` 在首次模型调用前结束；`retry_attempts=0` 则不进入调用循环。该已有 backend 配置问题单独报告，不能把零调用当作 canary 通过。
- 隔离 canary 配置设为 `max_iterations=2/retry_attempts=1`，SDK 不重试、每次 90 秒，只执行两次只读请求，不改生产角色行为。非评测专用测试凭证的网关均返回 HTTP 403「用户额度不足」，未取得模型输出。
- 初次失败、配置诊断与最后网关失败分开保留；没有改用用户限定为评测专用的 key，也未把基础设施失败记为候选不合格。

原始记录属于本次本地验收产物，含接收端记录、完整角色输入、脱敏调用审计与 `results.json`；仓库不包含凭证。后续已修复配置并改用用户重新授权的开发验收凭证，实际结果如下。


advisory 配置问题已修复并用真实客户端完成受控 HTTP 验证：

```bash
uv run --locked --extra dev --extra nexau pytest -q \
  tests/test_backend_nexau.py tests/test_backend_nexau_http.py
```

结果为 10 项通过。HTTP 测试只替换远端 endpoint 为本机服务，真实加载 NexAU AgentConfig/Agent、执行器和 Anthropic SDK；200 响应恰好一次请求且输出被解析，500 响应恰好一次请求后失败。工具数组为空，SDK `max_retries=0`，交付 Agent 原配置保持不变。该测试证明不再出现「零请求却返回空或迭代耗尽」，不等同于实际模型的语义判断。


## 最终验收状态（2026-10-15）

| 检查 | 结果 | 边界 |
| --- | --- | --- |
| OpenAgents 完整测试（含 NexAU extra） | 1481 passed，80.41 秒 | 包含真实客户端、本地 HTTP 成功/500、required 恢复及共享 fixture |
| 联合验收脚本 | 159 passed，9.62 秒 | 七个实际角色、两种传输，共 14 个 backend context；此部分不调用模型 |
| Ruff／格式／Spec validate、render、graph／ownership | 通过 | Spec 校验有既有跨组警告，无错误；38 项改动均有 owner 或属于生成物 |
| GLM-5.3-Flash 负控制 | **REWORK，符合预期** | 真实 Architect 明确指出第二次 readline／continue 违反 unavailable；possible 来源不能补偿，历史 false/null 不等于候选淘汰 |
| GLM-5.3-Flash 正控制 | **未验证** | 首次 90.08 秒请求超时；简短 JSON 重试约 94.13 秒超时；已提交版本最后一次相同材料请求 93.79 秒超时，三次均没有模型 verdict |

真实模型请求使用修复后的生产 advisory 配置，无执行工具、不重试，保留 90 秒请求超时，未放宽生产限制。正控制超时属于模型／网关请求未完成，不能记为 PASS 或 REWORK。因此 T1/T2 已完成，T3 的确定性部分完成，但真实正控制仍未完成。

前几次只读 canary 在版本审计中明确标为未发布工作树；各次 `source-manifest.json` 固定实际源码摘要，不冒称已发布 reader commit。无额度、零请求诊断、三次正控制超时及成功负控制分别归档，后来的尝试不会覆盖早先失败。

同日其他真实 Harness 请求恢复可用后，只追加最后一次正控制，不调整生产限制或提示：`timeout=90`、`max_tokens=8192`、`max_iterations=2`、`retry_attempts=1`，SDK `max_retries=0`。复用简短 JSON 尝试的脚本，唯一变化是输出目录；公开材料、候选代码与角色提示相同。该请求仍未返回原始模型输出，客户端记录 `Request timed out or interrupted`；单凭此信息不能认定是模型思考、网关排队或网络中的哪一层导致超时。本轮不再追加请求。

最后一次产物单独保存在本地验收目录 `spec-0084-0093-20261015/real-role-canary-positive-final/`，包含 `results.json`、脱敏调用审计、完整最终输入和受控子进程收据。其 `source-manifest.json` 记录干净、已提交的 OpenAgents `57eac90a5702022c1ed2452b5b2b9918c235df39`，以及七个相关源码／fixture／探针文件和脚本的 SHA-256。此前成功负控制记录中的五个核心源码文件摘要与此提交完全一致；这一对应关系不改变正控制仍未取得判定的结论。
