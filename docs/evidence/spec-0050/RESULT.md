# Spec-0050 浏览器成果 e2e 证据：评审评论「反馈摘要」为简短中文（issue #124）

> 本目录由 `scripts/e2e-spec-0050-review-reason-chinese-readability.sh` 渲染页面 + agent 用真实浏览器
> 驱动截图/断言产出。成果 = 「GitHub PR 评论的『反馈摘要』块文字可读性」这一**浏览器可见属性**
> （issue #124：「这样人类才能在 github 中直接处理」），故按 end-to-end-ui-screenshots skill 走真前端 + 截图。

## 被验证的产品成果

T1 把「面向人类的裁决理由（REASON/ISSUES/NEXT）必须用一段简短的中文」写进 reviewer 的输出格式硬规约
（`openagents/reviewer.py` 的 `_RUBRIC_TAIL`，code/rfc 两闸共享）。成果落在渲染出的 PR 评论「反馈摘要」块：
它是不是「盯 PR 的人一眼读懂」的简短中文，是一个渲染/视觉属性——正适合「渲染页面 + 截图 + 文本断言」验证。

## 真实浏览器证据（GREEN + RED 反证）

用**真实**产品代码 `reviewer.render_decision(kind="code")` 把两个 feedback fixture 渲染成真实评论 markdown →
包成 GitHub 风格 HTML 页 → **真实浏览器（headless Google Chrome）** 打开、截图、抽渲染后 DOM 的
`#feedback-summary` innerText 算「CJK 占比 + 长度」判据：

| 页面 | 截图 | 反馈摘要 innerText | CJK 占比（≥0.5） | 长度（≤300） | 判据 |
| --- | --- | --- | --- | --- | --- |
| GREEN 简短中文（reviewer 遵守新 prompt 后应产出） | [comment-green-short-chinese.png](comment-green-short-chinese.png) | 简短中文，含少量文件路径/英文 label | **0.515** | **106** | ✅ 通过 |
| RED 旧式长篇英文（无视语言约束时的坏输出） | [comment-red-long-english.png](comment-red-long-english.png) | 长篇英文论证 | 0.00 | 580 | ❌ 不通过 |

> 上表 CJK 占比取自**浏览器自身计算的 `#feedback-summary` innerText**（GREEN 0.515）；离线脚本自检
> 因换行/抽取方式差异打印 0.52，二者均满足 ≥0.5，结论一致。executor 真跑固化的完整实测值表与判定见
> [`docs/e2e-results/128/result.md`](../../e2e-results/128/result.md)（证据闸读取的门控文件，结论 PASS）。

- **GREEN 截图**肉眼可见「反馈摘要」块是一段能一眼读懂的简短中文（`ISSUES/NEXT/REASON` 三行简短中文）。
- **RED 反证截图**同一渲染路径喂旧式长英文，「反馈摘要」块又长又是英文，同一判据判**不通过**——证明绿非恒真、
  判据能区分「简短中文」与「长篇英文」，闭环成立。
- HTML 源页（可复现）：[comment-green-short-chinese.html](comment-green-short-chinese.html) /
  [comment-red-long-english.html](comment-red-long-english.html)。

## 诚实说明（工具与分层）

- **浏览器驱动方式**：本环境的 playwright / chrome-devtools **MCP 工具被权限门挡住**（未获授权，无法自 grant）。
  按 skill「Playwright 脚本里 page.screenshot 亦可」的等价路径，改用**系统真实 Google Chrome（headless）**
  渲染同两页并 `--screenshot` 截图、`--dump-dom` 取渲染后 DOM 做 `#feedback-summary` 文本判据——仍是**真浏览器
  渲染出的真截图与真 DOM**，非自动化测试/日志顶替。若后续 MCP 获授权，脚本内 runbook 的 playwright 步骤可直接复跑。
- **fixture 分层（真实理由文本不可 hermetic）**：本段 feedback 是「reviewer 遵守新 prompt 后应产出」的代表性
  fixture，验证的是 **render 路径 + 浏览器可读性判据**这条链路与判据本身。真实 LLM 在新 prompt 下**是否真的**产出
  简短中文，由脚本可选 `OPENAGENTS_E2E_REAL=1` 真实成果段（造 scratch PR、跑真 reviewer、贴真 GitHub PR、打开 PR
  页截图）验证；默认不执行（非 hermetic、需真 claude + 真 GitHub）。

## 交叉链接（测试防回归 + 真 app 证据证真实，两者都留）

- 单测（防回归）：`tests/test_reviewer.py::test_rubric_tail_requires_short_chinese_reason` /
  `::test_rubric_tail_examples_are_short_chinese_samples` /
  `::test_short_chinese_constraint_on_both_code_and_rfc_gates`。
- 产品改动：`openagents/reviewer.py` 的 `_RUBRIC_TAIL`（`# Spec-0050/T1`）。
- e2e 脚本：`scripts/e2e-spec-0050-review-reason-chinese-readability.sh`（`# Spec-0050/T2`）。
