# Spec-0058 证据 · 跨 issue 调度 DAG 拓扑图产物

本目录是 Spec-0058（跨 issue 调度）DAG 渲图**成果**的可见证据。

## `dag.dot` —— 真实 `schedgraph.render` 代码路径产出

`dag.dot` 由**产品真实代码路径** `openagents.schedgraph.render`（与 `orchestrator.schedule` 调用的同一
函数）产出，示例边集：

- `#150 → #137`（file-conflict，两者都改 `openagents/messages.py`）
- `#150 → #170`（logical，#170 复用 #150 接口）
- `#137 → #200`（logical，#200 依赖 #137 执行器）

产物如实体现两项设计成果：

1. **下游←上游有向边**：`"#150" -> "#137"` 等（上游先做、指向下游）。
2. **波次拓扑分层**：`#150` wave 0 → `#137`/`#170` wave 1 → `#200` wave 2，按波次着色（并行面一眼可见）。

## 能力自检降级（如实结论）

本环境实测**无 graphviz `dot`**、**无浏览器 MCP（Playwright / chrome-devtools）工具**。故：

- `render` 按设计**安全降级**为 `.dot` 文本产物（有 graphviz 时同一函数出 `dag.png`），这是常态路径而非
  边角，绝不硬失败（见 spec Reference-level「渲图」）。
- 尚无 product-facing 前端排程面板可导航，按能力自检降级为「**产物存在性 + DOT 文本边/波次断言**」
  （沿 Spec-0055 能力感知降级、Spec-0043「无浏览器降级文本断言」先例）；未来前端排程面板落地后再补真实
  浏览器导航截图。

## 复现

```bash
bash scripts/e2e-spec-0058-issue-scheduler.sh
```

离线段跑通 ruff + pytest 全套（1017 passed），并断言闭环：fixture→下游 `blocked-by:#<上游>`/独立
`sched-ready`/幂等无抖动；messages 门控挂 `blocked-by` 停 rfc-review（implement 未调）、摘除后放行；上游
closed 后保鲜剪边转 `sched-ready`；`schedgraph.render` 产物存在且 DOT 含预期边与波次分层。
