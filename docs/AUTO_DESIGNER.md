# 与 auto-designer 联合使用

OpenAgents 是交付 CLI，可独立安装；auto-designer 模拟用户并生成需求，通过 Gitea issue/标签交接，等待 Harness main SHA 更新。联合版本来源与发布门见 [RELEASING.md](RELEASING.md)。

## 安装后端

在本仓根目录，默认 Claude Code 后端只安装基础包：

```bash
uv sync --locked --extra dev
uv run --locked openagents --help
uv tool install --from . openagents
```

NexAU 后端另有可选 extra，与联合基线固定在相同 NexAU 提交和 `ag-ui-protocol==0.1.22`：

```bash
uv sync --locked --extra nexau --extra dev
uv run --locked --extra nexau python -c 'from nexau import Agent, AgentConfig'
uv tool install --from . 'openagents[nexau]'
```

`uv sync --locked` 用于源码环境可复现安装；`uv tool install` 使用包依赖元数据并创建独立环境，不承诺复用本仓的完整锁。源码改变后需要 `--force` 重装。

NexAU 后端需要 `OPENAGENTS_NEXAU_MODEL`、`OPENAGENTS_NEXAU_BASE_URL`、`OPENAGENTS_NEXAU_API_KEY`。该后端使用 Anthropic-compatible Messages 协议；OpenAI-compatible `/chat/completions` URL 不能直接当作其端点。可选上下文/输出限制变量见 `.env.example`。CLI 不自动 source `.env`，运行前需由 shell 或受控 launcher 导入。

## Forge、flow 与权限

配置位于目标仓库 `.openagents/openagents.yml`；使用 `openagents init` 生成的完整模板为准。Gitea 示例：

```yaml
version: 1
forge: gitea
gitea:
  base_url: http://127.0.0.1:3000
  owner: demo
  repo: harness
  token_env: GITEA_TOKEN
flow: v0.2
coordination: soft
agents:
  spec_writer: {backend: nexau}
  spec_curator: {backend: nexau}
  developer: {backend: nexau}
  acceptance: {backend: nexau}
release: manual
```

`flow: v0.2` 是显式选择：批量 Spec → DAG → Developer → Acceptance → 机械合并。默认 `standard` 仍可使用本分支；还有 `minimal` 与 `generate-only`，语义见包内配置模板，不能当作相同质量门的别名。

auto-designer 当前旧入口生成 `forge: gitea`、`coordination: soft`，省略 flow（因此为 standard），默认 CI/e2e 为 skip、review 为 agent。生成配置每次会被重写。上面的 v0.2 示例用于独立配置，不能靠分支名或手改生成文件切换旧 launcher 的行为。

独立 CLI 默认的 CI/e2e 门与 auto-designer 生成配置不同。启动前核对实际 YAML、后端和权限；`release: manual` 不阻止自动合并 PR。只在受信任的目标仓与运行环境中启动 `vigil`。

## 离线契约检查

在 sibling auto-designer checkout 中：

```bash
uv run --locked python backend/scripts/check_openagents_contract.py --openagents ../OpenAgents
```

它检查真实配置生成器与本仓解析器，不访问 Gitea 或模型。真实交付、终态屏障和续跑还需要独立 live canary。

桌面端位于 `apps/desktop/`，本轮仅保证 typecheck、单元测试和 bundle 构建；尚未把 GUI 启动、签名及多平台安装包列为首发承诺。
