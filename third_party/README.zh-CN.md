# 仓内第三方依赖

`nexau/` 保存 NexAU 0.4.1、提交 `5cd791b1382f1163621c9ff0b50c2cf01c4ba923` 的完整源码树，不含 Git 元数据或本地缓存。Apache-2.0 LICENSE 与原有声明完整保留；根目录 MIT 不替代这些条款。

原有 1012 个文件保持原样。新增的 `UPSTREAM.json` 保存逐文件 SHA256 与上游 Git tree；`nexau/_vendor_info.py` 仅提供来源与完整性校验，不修改 Agent 行为。

`uv sync --locked` 从仓内目录安装 NexAU，不访问已不可用的上游 Git 地址，也不替换为 PyPI 同名版本。独立校验：

```bash
python3 scripts/check_vendored_nexau.py
```

从相同源码构建可分享的 SDK wheel：

```bash
uv build third_party/nexau --wheel --out-dir dist/sdk
```

以 wheel 安装 OpenAgents 的可选 NexAU 后端时，应同时提供本地 SDK wheel 和带 nexau extra 的 OpenAgents wheel；普通 pip 不读取 tool.uv.sources。CI 会在源码目录外验证这种安装。

上游源码不参与本项目的 lint/test 扫描。修改 SDK 时单独记录补丁与来源校验值，不能把改过的代码冒充原上游快照；两仓维持同一冻结版本。已有实验及其冻结源码不会因此被改写。
