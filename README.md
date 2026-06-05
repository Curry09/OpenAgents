# OpenAgents

RFC 驱动的多 Agent 框架：从 GitHub 拉 issue → 先起草 RFC、由人评审批准 → 派一个 coding agent（Claude Code）按 RFC 改代码 → 开真实 PR → 根据评论/CI 自动迭代。

目标是用最小的 MVP 把「issue → PR」的闭环跑通，然后用它迭代自身。

## 前置条件

- Python ≥ 3.12、[uv](https://docs.astral.sh/uv/)
- 已鉴权的 [`gh` CLI](https://cli.github.com/)：首次用 `gh auth login` 登录（GitHub.com → HTTPS → 浏览器授权即可），用 `gh auth status` 确认通过。OpenAgents 不存任何 token，鉴权全交给 `gh`。
- 已安装的 [`claude` CLI](https://docs.claude.com/claude-code)

## 安装

```bash
uv tool install --from . openagents
```

装好后 `openagents` 在任意目录可用。改了代码后用 `--force` 重装更新。

## 用法

在一个 GitHub 仓库目录里运行（缺 git/远端时会提示你新建）：

```bash
openagents init             # 绑定当前目录为 OpenAgents 项目
openagents rfc 42           # 为 issue #42 起草 RFC，开 draft PR 等人评审（RFC-0005）
openagents refine-rfc 7     # 按 PR #7 上的最新评审评论精炼 RFC，并回贴改动说明
openagents implement 7      # RFC 获批（PR 打上 rfc-approved 标签）后，按 RFC 写代码并转正 PR
openagents iterate 7        # coding 阶段就 PR #7 的最新评论/CI 失败迭代（--reason comment|ci）
openagents poll             # 扫所有 open PR，按阶段自动路由：评审评论→精炼 / 批准→实现 / CI→修
openagents watch            # 按间隔自动循环 poll（Ctrl-C 退出）
openagents board            # 本地浏览器打开「成果看板」
openagents doctor           # 体检流水线环境：git/gh 鉴权/后端 claude/origin（RFC-0007）
```

### `openagents doctor` —— 环境健康自检（RFC-0007）

派单前用一条命令确认「这台机器能不能跑通 issue→PR 流水线」。`doctor` 只读地逐项体检并打印
✓/✗ 清单，**任一必需项失败时以非零退出码返回**（可直接用于脚本/CI 门控）。与 `board` 一样，
`doctor` 跳过项目绑定 preflight——体检对象恰恰可能是尚未就绪的环境。

检查项分两档：

| 检查项 | 档位 | 说明 | 失败修复 |
|--------|------|------|----------|
| `git 仓库` | 必需 | 当前目录是否为 git 仓库（复用 `resolve_project`） | `cd` 到目标仓库或 `git init` |
| `gh 鉴权` | 必需 | `gh` 是否安装且已 `gh auth status` 鉴权 | 安装 `gh` / `gh auth login` |
| `后端 claude` | 必需 | `claude` 是否在 PATH | 安装 Claude Code CLI |
| `origin 远端` | 可选 | 是否配置 origin 远端（推送/开 PR 才需要） | `git remote add origin <url>` |

可选项失败仅以 ⚠ warning 呈现、**不影响退出码**（纯本地仓库也能起草 RFC）。退出码只由必需项决定：
全部必需项通过 → `0`；任一必需项失败 → `1`。

RFC-first 闭环（RFC-0005）：`rfc <issue>` 起草 → 人在 draft PR 上 comment → `refine-rfc`（或 `poll` 自动）按评论改 RFC → 人打 `rfc-approved` 标签批准 → `implement`（或 `poll` 自动）按 RFC 写码并转正 PR → 进入评论/CI 迭代。CLI 只触发单步，跨步骤编排交给 `poll` 的状态机。

> 这些命令会真的调用 Claude 改代码、用 `gh` 开真 PR / 发评论，建议先在练习仓库上试。

## 开发

```bash
uv sync --extra dev
uv run pytest          # 单元测试
uv run ruff check .    # 代码检查
```

## 设计

本项目 RFC 驱动开发，设计文档见 [`docs/rfcs/`](./docs/rfcs/)。当前 MVP 见 [RFC-0001](./docs/rfcs/0001-mvp-issue-to-pr-loop.md)。
