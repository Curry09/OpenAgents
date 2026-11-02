# 第三方来源与许可

[English](THIRD_PARTY.md) | 简体中文

OpenAgents 自有代码按 [MIT License](LICENSE) 分发；依赖与外部材料保留各自的许可和来源声明。

## 依赖来源

| 组件 | 来源与版本记录 | 分发方式 |
| --- | --- | --- |
| Python 依赖 | [`pyproject.toml`](pyproject.toml) 与 [`uv.lock`](uv.lock) | 作为独立包安装，各包适用其自身许可证 |
| NexAU 可选后端 | [hzhua/nexau](https://github.com/hzhua/nexau)，提交 `28511d9f0362191a6c378fd441b2be55309a9e32` | Apache-2.0；固定 Git 依赖，未内置源码副本 |
| Electron、React、Vite 等桌面端依赖 | [`apps/desktop/package.json`](apps/desktop/package.json) 与 [`package-lock.json`](apps/desktop/package-lock.json) | 通过 npm 安装，打包分发时保留适用声明 |
| Claude Code | 外部安装的 CLI | 独立分发，适用其自身条款 |

基础包与 `nexau` extra 的依赖集合不同，源码和 wheel 元数据声明相同的 NexAU 固定 Git 来源。分发 NexAU 时，保留上游许可证、版权及适用的声明。OpenAgents 的 MIT 许可证不授予模型服务访问权，也不改变服务条款。

## 复用的项目代码

AHE-Beta 复用 `openagents/spec/` 工具。复制该代码时，应保留 OpenAgents 的许可证及可追溯来源，接收项目的许可证不替代原有声明。

## 目标仓库与生成材料

目标仓库代码、任务数据、模型输出和用户材料，不会仅因经过 OpenAgents 处理就改变许可。发布证据或资产前，应核对其来源许可及分发权限。运行记录还可能包含私有任务内容，分享前参照[安全说明](SECURITY.zh-CN.md)检查。
