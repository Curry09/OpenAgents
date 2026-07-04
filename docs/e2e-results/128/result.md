# 端到端执行证据（PR #128）

- 执行形态：cli
- 结论：pass

## executor 运行说明

本改动是纯 prompt 文本硬化（`openagents/reviewer.py` 的 `_RUBRIC_TAIL` 加「裁决理由必须一段简短中文」硬规约），
无运行时行为变更、无浏览器可跑成果——e2e 形态由 ui 降为 cli，可验证成果 = 离线确定性段（真跑，非声称）：

- `ruff check .` + `ruff format --check .` 全绿。
- `pytest -q` 全绿（850 passed），含 Spec-0050/T1 新增 3 个针对 `_RUBRIC_TAIL` 语言/长度硬规约的单测。
- grep 锚点：`_RUBRIC_TAIL` 含 T1 语言/长度硬规则关键字（简短 / 中文 / REASON·ISSUES·NEXT）全部命中。
- 真实 render 路径成果判据（走产品 `reviewer.render_decision(kind="code")`，抽「反馈摘要」块）：
  - GREEN 简短中文 fixture：CJK 占比 = 0.52（阈值 ≥ 0.5）、长度 = 106（阈值 ≤ 300）→ 通过。
  - RED 长篇英文 fixture：CJK 占比 = 0.00、长度 = 580 → 不通过（判据能区分「简短中文」与「长英文」，绿非恒真）。
  - 渲染出的 GitHub 风格评论页存 tracked 证据目录：`docs/evidence/spec-0050/comment-green-short-chinese.html` /
    `comment-red-long-english.html`（及配套 `.png`）。

浏览器导航+截图闭环为可选增强（无浏览器可跑成果、判据已在离线段机器可验），非门控红线；
真实 LLM 理由达成度由脚本可选 `OPENAGENTS_E2E_REAL=1` 真实 GitHub 段验证，非默认执行。
