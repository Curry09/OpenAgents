# 发布指南

[English](RELEASING.md) | 简体中文

OpenAgents 独立管理版本。与 AHE-Beta 联合发布时，记录一组经过验证的仓库提交和部署产物即可，两仓不需要使用相同版本号。

## 准备候选版本

从计划发布的 `main` 提交开始，更新包版本及发布说明，执行[验证检查](VERIFICATION.zh-CN.md)，通过 `uv build` 构建 wheel 和源码分发包。在源码目录之外验证安装；如果发布包含 NexAU 后端，也要验证对应 extra。

源码验证使用已提交的锁文件。uv tool 安装在独立环境中解析包元数据，不复现完整开发锁。NexAU extra 带有固定 Git 依赖，选择包发布渠道前，应验证该渠道对 direct-reference 依赖的支持。

联合发布应记录：

- 两仓的提交或不可变标签。
- NexAU 的固定来源及其他运行依赖版本。
- 实际交付镜像 digest 或已安装包的身份。
- 配置 Profile、平台和验证结果。

[`release/compatibility.json`](../release/compatibility.json) 是历史整理基线，不代表当前 main 已经完成联合发布。保留其中的历史标识，在发布资产中写入实际候选清单，不预写未来提交的哈希。

## 验证部署

对选定组合执行跨仓配置和观测契约检查。使用证据的部署还应在实际可执行文件或镜像中查询 `observation-capabilities --json`，关闭自动更新，并沿实际 Forge 和网络路径验证合成证据。部署的读取端支持新能力后，再启用对应发布能力。

同时验证成功交付及预期的拒绝、恢复行为，分别记录阻断和未验证项。按[安全说明](../SECURITY.zh-CN.md)及[第三方来源](../THIRD_PARTY.zh-CN.md)检查发布资产和日志中的凭证与受限材料。

## 发布版本

1. 冻结通过验证的候选，构建资产，生成校验和与版本清单。
2. 通过 Draft 或 Prerelease 验证安装与下载。
3. 创建不可变版本标签，发布说明和资产。
4. 联合发布时，先提供可被依赖的 OpenAgents 产物，再由控制器固定并验证该版本，双方发布页互相链接。

`openagents release --bump patch|minor|major` 是**目标仓库操作**：检查运行失败和 main CI 后，依据本地 `main` 引用推送 `release/vX.Y.Z` 分支和标签，因此应先确认该引用已更新。命令不会构建 wheel、创建 GitHub Release 或修改仓库可见性。

候选验证失败时，修复后生成新候选；不移动已发布标签，也不覆盖既有实验的冻结版本。回退证据传输时，先确认目标 Forge 仍接受原格式，否则应停止新派发，等待兼容路径恢复。
