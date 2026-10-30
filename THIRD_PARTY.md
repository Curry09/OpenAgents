# Third-party sources

项目自有代码按根 MIT LICENSE 分发；Python、Electron、React、Vite、模型 SDK 等依赖保留各自许可证，不能由本仓统一重新授权。Python 来源/版本见 `uv.lock`，桌面依赖见 `apps/desktop/package-lock.json`。

NexAU 可选后端使用 `third_party/nexau/` 内的 0.4.1 冻结源码（提交 `5cd791b1382f1163621c9ff0b50c2cf01c4ba923`）；Apache-2.0 LICENSE 和原有版权声明保留，来源与逐文件校验见 `UPSTREAM.json`。uv 从仓内目录安装，独立 wheel 用法见 `third_party/README.md`。Claude Code / Codex 是外部 CLI，使用者按其分发方式安装并遵守其条款；本项目许可证不授予外部服务访问权。

`openagents/spec/` 同时被 auto-designer 以 vendored 形式使用；复制时必须保留本仓 LICENSE 和可追溯的来源记录。

`docs/e2e-results/` 等实验取证、用户提供的目标代码与模型输出需要分别检查，不能仅因位于仓库就推定全部第三方内容按 MIT 分发。完整历史/发布资产扫描和依赖许可汇总列为公开前检查项。
