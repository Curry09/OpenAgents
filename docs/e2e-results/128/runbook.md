# PR #128 端到端说明书（runbook）· Spec-0050 / issue #124

> 本文件是给**独立 executor agent** 照做的可执行说明书。代码已实现完毕，本 runbook 只声明「怎么起、跑什么、看什么算过」。
> executor 请**逐条执行**下面的步骤并把观察/输出/截图固化成证据，最后据「判定点」给出 PASS / FAIL。
> **只读本文件、不改任何实现代码**（`openagents/`、`scripts/`、`tests/` 一律不动）。

---

## 0. 执行形态声明

```
form = cli
```

**为什么是 cli（e2e 规约降级，见 spec frontmatter e2e 块）**：本 PR 是纯 prompt 文本硬化（reviewer 的 `_RUBRIC_TAIL` 加「裁决理由必须一段简短中文」硬规约），**无运行时行为变更、无浏览器可跑成果**。「反馈摘要须为简短中文」这条约束的可验证成果，是**离线确定性**地跑通真实 `render_decision` 渲染路径 + 机器可验证的可读性判据（CJK 占比 ≥ 0.5 且 长度 ≤ 300，GREEN 通过 / RED 长英文不通过），而非需要真 LLM 或浏览器交互的界面闭环。故 executor 的**门控成果 = 离线段真跑全绿**（步骤 A）；浏览器导航+截图闭环（步骤 B/C）为**可选增强**，环境具备 browser MCP 时可做以留视觉存证，**缺失亦不判 FAIL**——判据本身已在离线段机器可验。

**RFC 批准的意图（不可偷换、不得弱化）**：reviewer 的裁决理由（反馈摘要）必须是盯 PR 的人能一眼读懂并据此处理的**一段简短中文**，而非长篇英文堆砌；这一意图由离线段的真实 `render_decision` 渲染路径 + CJK/长度判据（GREEN 通过、RED 反证不通过）机器可验。

---

## 1. 前置与环境

1. **工作目录**：`cd` 到仓库根（本 worktree 根 = `.openagents/worktrees/issue-124`，即含 `openagents/`、`scripts/`、`docs/` 的目录）。以下所有命令都从仓库根执行。
2. **工具集自检（诚实纪律，遵循 end-to-end-ui-screenshots skill）**：确认是否具备浏览器自动化能力——本会话挂载了 `playwright` MCP（工具真名 `mcp__playwright__browser_navigate` / `mcp__playwright__browser_take_screenshot` / `mcp__playwright__browser_evaluate` / `mcp__playwright__browser_console_messages`）与 `chrome-devtools` MCP（`mcp__chrome-devtools__navigate_page` / `take_screenshot` / `evaluate_script` / `list_console_messages`），二者任一即可驱动真实浏览器。
   - 若两者都**客观不可用**（未授权 / 无显示 / MCP 未连接），**不得**用离线段冒充浏览器成果；应按 skill 纪律在证据里明写「因无浏览器自动化，浏览器成果段未执行」这一**阻塞项**，并回退到「系统真实 Google Chrome headless（`--screenshot` 截图 + `--dump-dom` 取渲染后 DOM）」等价真浏览器路径。二者皆不可得才算阻塞，**不得**跳过或以单测顶替。
3. **证据落点（两处都要）**：
   - Spec-0050 成果证据（截图 + 页面）→ tracked 目录 `docs/evidence/spec-0050/`（意图明确要求）。
   - 本 PR 的 e2e 结果汇总 → `docs/e2e-results/128/result.md`（证据闸 `evidence_gate.review_evidence` 读这里对照 RFC 意图门控合并）。

---

## 2. 判据阈值（「简短中文」的机器可验证操作化判据）

来自 `scripts/e2e-spec-0050-review-reason-chinese-readability.sh`（Spec-0050 定稿，不得改动）：

| 判据 | 阈值 | 含义 |
| --- | --- | --- |
| `CJK 占比` = CJK 字符数 / 非空白字符数 | **≥ 0.5** | 主体是中文；用占比而非「全中文」以容许夹带文件路径 / 英文术语（如 `openagents/reviewer.py:42`、`ISSUES`/`NEXT`/`REASON` label） |
| `总长度` = 反馈摘要块 innerText 的字符数 | **≤ 300** | 「一段简短」的上限，够表达结论 + 下一步而不长篇堆砌 |
| console 报错 | **0 条 error** | 页面正常加载、渲染无异常 |

