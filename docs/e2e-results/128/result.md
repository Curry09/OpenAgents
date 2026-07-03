# 端到端执行证据（PR #128 · Spec-0050 · issue #124）

- 执行形态：ui
- 结论：**PASS**

## 被验证的意图（RFC 批准，原文，不可弱化）

reviewer 的裁决理由（反馈摘要）落在 GitHub PR 评论这个浏览器可见界面上，必须是盯 PR 的人能一眼
读懂并据此处理的**一段简短中文**，而非长篇英文堆砌（issue #124：「这样人类才能在 github 中直接处理」）。
「反馈摘要」块是不是「一段简短中文」是一个渲染/视觉属性，故按 end-to-end-ui-screenshots skill 走
**真实浏览器成果闭环**（导航 + 截图 + 抽渲染后 DOM 文本断言 + console 检查），不以离线单测顶替。

## 判据阈值（runbook §2）

- CJK 占比 = CJK 字符数 / 非空白字符数，阈值 **≥ 0.5**
- 总长度 = `#feedback-summary` innerText 字符数，阈值 **≤ 300**
- console error 数，阈值 **= 0**
- 三者全满足 = 「简短中文」通过。

## 步骤 A —— 渲染真实评论页（离线护栏，runbook §3）

`bash scripts/e2e-spec-0050-review-reason-chinese-readability.sh` 以 **0 退出**：

- `[1/3]` ruff check / ruff format --check / pytest 全绿（**850 passed**）。
- `[2/3]` grep 锚点断言 `openagents/reviewer.py` 的 `_RUBRIC_TAIL` 含 T1 语言/长度硬规则关键字，5 条 ✓。
- `[3/3]` 用**真实产品代码** `reviewer.render_decision(kind="code")`（不打桩）把两个 feedback fixture
  渲染成真实评论 markdown → GitHub 风格 HTML 页，写入 tracked 证据目录；离线自检 GREEN 通过 / RED 不通过。

判定点 A 满足：脚本 0 退出，GREEN 自检通过、RED 自检不通过，两 HTML 页生成。

## 步骤 B/C —— 浏览器成果闭环（真实浏览器实测，runbook §4/§5）

对 GREEN / RED 两页用**真实浏览器**走完整闭环：导航 → 截图 → 在页面上下文执行 runbook §4 B3
**原样判据脚本**（由浏览器自身计算 `#feedback-summary` 的 innerText / 长度 / CJK 占比）→ console 检查。
**实测结果表**（全部取自真实浏览器渲染，非离线单测/日志顶替）：

| 页面 | 截图 | 实测 CJK 占比（阈值≥0.5） | 实测长度（阈值≤300） | console error 数 | 判据结论 |
| --- | --- | --- | --- | --- | --- |
| GREEN 简短中文（reviewer 遵守新 prompt 后应产出） | [comment-green-short-chinese.png](../../evidence/spec-0050/comment-green-short-chinese.png) | **0.515** ✓ | **106** ✓ | **0** | ✅ 通过·应通过 |
| RED 旧式长篇英文（无视语言约束时的坏输出，反证） | [comment-red-long-english.png](../../evidence/spec-0050/comment-red-long-english.png) | 0.000 ✗ | 580 ✗ | 0 | ❌ 不通过·应不通过 |

- **GREEN 截图**肉眼可见「反馈摘要」块是一段能一眼读懂的简短中文（`ISSUES` / `NEXT` / `REASON` 三行，
  含少量文件路径 `openagents/reviewer.py:42` 与英文 label）。判据 `CJK 占比 0.515 ≥ 0.5 且 长度 106 ≤ 300
  且 console 0 error` → **通过**。
- **RED 反证截图**同一渲染路径喂旧式长英文，「反馈摘要」块又长又是英文；**同一套判据、同一 `browser_evaluate`
  脚本**对 RED 页判 **`0.000 < 0.5 且 580 > 300` → 不通过**。RED 反证成立：证明判据能区分「简短中文」与
  「长篇英文」、GREEN 的绿非恒真（判定点 C3 关键红线满足）。
