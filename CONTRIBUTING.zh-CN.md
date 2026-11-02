# 贡献指南

[English](CONTRIBUTING.md) | 简体中文

欢迎提交可复现问题、文档修正及聚焦的实现。先阅读[项目说明](README.zh-CN.md)和 [Spec 指南](docs/specs/README.md)；新功能或跨模块行为变化先更新对应设计契约，不要手动编辑生成的 `docs/specs/OVERVIEW.md` 和 `docs/specs/ARCHITECTURE.md`。

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

桌面端使用 Node.js 22，在 `apps/desktop/` 执行 `npm ci`、`npm run typecheck`、`npm test`、`npm run build`。仅运行类型检查、测试和构建时，可使用 `npm ci --ignore-scripts`；图形界面试用则需要安装 Electron 二进制。

锁文件随依赖修改一并提交，日常 CI 使用 `--locked`。涉及交付契约时在 AHE-Beta 中跑跨仓配置检查，并注明双方提交。普通 PR 无需模型 key；真实模型 canary 单独记录成本、版本和脱敏证据。

NexAU 可选检查、跨仓探针及离线和真实验收的边界见[验证指南](docs/VERIFICATION.zh-CN.md)。

## 提交与评审

使用 Conventional Commits，例如 `fix(cli): preserve resume identity`。若指定 scope，只能使用 `backend`、`cli`、`ci`、`deps`、`docs`。PR 描述说明问题、最终行为、验证命令及限制；避免把试验轨迹、凭证或机器专用配置混入源码。新 spec 通过仓库 CLI 预留编号，修改后重生成视图。不要在整理 PR 中擅自重写既有实验结果。

提交贡献表示你有权提供相应代码，并同意按本项目 MIT 许可证分发该贡献。第三方材料应保留自己的许可与来源；涉及人物画像或基准任务的内容先核对[第三方来源](THIRD_PARTY.zh-CN.md)。

## 双语文档

根目录的 README、CONTRIBUTING、SECURITY 和 THIRD_PARTY 各提供英文版（`.md`）与简体中文版（`.zh-CN.md`）。修改其中一版时，请同步另一版的内容、命令和链接，并保留顶部的语言切换入口。`docs/` 下的使用指南也提供两种语言；设计 Spec 主要使用中文。
