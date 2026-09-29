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

## Gitea.com 观测证据兼容（Spec-0092）

证据读取端支持原 gzip 和新增 ZIP（仅含 `evidence.json`），内部 v1 JSON、issue 授权、
历史版本、路径与摘要检查保持不变。无 `encoding` 的旧句柄仍按 gzip 解释；ZIP 必须显式
声明 `encoding: zip`，不需要迁移已有自建 Gitea 的附件。

部署新托管路径前，在**实际交付环境的可执行文件或最终镜像内**检查能力：

```bash
OPENAGENTS_NO_SELF_UPDATE=1 openagents observation-capabilities --json
uv run --locked python scripts/check_observation_reader.py
```

第一条离线、只读，不需要仓库或凭证，也不自更新；旧 OpenAgents 不识别该命令时，环境
开关同样防止查询先触发更新。第二条使用合成证据验证真实 `prepare`，不调用模型。
支持 ZIP/R2 的发布端必须先验证实际 reader，不能用宿主源码版本代替运行镜像。
纯旧 gzip + 同源直接下载的组合不强制要求新增能力命令。

Gitea.com 的附件入口允许一次到固定 R2 HTTPS 域的签名跳转，外部请求不携带 Gitea token、
cookie 或 `.netrc` 认证；其他站点保留原同源直接下载行为。下载有总时间和大小限制。
站点存储域发生变化会明确拒绝，不能通过放宽任意重定向解决。容器出口、公网 Gitea URL
和镜像 pin 由配套 auto-designer 部署配置负责。

真实合成探针可显式调用读取脚本：

```bash
uv run --locked python scripts/check_observation_reader.py --live \
  --base-url https://gitea.com --owner YOUR_USER --repo YOUR_PROBE_REPO \
  --expected-package /private/synthetic-package.json --sha256 ATTACHMENT_SHA256
```

凭证从 `GITEA_TOKEN`（或 `--token-env` 指定的环境变量）读取；预期 JSON 包含测试 issue
编号、授权 session 和合成文件。脚本只读取指定 issue/成员附件，临时副本验证后删除，不创建
远端评论或调用模型。成功要求真实只读文件、scope 和 digest；“证据不可用”的降级不算通过。