- **CJK 占比公式**（与脚本 `cjk_ratio` 一致）：去掉所有空白字符后，统计落在 `一`(U+4E00) 到 `鿿`(U+9FFF) 区间的字符数除以非空白字符总数。
- **判据 = 占比 ≥ 0.5 **且** 长度 ≤ 300 **且** console 无 error**，三者全满足才算「简短中文」通过。

---

## 3. 步骤 A —— 渲染真实评论页（起页面）

**命令**：

```bash
bash scripts/e2e-spec-0050-review-reason-chinese-readability.sh
```

**这条脚本做什么（executor 需知，勿改脚本）**：
- `[1/3]` 跑 `ruff check` / `ruff format --check` / `pytest -q`（离线确定性护栏）。
- `[2/3]` grep 锚点断言 `openagents/reviewer.py` 的 `_RUBRIC_TAIL` 含 T1 语言/长度硬规则关键字。
- `[3/3]` 用**真实产品代码** `reviewer.render_decision(kind="code")`（不打桩）把两个 feedback fixture 渲染成真实评论 markdown，再包成 GitHub 风格 HTML 页，写入 tracked 证据目录：
  - GREEN（reviewer 遵守新 prompt 后应产出的「一段简短中文」）→ `docs/evidence/spec-0050/comment-green-short-chinese.html`
  - RED（旧式长篇英文坏输出，反证）→ `docs/evidence/spec-0050/comment-red-long-english.html`
  - 两页的「反馈摘要」块都放在 `<div id="feedback-summary">` 里，供浏览器侧抽文本断言。

**期望输出**：
- `[1/3]` `[2/3]` 全绿（无 `✗`、无非零退出）。
- `[3/3]` 打印两行判据自检，形如：
  - `[GREEN 简短中文] CJK 占比=0.52（阈值≥0.5） 长度=106（阈值≤300） → 通过（简短中文）`
  - `[RED   长篇英文] CJK 占比=0.00（阈值≥0.5） 长度=580（阈值≤300） → 不通过（超长/英文）`
- 末尾打印两个 `file://` 参考 URL（GREEN / RED 页），以及给浏览器侧的说明。
- 两个 HTML 文件存在于 `docs/evidence/spec-0050/`。

**判定点 A**：脚本以 0 退出；GREEN 自检「通过」、RED 自检「不通过」（离线侧已证判据能区分两者、绿非恒真）；两个 HTML 页确实生成。任一不满足 → **FAIL**，记录脚本 stderr。

> 注意（降级后）：这一步「离线段真跑全绿 + 真实 render 路径判据（GREEN 通过 / RED 不通过）」**就是本 cli 形态的门控成果**。步骤 B/C 的浏览器闭环为可选视觉存证，环境无 browser MCP 时可跳过，不判 FAIL。

---

## 4. 步骤 B —— GREEN 浏览器成果闭环（可选视觉存证）

> 降级后：本步为**可选增强**，非门控红线。环境具备 browser MCP 时做以留视觉截图；缺失则跳过并在 `result.md` 据实标注，不判 FAIL。

用 `playwright` MCP（或 `chrome-devtools` MCP）对 GREEN 页走完整闭环。GREEN 页 URL = 步骤 A 打印的 `file://<repo>/docs/evidence/spec-0050/comment-green-short-chinese.html`。

**B1. 导航**
- 请求：`browser_navigate` 打开 GREEN 页 `file://` URL。
- 期望：页面成功加载，标题「评审评论（简短中文·应通过）」，可见「## 评审闸裁决」抬头、`❌ REWORK`、以及「反馈摘要」块。

