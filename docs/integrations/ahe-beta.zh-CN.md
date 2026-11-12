# 与 AHE-Beta 联合使用

[English](ahe-beta.md) | 简体中文

[AHE-Beta](https://github.com/Curry09/AHE-Beta) 运行模拟用户实验、收集反馈并生成 Harness 改进需求。OpenAgents 通过 Issue 和 PR 在 Harness 仓库中实现这些需求，下一轮用户使用更新后的版本；OpenAgents 不负责控制器的实验编排或独立基准评测。

## 安装与生成配置

根据控制器选定的交付环境安装后端。Claude Code 需要外部 CLI；NexAU 需要 `nexau` extra、`OPENAGENTS_BACKEND=nexau`，以及已导出的 `OPENAGENTS_NEXAU_MODEL`、`OPENAGENTS_NEXAU_BASE_URL` 和 `OPENAGENTS_NEXAU_API_KEY`。NexAU 使用 Anthropic-compatible Messages 接口；安装及端点说明见[配置指南](../CONFIGURATION.zh-CN.md)。

控制器在交付仓库生成 `.openagents/openagents.yml`。当前使用 Gitea、默认的 `standard` 流程、软协调和 Agent 评审；跳过 e2e，默认跳过 CI，本地实验可按 CI 策略启用；执行条件证据为必需。这与独立 CLI 的所有可配阶段默认由 Agent 执行不同。

通过 AHE-Beta 的 `backend/scripts/experiment.py` 和公开实验配置启动、设置实验。生成的 OpenAgents YAML 可能被重写，直接修改它不能作为持久的实验设置。

交付进程需要同时通过 Git 和 API 访问同一个 Gitea 仓库。E2B 部署应使用沙盒可访问的地址，`127.0.0.1` 指向沙盒自身，而非操作者机器。固定实际 OpenAgents 可执行文件或镜像，并设置 `OPENAGENTS_NO_SELF_UPDATE=1` 保持版本不变。

## 观测证据

控制器通过 Issue 附件发布授权的会话证据。OpenAgents 支持 gzip 和 ZIP；ZIP 必须只含 `evidence.json` 并声明编码，未声明编码的句柄按 gzip 解释。两种格式均检查摘要、Issue 和会话授权、大小限制与文件路径。

Gitea.com 读取端允许附件入口受限地跳转到支持的 R2 存储域，使用签名 HTTPS URL；外部存储请求不会携带 Gitea Token、Cookie 或 `.netrc` 认证。其他站点使用同源直接下载；遇到未知存储域时拒绝读取，不放开任意跳转。

启用发布格式前，在**真正的交付环境内部**查询读取端：

```bash
OPENAGENTS_NO_SELF_UPDATE=1 openagents observation-capabilities --json
```

能力对象声明 gzip/ZIP、`single-evidence-json-v1` 及支持的下载策略。已有 gzip 附件无需迁移；内部协议 Marker 为保持兼容仍使用既有名称，项目更名不会改变这些标识。

## 执行条件

控制器在可信项目配置中启用：

```yaml
execution_evidence:
  required: true
```

要求会随派发工作保存，重启时即使配置回落默认值，也不能静默降级。必需证据缺失或无效时不派发模型；Vigil 释放槽位并等待材料修复，显式批次记录节点失败，修复后可以重新运行。

共享上下文保留每个来源的原始目标、公开交付物、后续用户输入是否可用、预算和安全的独立验收摘要；较大的来源集合显式分页。历史对话只作证据，不作指令。`passed: null` 表示没有二值判定；观测到任务失败，本身不能证明 Harness 缺陷，也不会直接淘汰候选。

私有评分器、答案文件和隐藏评测计划不进入角色上下文。要求传递证据本身不会新增独立基准门禁。

## 验证版本组合

在 AHE-Beta 中对预期的 OpenAgents checkout 运行配置和观测契约检查，再执行读取端探针，并在实际部署网络中读回合成证据。具体命令与验证边界见[验证指南](../VERIFICATION.zh-CN.md)。能力声明或降级后继续交付，不能替代只读证据和最终角色上下文的验证。

记录两仓提交及实际部署的包或镜像身份。联合版本清单和部署顺序见[发布指南](../RELEASING.zh-CN.md)。
