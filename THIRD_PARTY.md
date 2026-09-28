# Third-party sources

项目自有代码按根 MIT LICENSE 分发；Python、Electron、React、Vite、模型 SDK 等依赖保留各自许可证，不能由本仓统一重新授权。Python 来源/版本见 `uv.lock`，桌面依赖见 `apps/desktop/package-lock.json`。

NexAU 可选后端从 `pyproject.toml` 中固定的官方 Git 提交安装。Claude Code / Codex 是外部 CLI，使用者按其分发方式安装并遵守其条款；本项目许可证不授予外部服务访问权。

`openagents/spec/` 同时被 auto-designer 以 vendored 形式使用；复制时必须保留本仓 LICENSE 和可追溯的来源记录。

`docs/e2e-results/` 等实验取证、用户提供的目标代码与模型输出需要分别检查，不能仅因位于仓库就推定全部第三方内容按 MIT 分发。完整历史/发布资产扫描和依赖许可汇总列为公开前检查项。
