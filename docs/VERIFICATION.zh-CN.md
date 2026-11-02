# 验证指南

[English](VERIFICATION.md) | 简体中文

以下检查在 OpenAgents 源码根目录执行，使用固定提交和已提交的锁文件。示例关闭命令执行前的自动更新，确保实际运行的就是正在检查的代码。

## 离线检查

```bash
export OPENAGENTS_NO_SELF_UPDATE=1
uv sync --locked --extra dev
uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
uv run --locked --extra dev pytest -q
uv run --locked --extra dev spec validate
uv run --locked --extra dev spec render
uv run --locked --extra dev spec graph
uv run --locked --extra dev spec graph --check
```

除非相应源文件发生变化，重新生成不应改变 `docs/specs/OVERVIEW.md` 或 `docs/specs/ARCHITECTURE.md`。CI 还会检查 Spec 编号冲突和提交信息。

使用 NexAU 时，安装对应 extra，核对固定依赖，并通过受控的本地 HTTP 服务测试真实客户端：

```bash
uv sync --locked --extra dev --extra nexau
uv run --locked --extra dev --extra nexau python scripts/check_nexau_dependency.py --installed
uv run --locked --extra dev --extra nexau pytest -q \
  tests/test_backend_nexau.py tests/test_backend_nexau_http.py
```

这些检查不需要模型凭证。本地 HTTP 测试覆盖 SDK 构造和请求响应处理，不能证明真实模型理解了交付要求。

## 证据读取端检查

```bash
uv run --locked --extra dev python scripts/check_observation_reader.py
uv run --locked --extra dev python scripts/check_observation_reader.py \
  --execution-fixture tests/fixtures/execution_evidence_contract.json
```

合成探针覆盖真实的证据准备、gzip/ZIP 解码、范围与摘要检查、只读文件，以及执行条件向角色上下文的传递；远端 Forge 由测试夹具替代。发出警告后降级继续交付，不能记作必需证据检查通过。

真实的**只读**检查需要先在专用测试仓库发布合成包，并导出 `GITEA_TOKEN`：

```bash
uv run --locked --extra dev python scripts/check_observation_reader.py --live \
  --base-url https://gitea.com --owner YOUR_USER --repo YOUR_PROBE_REPO \
  --expected-package /private/synthetic-package.json --sha256 ATTACHMENT_SHA256
```

预期包包含测试 Issue、授权会话和合成文件。探针读取该 Issue 与附件，不发表评论，也不调用模型。应使用目标读取端版本，在实际部署网络中执行。

## 跨仓检查

在兼容的 AHE-Beta checkout 中，对这份 OpenAgents 执行：

```bash
uv run --locked --extra dev python backend/scripts/check_openagents_contract.py \
  --openagents /path/to/OpenAgents
uv run --locked --extra dev python backend/scripts/check_observation_contract.py \
  --openagents /path/to/OpenAgents
```

它们分别对照实际配置生成器、证据发布端和指定读取端，记录结果时注明双方提交。个别历史测试可能仍要求旧控制器包路径；当前组合使用控制器侧的现行检查，不应把测试被跳过当成已经通过。

## 桌面端与打包

在 `apps/desktop/` 中使用 Node.js 22，运行 `npm ci --ignore-scripts`、`npm run typecheck`、`npm test` 和 `npm run build`。启动 GUI 时则通过 `npm ci` 正常安装 Electron。Bundle 构建通过不等于已经完成 GUI 交互测试。

CI 会构建 Python wheel，在源码目录外安装，检查两个 CLI 的帮助，并单独验证带 NexAU extra 的安装，避免开发目录掩盖导入问题。

## 真实交付验收

使用专用目标仓库和实际部署的后端，验证需求录入、规格、实现、评审、合并和重启恢复，也要包含应被拒绝的反例。记录准确的源码或包版本、配置、调用限制与脱敏凭据。UI 行为需要运行中界面的证据，可参考可选的 [UI 验证指南](skills/end-to-end-ui-screenshots/README.md)。

测试和评审期间，将运行证据保存在候选受跟踪源码之外；发布时只选择已检查、已脱敏的结果。明确区分运行成功、模型判断和基础设施失败，模型响应不可用不能记作 PASS 或 REWORK。

历史单次验收报告保留在 Git 历史中。例如，[执行条件合同的模型验收记录](https://github.com/Curry09/OpenAgents/blob/e5b66cef17452513373e5f1d4da192c824b288fb/docs/validation/execution-contract-preservation.md)包含通过的负控制，但正控制始终没有取得模型判定；确定性契约测试不能补全这项语义验收。