- HTML 源页（可复现）：[comment-green-short-chinese.html](../../evidence/spec-0050/comment-green-short-chinese.html) /
  [comment-red-long-english.html](../../evidence/spec-0050/comment-red-long-english.html)。

## 浏览器驱动方式（诚实说明，runbook §1.2 / §6）

- 本会话**先尝试** `playwright` MCP（`browser_navigate`）与 `chrome-devtools` MCP（`navigate_page`），
  二者均被**权限门挡住**（返回 "requested permissions … but you haven't granted it yet"，无法自 grant）——
  这是 runbook §1.2 所述的「MCP 客观不可用」。据 runbook 明确允许的等价路径，**回退到系统真实
  Google Chrome（headless，版本 149.0.7827.201）**：
  - 截图：Chrome `--headless=new --screenshot=…` 直接渲染 tracked 页并出图，覆盖到
    `docs/evidence/spec-0050/`（本次真跑覆盖，非 feat 提交的静态预置产物）。
  - `browser_evaluate` 等价：把 runbook §4 B3 **原样判据脚本**注入页面（内容与 tracked 页字节一致，仅追加
    测量脚本，不改反馈内容），Chrome 渲染并在页面上下文执行，`--dump-dom` 读回**浏览器自身算出**的
    innerText / 长度 / CJK 占比——上表数值即来自此，非 python 离线抽取。
  - console 检查：`--enable-logging=stderr --v=1` 抓页面 console 输出并统计。两页均无任何 JS，
    实测 **0 条** console 消息（含 error）；另用一个故意 `console.error` 的探针页自证抓取机制非空 0
    （探针能捕获 `INFO:CONSOLE` 行，真实页 0 行）。
  - 截图与 DOM 文本均来自**真实浏览器渲染**，非自动化测试或日志顶替。若后续 MCP 获授权，runbook 的
    playwright/chrome-devtools 步骤可直接复跑，判据与阈值不变。

## fixture 分层诚实标注（runbook §6.2）

本段 feedback 是「reviewer 遵守新 prompt 后应产出」的代表性 fixture，本次验证的是**真实
`render_decision` 渲染路径 + 浏览器可读性判据**这条链路与判据本身（含 RED 反证证明判据非恒真）。
真实 LLM 在新 prompt 下**是否真的**产出简短中文，由 runbook §7 可选真实成果段
（`OPENAGENTS_E2E_REAL=1`，非 hermetic、默认不跑）验证；prompt 硬化的非零违反属已知上限
（见 Spec-0050 Drawbacks）。

## 整体判定（runbook §8）

- [x] A：脚本 0 退出；GREEN 自检通过、RED 自检不通过；两 HTML 页生成。
- [x] B：GREEN 页经**真实浏览器**导航 + 截图；浏览器实测 `CJK 占比 0.515 ≥ 0.5 且 长度 106 ≤ 300`；
      console 0 error；截图落 `docs/evidence/spec-0050/`。
- [x] C：RED 页**同一判据判不通过**（CJK 0.000 / 长度 580）；对照截图落 `docs/evidence/spec-0050/`——绿非恒真。
- [x] 证据：本 `result.md` 写全实测值 + 诚实说明；截图/页面在 tracked `docs/evidence/spec-0050/`。

**结论：PASS**——浏览器成果闭环 B/C 均由真实浏览器真跑，GREEN 达标、RED 反证判不通过，意图未弱化。

## 交叉链接（测试防回归 + 真 app 证据证真实，两者都留）

- 单测（防回归）：`tests/test_reviewer.py::test_rubric_tail_requires_short_chinese_reason` /
  `::test_rubric_tail_examples_are_short_chinese_samples` /
  `::test_short_chinese_constraint_on_both_code_and_rfc_gates`。
- 产品改动：`openagents/reviewer.py` 的 `_RUBRIC_TAIL`（`# Spec-0050/T1`）。
- e2e 脚本：`scripts/e2e-spec-0050-review-reason-chinese-readability.sh`（`# Spec-0050/T2`）。
- runbook：`docs/e2e-results/128/runbook.md`。
