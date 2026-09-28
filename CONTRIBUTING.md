# Contributing

欢迎提交可复现问题、文档修正及聚焦的实现。先阅读 README 和 docs/specs/README.md；新功能或跨模块行为变化先更新对应设计契约，不把生成的 OVERVIEW/ARCHITECTURE 当源文件手改。

## 本地检查

在本仓根目录：

```bash
uv sync --locked --extra dev
uv run --locked --extra dev pytest -q
uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
uv run --locked spec validate
uv run --locked spec render
uv run --locked spec graph
```

前端使用 Node.js 22，在 `apps/desktop/` 执行 `npm ci`、`npm test`、`npm run build`。OpenAgents desktop 另跑 `npm run typecheck`；只做 bundle 检查可 `npm ci --ignore-scripts`，GUI 试用则需要安装 Electron 二进制。

锁文件随依赖修改一并提交，日常 CI 使用 `--locked`。涉及交付契约时在 auto-designer 中跑跨仓配置检查，并注明双方提交。普通 PR 无需模型 key；真实模型 canary 单独记录成本、版本和脱敏证据。

## 提交与评审

使用 Conventional Commits，例如 `fix(runtime): preserve resume identity`。PR 描述说明问题、最终行为、验证命令及限制；避免把试验轨迹、凭证或机器专用配置混入源码。新 spec 通过仓库 CLI 预留编号，修改后重生成视图。不要在整理 PR 中擅自重写既有实验结果。

提交贡献表示你有权提供相应代码，并同意按本项目 MIT 许可证分发该贡献。第三方材料应保留自己的许可与来源；涉及人物画像/benchmark 的内容先核对 THIRD_PARTY.md。
