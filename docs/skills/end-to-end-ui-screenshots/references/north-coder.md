# Runbook：north-coder 项目具体流程

SKILL.md 的「通用流程」在 north-coder 上的具体落地。其他项目**别照抄命令**，照抄的是 SKILL.md 的思路，自己写一份本项目的 runbook。

前置：**绝不碰生产端口 8848**；用安全端口（后端 8851 / 前端 5175）。

1. **配置**：需要真 app 显示的行为，改到位（含为跑通证据而做的临时脚手架，如临时 agent/profile —— 只能是测试夹具，**不得伪造正在验证的那个行为本身**；事后必须 revert，不进 PR）。dev 后端读 `backend-rs/agent/`，改 yaml/prompt 后新开会话即生效。
2. **起后端**（后台）：`RUST_LOG="warn,<target>=info,north_coder_backend_rs=info" NORTH_CODER_LOG_LEVEL=info NC_CONTEXT_SINGLE_USER=1 ./backend-rs/target/debug/ncoder serve --mode server --host 127.0.0.1 --port 8851 --data-dir ~/.north-coder --no-serve-frontend > backend.log 2>&1`。改了 Rust / 依赖 rev 要先 `cargo build --bin ncoder`。日志落盘以便 grep + 截图运行时证据。
3. **起前端**（后台）：`printf 8851 > frontend/.backend-port`；`pnpm --filter frontend run dev --host 127.0.0.1 --port 5175`。缺依赖先 `pnpm install`。用 `until nc -z 127.0.0.1 <port>` 等就绪。
4. **驱动 UI**：chrome-devtools MCP。`new_page` → `take_snapshot`（拿 uid）→ `fill`/`click` 发指令 → 轮询后端日志等目标事件（真 LLM 慢，用 `until grep ... backend.log` 等，别干等）→ `take_snapshot` 展开子过程 → `take_screenshot`。
5. **截图落地**：chrome-devtools MCP 只能写进它自己配置的 workspace root（这次会话里恰好是 nexau-rs 根；实际以当前配置为准，写别处会 Access denied）——先存 workspace root、再 `mv` 进 north-coder 的证据目录（如 `docs/evidence/<rfc>/screenshots/`）。同时把运行时日志片段存 `logs/`。
6. **可观测性缝**：模型不自知的东西（middleware 组成、max_context_tokens、工具集）在产品侧加一行 INFO 运行时日志专门打印，UI + 日志双证。
7. **收尾**：停我起的服务（按端口 `lsof -ti tcp:8851` kill，或 TaskStop 后台任务）；`rm frontend/.backend-port`；**revert 所有临时脚手架**；确认生产 8848 全程未动。
