# 配置指南

[English](CONFIGURATION.md) | 简体中文

OpenAgents 读取目标仓库的 `.openagents/openagents.yml`。`openagents init` 根据[带注释的模板](../openagents/data/openagents.yml.template)生成配置，已有文件不会被覆盖；`init --force` 会替换原文件。文件不存在或为空时，使用内建默认值。

## 默认交付配置

```yaml
version: 1
flow: standard
coordination: dependencies
forge: github
stages:
  triage: agent
  rfc: agent
  architecture: agent
  conflict: agent
  ci: agent
  e2e: agent
  review: agent
  merge: agent
release: manual
defaults:
  interval: 60
  base: main
  labels: [openagents]
repos:
  - path: .
```

未指定的阶段使用 `agent`；未通过环境变量选择 NexAU 时，CLI 使用 Claude Code。`vigil --config PATH` 可选择其他文件；`--base`、`--interval`、`--label` 和 `--skip` 只覆盖本次运行，不改写 YAML。各仓库条目可以覆盖共享默认值；凭证或运行环境不同时，建议分别配置和部署。

## 后端

当前已实现的后端为 `claude_code` 和 `nexau`。`vigil` 通过 `OPENAGENTS_BACKEND=nexau` 选择 NexAU，否则 CLI 创建 Claude Code 后端。

加载器接受 `agents.<角色>.backend` 声明，但当前 CLI 尚未按这些逐角色映射路由执行。仅修改这些字段不会切换实际后端，也不会实现混合后端执行；配置字段接受字符串，不代表任意后端名都有实现。

Claude Code 使用已安装的 `claude` CLI 及其认证、模型和端点配置。默认权限模式为 `acceptEdits`，可通过 `OPENAGENTS_PERMISSION_MODE` 覆盖；应根据目标项目实际需要的工具设置权限。

NexAU 需要安装可选 extra，并导出以下变量：

```bash
export OPENAGENTS_BACKEND=nexau
export OPENAGENTS_NEXAU_MODEL='your-model'
export OPENAGENTS_NEXAU_BASE_URL='https://your-provider.example'
export OPENAGENTS_NEXAU_API_KEY='your-local-secret'
```

该后端使用 Anthropic-compatible **Messages** 接口，不能直接替换为 OpenAI `/chat/completions` URL。可选限制为 `OPENAGENTS_NEXAU_MAX_CONTEXT_TOKENS`（默认 `262144`）和 `OPENAGENTS_NEXAU_MAX_OUTPUT_TOKENS`（默认 `32768`）。示例见 [`.env.example`](../.env.example)，CLI 不会自动加载该文件。

`OPENAGENTS_CLAUDE_MAX_WALL` 控制共享的单次调用总时长，包括 Vigil 派发；虽然名称保留了 Claude，该限制也适用于 Vigil 派发的 NexAU。默认 `3600` 秒，有限且不大于零的值表示关闭。Claude Code 另有输出静默上限 `OPENAGENTS_CLAUDE_IDLE_TIMEOUT`，默认 `300` 秒，不大于零时关闭。持续有活动不会延长总时长预算。

## GitHub 与 Gitea

GitHub 使用 `gh` 的认证。使用 Gitea 时，配置 API 基址和仓库身份：

```yaml
version: 1
forge: gitea
gitea:
  base_url: https://gitea.com
  owner: your-user
  repo: your-project
  token_env: GITEA_TOKEN
```

运行前导出指定名称的 Token；自建 Gitea 则填写该部署可访问的基址。Git 传输也必须能够认证：仅在环境变量中提供 REST Token，并不会自动配置 Git 凭证助手或 SSH 身份。

## 交付流程与协调方式

| 流程 | 入口 | 行为 |
| --- | --- | --- |
| `standard` | `openagents vigil` | 持续交付，包含规格、架构评审、实现、验证、评审和返工 |
| `minimal` | 配置 `flow: minimal` 后运行 `openagents vigil` | 实验流程：紧凑规格、一次实现、按原始 Issue 验收 |
| `generate-only` | 配置 `flow: generate-only` 后运行 `openagents vigil` | 研究流程：受约束生成和机械合并，不做质量验证 |

`coordination: dependencies` 由 Curator 建立硬依赖；`soft` 生成非阻塞的排序建议，保留原始 Issue 和验收条件；`off` 关闭模型协调，Forge 上已有的依赖仍然生效。

## 质量门禁

`triage`、`rfc`、`architecture`、`ci` 和 `e2e` 可以设置为 `agent` 或 `skip`，其中架构评审只能与 RFC 起草一起跳过。`conflict` 和 `merge` 不能跳过；自动合并时，`review: skip` 会被拒绝。在 OpenAgents 中跳过 CI，不会绕过 Forge 的分支保护。

`head-advanced`、`evidence-stamp` 和 `round-cap` 是确定性的运行时门禁，不是可配置阶段。`implement` 和 `deliver` 始终派发 Agent；这些名称不能写入 `stages`。

`release: manual` 是默认发布策略。加载器也接受 `auto`，但自动发布版本尚未实现，应使用显式 `release` 命令；PR 合并仍由交付流程控制。

## 必需的执行条件证据

当发布端支持执行条件证据时，可以在可信项目配置中要求提供：

```yaml
execution_evidence:
  required: true
```

必需证据缺失、损坏、越权或版本不支持时，会阻止模型派发。普通项目默认为 `false`，Issue 正文不能关闭这项要求。发布和读取端检查见 [AHE-Beta 联合使用](integrations/ahe-beta.zh-CN.md)。
