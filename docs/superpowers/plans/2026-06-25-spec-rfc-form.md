# spec 转 rust-RFC 形态(总览先行 + 单 spec 自包含)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 OpenAgents 的 spec 从「Task DAG 骨架 + 每 Task 各写 prose」改成「feature 级 rust-RFC 9 段 prose 为主体,DAG + 文件分配收进 Reference-level」,使任取一个 spec 单独可读、总览先行。

**Architecture:** 数据模型新增组级 `Overview`(9 段);Task 瘦身,只留结构化字段 + frontmatter 里的 `scope`/`acceptance`;正文 parse/render 从「`## T<n>` Task 小节」改为「`## <rust 段名>` 组级段」。校验加「必填段非空 + 跨 spec 裸引用 warning」。skill/README/orchestrator 文案对齐。19 个存量 spec 回填。

**Tech Stack:** Python 3、ruamel.yaml(frontmatter round-trip)、jsonschema(draft 2020-12)、pytest、ruff(行宽 100)。

## Global Constraints

- 提交信息遵循 Conventional Commits;scope ∈ {backend, cli, ci, deps, docs};subject 不以 `RFC-xxxx` 开头(commitlint)。
- Ruff 行宽 100;`ruff check` + `ruff format --check` 必须过。
- Python 函数禁止位置参数(全 `*` 关键字);private(`_` 开头)函数参数禁止默认值,调用方显式传参。
- 代码注释引用 spec id:新代码 `# Spec-NNNN`(本组落地后补);存量 `# Spec-NNNN/T*` 祖父化保留。
- `tasks[].files` **必须**保留为 frontmatter 结构化机器源(为 issue #71 运行期 owner 检查铺路)。
- CI 参照:用 `uv run spec ...` / `uv run pytest`(避免 bare `spec` 跑到别的 worktree 的旧代码)。
- 测试落到 `tests/test_spec_*.py`,沿用现有 `tmp_path` + `_write_group` 模式。

---

### Task 1: 组级 Overview 数据模型 + 正文 parse/render 重写

把组级 9 段 prose 引入 `model.py`,Task 去重 prose、`scope`/`acceptance` 移入 frontmatter,正文按 rust 段名切分。

**Files:**
- Modify: `openagents/spec/model.py`
- Test: `tests/test_spec_model.py`

**Interfaces:**
- Produces:
  - `model.Overview`(frozen dataclass,9 个 str 字段默认 `""`):
    `summary / motivation / guide_level / reference_level / drawbacks / rationale_alternatives / prior_art / unresolved_questions / future_possibilities`
  - `model.Group` 新增 `overview: Overview`(默认 `Overview()`)。
  - `model.Task` 去掉 `motivation/design/interface/tradeoffs/tests/references/open_questions/summary`;保留 `scope: str = ""`、`acceptance: str = ""`(现为 body prose,改为 frontmatter)。
  - `_OVERVIEW_SECTIONS: tuple[tuple[str,str],...]` rust 段标题 → Overview attr,渲染按此序。
  - `render_group` / `load_group` round-trip 覆盖 `overview` 与 task 的 `scope`/`acceptance`。

- [ ] **Step 1: 写失败测试** — 在 `tests/test_spec_model.py` 顶部补 `Overview` import,改 `_sample_group` 带 overview,新增 round-trip 断言。

```python
from openagents.spec.model import Group, Metadata, Overview, RelatesTo, Task

def _sample_overview() -> Overview:
    return Overview(
        summary="一句话讲清这个 feature。",
        motivation="现状 X，问题 Y，所以要改（背景就地复述，不甩引用）。",
        guide_level="当它已存在，这样向人讲解：示例……",
        reference_level="技术方案细节。\n\nTask 分解：T1 改 a.py，T2 改 b.py。",
        rationale_alternatives="备选 A 被否决，因为……",
        future_possilities := "",  # 占位，见下方修正
    )
```

> 注：上面 `future_possilities` 写法仅示意，真实代码用关键字 `future_possibilities=""`。最终测试代码见 Step 3 配套。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_spec_model.py -x -q`
Expected: FAIL（`ImportError: cannot import name 'Overview'`）。

- [ ] **Step 3: 实现 model.py**

要点:
1. 新增 `Overview` frozen dataclass(9 字段,默认 `""`)。
2. `Group` 加 `overview: Overview = field(default_factory=Overview)`。
3. `Task` 删除 `summary/motivation/design/interface/tradeoffs/tests/references/open_questions`;`scope`/`acceptance` 保留为字段(已有)。
4. `_TASK_FM_ORDER` 末尾加 `("scope","scope")`、`("acceptance","acceptance")`(进 frontmatter)。
5. 删 `_PROSE_SECTIONS`/`_HEADING_TO_ATTR`/`_TASK_HEADING_RE`/`_PROSE_HEADING_RE`;新增:

```python
_OVERVIEW_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Summary", "summary"),
    ("Motivation", "motivation"),
    ("Guide-level explanation", "guide_level"),
    ("Reference-level explanation", "reference_level"),
    ("Drawbacks", "drawbacks"),
    ("Rationale and alternatives", "rationale_alternatives"),
    ("Prior art", "prior_art"),
    ("Unresolved questions", "unresolved_questions"),
    ("Future possibilities", "future_possibilities"),
)
_SECTION_BY_HEADING = {h: a for h, a in _OVERVIEW_SECTIONS}
_SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
# 占位注释（spec new 脚手架用）：非空但 _is_blank_prose 视其为空。
_PLACEHOLDER = "<!-- 待填 -->"
```

6. `_render_body(group)`：永远输出 9 个 `## <heading>` 段;空内容输出 `_PLACEHOLDER`。
7. `_parse_body(body)`：按 `## <heading>` 切段,命中 `_SECTION_BY_HEADING` 的存进 dict;返回 `{attr: text}`;`load_group` 据此构 `Overview`(去掉 `_PLACEHOLDER`-only 段，归一为 `""`）。新增 `_strip_placeholder(text)` 工具。
8. `task_from_mapping` 读 frontmatter 的 `scope`/`acceptance`。
9. `render_group`：body 改为 overview 9 段;`load_group` 不再用 prose 覆盖 task(task prose 没了),改为 `overview=...`。

配套最终测试(替换 Step 1 占位):

```python
def test_round_trip_preserves_overview_and_tasks(tmp_path: Path) -> None:
    group = _sample_group()  # 带 _sample_overview() 与一个 scope/acceptance 齐全的 task
    path = _write_group(root=tmp_path, group=group)
    reloaded = model.load_group(path=path)
    assert reloaded.overview == group.overview
    t, o = reloaded.tasks[0], group.tasks[0]
    for attr in ("id","title","status","priority","files","scope","acceptance","depends_on"):
        assert getattr(t, attr) == getattr(o, attr), attr
    assert model.render_group(group=group) == model.render_group(group=reloaded)

def test_body_holds_overview_frontmatter_holds_scope(tmp_path: Path) -> None:
    path = _write_group(root=tmp_path, group=_sample_group())
    text = path.read_text(encoding="utf-8")
    head, body = text.split("\n---\n", 1)
    assert "## Summary" in body and "## Reference-level explanation" in body
    assert "scope:" in head and "acceptance:" in head      # 进 frontmatter
    assert "## T" not in body                                # 不再有 Task 小节
```

同时更新现有 `test_optional_fields_default`（删 `task.tests` 断言，`task.tests` 字段已不存在）、`test_frontmatter_holds_structured_body_holds_prose`（改名/改断言为上面的 body-overview 版）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_spec_model.py -q`
Expected: PASS。

- [ ] **Step 5: lint + 提交**

```bash
uv run ruff check openagents/spec/model.py tests/test_spec_model.py
uv run ruff format openagents/spec/model.py tests/test_spec_model.py
git add openagents/spec/model.py tests/test_spec_model.py
git commit -m "feat(backend): spec 数据模型引入组级 Overview 9 段 + Task 瘦身"
```

---

### Task 2: schema 瘦身 + validate 质量门槛(必填段 + 自包含 warning)

**Files:**
- Modify: `openagents/spec/schema.py`、`openagents/spec/validate.py`
- Test: `tests/test_spec_validate.py`、`tests/test_spec_model.py`(schema 合法性参数化已覆盖)

**Interfaces:**
- Consumes: Task 1 的 `model.Overview` / `model.Group.overview`。
- Produces:
  - `schema._PROSE_KEYS = ("scope", "acceptance")`;`TASK_SCHEMA["required"] = ["id","title","status","priority","files","acceptance"]`。
  - `validate._overview_required_checks(*, groups)` → error(必填段空)。必填段:`summary / motivation / reference_level / rationale_alternatives`。
  - `validate._self_contained_checks(*, groups)` → warning(裸跨 spec 引用)。

- [ ] **Step 1: 写失败测试**

```python
def test_missing_required_overview_section_is_error(tmp_path):
    g = _group_with_overview(reference_level="")   # 必填段留空
    _write(tmp_path, g)
    report = validate(specs_root=tmp_path)
    assert not report.ok
    assert any("Reference-level" in i.message and i.level == "error" for i in report.issues)

def test_bare_cross_spec_ref_is_warning(tmp_path):
    g = _group_with_overview(motivation="详见 Spec-0012 决策 8。")
    _write(tmp_path, g)
    report = validate(specs_root=tmp_path)
    assert report.ok                               # 仅 warning，不破 ok
    assert any(i.level == "warning" and "Spec-0012" in i.message for i in report.issues)

def test_task_without_acceptance_is_schema_error(tmp_path):
    # frontmatter 缺 acceptance → schema required 拦下
    ...
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_spec_validate.py -x -q`
Expected: FAIL。

- [ ] **Step 3: 实现**

`schema.py`:
```python
_PROSE_KEYS = ("scope", "acceptance")
# TASK_SCHEMA properties 保留 scope/acceptance（经 _PROSE_KEYS）；其余重 prose 键删除。
TASK_SCHEMA["required"] = ["id", "title", "status", "priority", "files", "acceptance"]
```
(注:直接在字面量里写 required,勿运行期 mutate。)

`validate.py`:
```python
_REQUIRED_SECTIONS = (("summary","Summary"),("motivation","Motivation"),
                      ("reference_level","Reference-level explanation"),
                      ("rationale_alternatives","Rationale and alternatives"))
_BARE_REF_RE = re.compile(r"Spec-\d{4}\s*(决策|/T)?")  # 简洁起见，命中即提示自包含

def _overview_required_checks(*, groups):
    issues = []
    for g in groups:
        for attr, label in _REQUIRED_SECTIONS:
            if not getattr(g.overview, attr).strip():
                issues.append(ValidationIssue(level=_ERROR,
                    where=f"{g.number}/overview",
                    message=f"必填总览段「{label}」为空（单 spec 自包含、总览先行）"))
    return issues

def _self_contained_checks(*, groups):
    issues = []
    for g in groups:
        for attr, _ in model_overview_items():   # 遍历 9 段
            text = getattr(g.overview, attr)
            for m in _BARE_REF_RE.finditer(text):
                issues.append(ValidationIssue(level=_WARNING,
                    where=f"{g.number}/overview/{attr}",
                    message=f"疑似跨 spec 裸引用 {m.group(0)!r}：确认必要信息已就地复述（issue #69）"))
    return issues
```
在 `validate()` 链里追加这两步。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_spec_validate.py tests/test_spec_model.py -q`
Expected: PASS。

- [ ] **Step 5: lint + 提交**

```bash
uv run ruff check openagents/spec/schema.py openagents/spec/validate.py tests/test_spec_validate.py
uv run ruff format openagents/spec/schema.py openagents/spec/validate.py tests/test_spec_validate.py
git add openagents/spec/schema.py openagents/spec/validate.py tests/test_spec_validate.py
git commit -m "feat(backend): spec 校验加必填总览段 + 跨 spec 裸引用 warning"
```

---

### Task 3: `spec new` 生成 9 段脚手架 + render/mutate/cli 适配

确保 `spec new` 产出含 9 段空模板的组文件;修正因 Task 1 改动而失败的 render/mutate/cli/signpost 测试。

**Files:**
- Modify: `openagents/spec/render.py`(若引用已删 task 字段)、`openagents/spec/mutate.py`、`openagents/spec/cli.py`(多半无需改,验证)
- Test: `tests/test_spec_render.py`、`tests/test_spec_mutate.py`、`tests/test_spec_cli.py`、`tests/test_spec_signpost.py`

**Interfaces:**
- Consumes: Task 1/2。
- Produces: `spec new <slug> --issue --title --summary` 生成的 `.md` 正文含 9 个 `## <rust 段名>` + `<!-- 待填 -->` 占位;`spec validate` 对刚建的空组报必填段 error(预期——提示作者去填)。

- [ ] **Step 1: 写/改失败测试** — `test_spec_mutate.py` 断言新建组 body 含 9 段标题:

```python
def test_new_group_scaffolds_nine_sections(tmp_path):
    path = mutate.create_group(specs_root=tmp_path, slug="demo", title="D",
                               issue=1, summary="一句话", number=None)
    body = path.read_text(encoding="utf-8")
    for h in ("## Summary","## Motivation","## Guide-level explanation",
              "## Reference-level explanation","## Drawbacks",
              "## Rationale and alternatives","## Prior art",
              "## Unresolved questions","## Future possibilities"):
        assert h in body
```

- [ ] **Step 2: 跑全 spec 测试,收集失败**

Run: `uv run pytest tests/test_spec_render.py tests/test_spec_mutate.py tests/test_spec_cli.py tests/test_spec_signpost.py -q`
Expected: 多处 FAIL（旧测试断言 `## T1 · …` / `### Design` 等已废结构）。

- [ ] **Step 3: 实现 + 修测试**

- `render.py`:确认未引用已删 task 字段(应无);若 `_render_tldr` 想展示组级 Summary 段,可由 `group.overview.summary` 取(可选,优先沿用 `metadata.summary`)。
- `mutate.create_group`:无需改(body 9 段由 `model._render_body` 对空 `Overview` 自动产出占位)。
- 修正各测试里对旧 body 结构的断言,改为 9 段/frontmatter scope-acceptance 版。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/ -q`
Expected: PASS（全量）。

- [ ] **Step 5: lint + 提交**

```bash
uv run ruff check openagents/spec tests/test_spec_*.py
uv run ruff format openagents/spec tests/test_spec_*.py
git add openagents/spec tests/test_spec_*.py
git commit -m "feat(cli): spec new 产出 rust-RFC 9 段脚手架，修适配测试"
```

---

### Task 4: skill + references + docs/specs/README 对齐 rust RFC

**Files:**
- Modify: `.claude/skills/spec-driven-development/SKILL.md`
- Modify: `.claude/skills/spec-driven-development/references/task-fields.md`
- Modify: `docs/specs/README.md`
- (无单测;门槛为内容审阅 + 与代码一致)

- [ ] **Step 1: 改 SKILL.md Phase 2**
  - 流程改为:`spec new`(含 9 段脚手架)→ **先写满 9 段组级 RFC 总览(尤其 Summary/Motivation/Reference-level/Rationale)** → 再 `spec add-task` 补 DAG 行(`--files` 互斥、`--acceptance` 必填)。
  - Quality bar 加两条:**① 单 spec 自包含——禁止把理解本 spec 的必要信息留给「见 Spec-NNNN」式裸引用,复述胜过引用;② 想写进正文的「调用方请务必…」软约定,先试改成 frontmatter 字段 / `spec validate` 规则让它无法违反(`files` 互斥即范例,呼应 issue #71)。**
  - 顶部格式横幅追加一行指向 `docs/specs/2026-06-25-spec-rfc-form-design.md`。

- [ ] **Step 2: 改 references/task-fields.md** — 删重 prose 字段说明;新增「组级 Overview 9 段」字段表 + Task 仅 `scope/acceptance` 短 prose(进 frontmatter)。

- [ ] **Step 3: 重写 docs/specs/README.md 对齐 rust RFCs README**
  - 章节:What is a spec / When you need a spec(实质改动才建组) / The spec template(9 段)/ The spec life-cycle(status:pending→in-progress→done;abandoned)/ 工具命令 / 编号规则。
  - 引用 `rust-lang/rfcs` README 为来源(理念 7)。

- [ ] **Step 4: 提交**

```bash
git add .claude/skills/spec-driven-development docs/specs/README.md
git commit -m "docs(docs): skill + README 对齐 rust-RFC 9 段（总览先行+自包含 quality bar）"
```

---

### Task 5: orchestrator 派活 prompt 对齐

**Files:**
- Modify: `openagents/orchestrator.py`（`_DRAFT_RFC_TASK` / `_REFINE_RFC_TASK`）
- Test: `tests/test_orchestrator.py`（若断言 prompt 文案）

- [ ] **Step 1: 查现有测试是否锁 prompt 文案**

Run: `uv run pytest tests/test_orchestrator.py -q` 并 grep `add-task`/`summary` 断言。

- [ ] **Step 2: 改 prompt** — `_DRAFT_RFC_TASK` 改为:`spec new`(必填 `--summary`)→ **先写满 9 段 RFC 总览(自包含,禁裸引用)** → `spec add-task` 补 DAG 行(`--files` 互斥、`--acceptance`)→ `spec validate` + `spec render`。`_REFINE_RFC_TASK` 同步措辞。

- [ ] **Step 3: 跑测试 + lint + 提交**

```bash
uv run pytest tests/test_orchestrator.py -q
uv run ruff check openagents/orchestrator.py && uv run ruff format openagents/orchestrator.py
git add openagents/orchestrator.py tests/test_orchestrator.py
git commit -m "docs(backend): orchestrator 派活 prompt 对齐 rust-RFC 9 段流程"
```

---

### Task 6: 回填 19 个存量 spec 到新形态

把每个 `docs/specs/NNNN-slug.md` 重写为新形态:9 段组级总览(就地复述跨 spec 必要信息) + frontmatter `tasks[]`(结构化 + `scope`/`acceptance`),正文不再有 `## T<n>` 小节。

**Files:**
- Modify: `docs/specs/0001-*.md` … `docs/specs/0023-*.md`(共 19 个组文件)
- Regenerate: `docs/specs/OVERVIEW.md`(`spec render`)、`docs/specs/ARCHITECTURE.md`(`spec graph`)

**Interfaces:**
- Consumes: Task 1–3 落地的新模型 + 校验。

- [ ] **Step 1: 标准化重写规程(每个 spec 一遍)**
  1. 读旧文件的现有 prose(各 Task 的 design/tradeoffs/...)与跨 spec 引用。
  2. 把分散的 Task prose **上提合并**成组级 9 段:Summary/Motivation(背景就地复述,消「见 Spec-NNNN」裸引用)/Guide-level/Reference-level(含 Task 分解表 + DAG)/Drawbacks/Rationale&alternatives/Prior art/Unresolved/Future。无内容的段填 `<!-- 待填 -->` 但**必填四段必须实写**。
  3. frontmatter `tasks[]` 保留 id/title/status/priority/depends-on/relates-to/files;补齐每行 `scope`/`acceptance`。
  4. 单文件 `uv run spec validate` 必须无 error(warning 容许但尽量消)。

- [ ] **Step 2: 分批回填**（建议每 PR-commit 3–5 个 spec,便于回看）
  - 首批先 0023 / 0012(引用最重),建立范例。
  - 可按 issue #69 派并行 subagent(每 agent 一个 spec,只改自己那一个文件——天然满足 files 互斥)。

- [ ] **Step 3: 全量校验 + 重生成派生物**

```bash
uv run spec validate                       # 0 error
uv run spec render                          # 重生成 OVERVIEW.md
uv run spec graph                           # 重生成 ARCHITECTURE.md
git diff --exit-code docs/specs/OVERVIEW.md docs/specs/ARCHITECTURE.md || \
  git add docs/specs/OVERVIEW.md docs/specs/ARCHITECTURE.md
```

- [ ] **Step 4: 提交(分批)**

```bash
git add docs/specs/00XX-*.md
git commit -m "docs(docs): 回填 spec 00XX 到 rust-RFC 9 段总览形态"
```

---

### Task 7: 全链路验证 + 收尾

- [ ] **Step 1: 全量测试 + lint**

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

- [ ] **Step 2: spec 自校验全绿 + 无漂移**

```bash
uv run spec validate          # 0 error
uv run spec render && git diff --exit-code docs/specs/OVERVIEW.md
uv run spec graph  && git diff --exit-code docs/specs/ARCHITECTURE.md
```

- [ ] **Step 3: 端到端启动脚本** — 写 `scripts/e2e-spec-0024-rfc-form.sh`:建临时 specs 根 → `spec new` → 填 9 段 → `add-task` → `validate`/`render`/`graph` 全绿,演示新流程(对标历史 `scripts/e2e-spec-0023-*.sh`)。

- [ ] **Step 4: dogfood 本 feature 的 spec 组** — 用新格式 `spec new` 建本 feature 自己的组(issue #69),9 段写满,Task 行覆盖本计划 7 个任务;`validate` 全绿。

- [ ] **Step 5: 推分支 + 开 PR**

```bash
git push -u origin openagents/issue-69-spec-rfc-form
gh pr create --title "spec 转 rust-RFC 形态：总览先行 + 单 spec 自包含（issue #69）" --body "..."
```

---

## Self-Review

- **Spec 覆盖**:issue #69 三条验收 → Task1/2(自包含校验+9段模型)、Task4/5(skill+orchestrator 流程)、Task6(回填);issue #71 扩展点 → Global Constraints 锁 `tasks[].files` 结构化源 + Task4 quality bar。✓
- **占位扫描**:无 TODO/TBD 残留(Task6 的 `<!-- 待填 -->` 是产品内的合法占位,非计划占位)。✓
- **类型一致**:`Overview` 9 字段名在 Task1/2/3/4 全文一致;`_REQUIRED_SECTIONS` 用同名 attr。Step 1 占位代码里的 `future_possilities := ` 是示意,Step 3 已注明真实关键字 `future_possibilities`。✓
- **风险**:Task1 改动会连锁打挂 render/mutate/cli/signpost 旧测试 → Task3 专门收口跑 `pytest tests/` 全量。