**B2. 截图存证**
- 请求：`browser_take_screenshot`，`filename` 传 `comment-green-short-chinese.png`。
- **落点纪律（executor 必做）**：playwright/chrome-devtools 的截图默认写到各自 MCP 的 output 目录，未必落在仓库里。执行后**核实** `docs/evidence/spec-0050/comment-green-short-chinese.png` 确实存在且已更新——若 MCP 把文件写到别处，用 shell 把它**复制到** `docs/evidence/spec-0050/`（tracked 证据目录，意图明确要求）并覆盖既有同名截图。截图不落到该 tracked 目录 = 证据未固化 = 该步不算过。
- 期望：截图肉眼可见「反馈摘要」块是一段能一眼读懂的简短中文（`ISSUES` / `NEXT` / `REASON` 三行简短中文，含少量文件路径 / 英文 label）。
- 判定点 B2：`docs/evidence/spec-0050/comment-green-short-chinese.png` 生成 / 更新，内容是中文反馈摘要，非空白 / 非报错页。

**B3. 抽「反馈摘要」块文本 + 判据断言**
- 请求：`browser_evaluate` 在页面上下文执行，取渲染后 DOM 的反馈摘要文本并算判据。示例脚本（JS）：

  ```js
  () => {
    const t = document.getElementById('feedback-summary').innerText;
    const nonspace = [...t].filter(c => !/\s/.test(c));
    const cjk = nonspace.filter(c => c >= '一' && c <= '鿿').length;
    return {
      text: t,
      length: t.length,
      cjkRatio: nonspace.length ? cjk / nonspace.length : 0,
    };
  }
  ```
- 期望：返回 `cjkRatio ≥ 0.5` **且** `length ≤ 300`。**基线实测**（本 runbook 用真实 `render_decision` 路径核过）GREEN 反馈摘要 `length = 106`；CJK 占比在**浏览器 DOM `innerText`** 上实测 `≈ 0.515`（离线 python `cjk_ratio` 因换行/抽取差异打印 `0.52`）——两者均 `≥ 0.5`，你用上面这段 `browser_evaluate` 脚本从真实 DOM 取到的值应落在此量级且仍满足阈值；以你实测的浏览器值为准记录。
- 判定点 B3：`cjkRatio ≥ 0.5 && length ≤ 300`。不满足 → **FAIL**，把实测 `text / length / cjkRatio` 记进证据。

**B4. console 无报错**
- 请求：`browser_console_messages`（传 `level: "error"` 只看 error 级；或 chrome-devtools `list_console_messages`）。
- 期望：无 `error` 级别消息。
- 判定点 B4：0 条 console error。有 error → **FAIL**，记录报错原文。

---

## 5. 步骤 C —— RED 反证浏览器闭环（可选视觉存证）

> 降级后：同步骤 B 为**可选增强**，非门控红线。RED 反证的判据区分能力已在步骤 A 离线段机器可验（RED 自检判不通过）。

对 RED 页 `file://<repo>/docs/evidence/spec-0050/comment-red-long-english.html` 重复 B1–B4 的**同一套**判据（同阈值、同 `browser_evaluate` 脚本），但**期望结论相反**。

**C1. 导航**：`browser_navigate` 打开 RED 页；标题「评审评论（长篇英文·应不通过）」。

**C2. 截图**：`browser_take_screenshot`，`filename` 传 `comment-red-long-english.png`，同 B2 落点纪律**核实 / 复制到** `docs/evidence/spec-0050/comment-red-long-english.png`。肉眼可见「反馈摘要」块又长又是英文。

**C3. 同判据断言，应判不通过**：用 B3 **完全相同**的 `browser_evaluate` 脚本抽 `#feedback-summary` 文本。
- 期望：`cjkRatio ≥ 0.5 && length ≤ 300` 为 **false**。**基线实测**（真实 `render_decision` 路径核过，浏览器 DOM `innerText`）RED 反馈摘要 `cjkRatio = 0.00`（全英文）、`length = 580`（超长）——两条判据同时不满足。
- **判定点 C3（RED 反证，关键）**：同一判据对 RED 页**必须判不通过**。若 RED 也「通过」，说明判据不能区分「简短中文」与「长篇英文」、绿是恒真的假绿 → **整体 FAIL**（这正是本步骤要防的：证明步骤 B 的绿有意义）。

**C4. console**：RED 页也不应有 console error（页面本身正常，只是内容是坏样本）。

---

## 6. 证据固化

executor 完成 B/C 后：

