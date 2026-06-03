# OpenAgents

RFC 驱动的多 Agent 框架：从 GitHub 拉 issue → 派一个 coding agent（Claude Code）改代码 → 开真实 PR → 根据评论/CI 自动迭代。

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
openagents init           # 绑定当前目录为 OpenAgents 项目
openagents solve 42       # 解 issue #42：派 agent 改码 → 开真实 PR
openagents poll           # 扫所有 open PR：CI 失败或有新评论就让 agent 追加 commit 修
openagents watch          # 按间隔自动循环 poll（Ctrl-C 退出）
openagents board          # 本地浏览器打开「成果看板」
```

> `solve` / `poll` 会真的调用 Claude 改代码、用 `gh` 开真 PR，建议先在练习仓库上试。

## 开发

```bash
uv sync --extra dev
uv run pytest          # 单元测试
uv run ruff check .    # 代码检查
```

## 设计

本项目 RFC 驱动开发，设计文档见 [`docs/rfcs/`](./docs/rfcs/)。当前 MVP 见 [RFC-0001](./docs/rfcs/0001-mvp-issue-to-pr-loop.md)。
