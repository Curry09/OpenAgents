<!-- Spec-0044/T4：浏览器自演示段的诚实阻塞记录（遵循本 skill「诚实报阻塞 ≠ 合理化跳过」纪律）。 -->

# spec-0044 浏览器自演示段：阻塞记录

## 状态：未执行（诚实阻塞，非跳过）

**因 X 未验证**：本次运行环境为**非交互会话**，浏览器自动化 MCP（playwright / chrome-devtools）
的工具调用需要交互式权限授权，而本会话无人可授权 —— `browser_navigate` /
`navigate_page` 均返回 `requested permissions ... haven't granted it yet`。这属于本 spec
`Drawbacks` 已预见的情形（headless / 无显示 / 无可用 browser MCP 的环境只能跑离线段）。

按 `../../skills/end-to-end-ui-screenshots/SKILL.md`「环境确实跑不起来时（诚实报阻塞 ≠ 合理化
跳过）」纪律：**明写此阻塞项，不用离线段顶替声称「浏览器段已跑」**。

## 已完成的部分（离线确定性段）

`bash scripts/e2e-spec-0044-e2e-screenshot-skill.sh` 离线段全绿：ruff + ruff format + pytest
（797 passed）+ 全部 grep 锚点命中（SKILL.md 原文锚点 / reviewer.py 无证据=REWORK /
orchestrator.py 三分类判断）。

## 缺什么才能补齐（供有 browser 的环境执行一次并入库）

在**可授权 browser MCP** 的环境里跑一遍 `scripts/e2e-spec-0044-e2e-screenshot-skill.sh` 的第
2 段说明书，对 `docs/skills/end-to-end-ui-screenshots/examples/reference-app.html`（`file://`
打开）走：

1. `navigate` 打开参考页；
2. `snapshot` 取「应用配置」按钮 + `#status`；
3. `click`「应用配置」；
4. `wait_for` 等 `#status` 出现「已生效」文案；
5. `take_screenshot` 存本目录 `docs/evidence/spec-0044/reference-app-applied.png`；
6. `list_console_messages` 断言无 error、`list_network_requests` 断言无失败请求；
7. **RED 反验**：临时把 `reference-app.html` 里 `status.textContent = "已生效"` 改成不赋值，
   重跑 → `wait_for` 应超时 / 截图显示空 `#status`，证明证据非空过；反验脚手架事后 revert、不进 PR。

补齐后删除本文件，替换为真实截图 + console/network 断言结果。