1. **截图 + 页面**已在 `docs/evidence/spec-0050/`：
   - `comment-green-short-chinese.png` / `.html`
   - `comment-red-long-english.png` / `.html`
2. 写 / 更新 `docs/e2e-results/128/result.md`，至少含：
   - 本 PR / spec / issue 标识（PR #128、Spec-0050、issue #124）与 `form: cli`。
   - **被验证的意图**（原文）：reviewer 裁决理由（反馈摘要）在 GitHub PR 评论里必须是盯 PR 的人一眼读懂并据此处理的一段简短中文。
   - 一张结果表：GREEN 与 RED 各自的 `实测 CJK 占比 / 实测长度 / console error 数 / 判据结论（通过·应通过 / 不通过·应不通过）`，附截图相对链接。
   - 浏览器驱动方式的**诚实说明**：用了 playwright MCP / chrome-devtools MCP / 还是回退到系统真实 Chrome headless；截图与 DOM 文本均来自**真实浏览器渲染**，非自动化测试或日志顶替。
   - **fixture 分层诚实标注**：本段 feedback 是「reviewer 遵守新 prompt 后应产出」的代表性 fixture，验证的是「真实 `render_decision` 渲染路径 + 浏览器可读性判据」这条链路与判据本身；真实 LLM 在新 prompt 下**是否真的**产出简短中文，由步骤 D（可选真实成果段）验证。

---

## 7. 步骤 D —— 可选真实成果段（`OPENAGENTS_E2E_REAL=1`，非默认）

**默认不跑**（非 hermetic，需真 GitHub 仓库 + `gh` 登录 + 真 claude backend，会真实建 PR / 评论 / 跑 reviewer）。仅当要验「真实 LLM 在新 prompt 下的实际产出达成度」时执行：

```bash
OPENAGENTS_E2E_REAL=1 bash scripts/e2e-spec-0050-review-reason-chinese-readability.sh
```

步骤（脚本会打印同款指引）：
1. 在 scratch 仓库造一个「有明显缺陷」的 PR（如某函数缺空输入边界、删了在用接口未改调用方）。
2. 跑一次**真 reviewer**（code 闸，真 backend）拿到真实 REWORK feedback → `render_decision` → 经 orchestrator / identity 贴到**真实 GitHub PR**。
3. 用 `browser_navigate` 打开该 PR 页、定位「## 评审闸裁决」评论、`browser_take_screenshot` 存 `docs/evidence/spec-0050/`、`browser_evaluate` 抽反馈摘要文本断言 `CJK 占比 ≥ 0.5 且 长度 ≤ 300`、console 无 error。
4. 对照（改前基线）：同类 PR 的反馈摘要常是长篇英文（CJK 占比低 / 超长）——这才是本 feature 治的病。

判定点 D（若执行）：真实 PR 评论的「反馈摘要」块在浏览器里满足判据。若真实 LLM 仍偶发长英文，据实记录（prompt 硬化非零违反，属已知上限，见 Spec-0050 Drawbacks），不掩盖。

---

## 8. 整体判定（PASS / FAIL 汇总）

**门控项（A）满足即 PASS；B/C 为可选增强**：

- [ ] A（门控）：`bash scripts/e2e-spec-0050-review-reason-chinese-readability.sh` 以 0 退出；离线段 ruff+format+pytest 全绿、grep 锚点命中；真实 `render_decision` 路径 GREEN 自检通过、RED 自检不通过；两 HTML 页生成落 tracked `docs/evidence/spec-0050/`。
- [ ] 证据：`docs/e2e-results/128/result.md` 写全上述实测值 + 诚实说明。
- [ ]（可选）B/C：环境具备 browser MCP 时，对 GREEN/RED 页走浏览器导航 + 截图 + `browser_evaluate` 判据复核，留视觉存证；缺失则据实标注跳过。

**判定红线（降级后）**：门控成果是**离线段（步骤 A）真跑全绿 + 真实 render 路径判据 GREEN 通过 / RED 反证不通过**——纯 prompt 文本改动无浏览器可跑成果，判据已在离线段机器可验，故浏览器闭环（B/C）缺失**不判 FAIL**。仅当步骤 A 未真跑 / 未全绿，或用「grep 到 rubric 文本」之外的空口顶替离线判据 → 判 FAIL。
