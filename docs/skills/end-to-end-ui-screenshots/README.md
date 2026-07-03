<!-- Spec-0044/T4：skill 目录索引 + 人工安装说明 + 目标仓库 runbook 指引。 -->

# end-to-end-ui-screenshots · 端到端跑真 app 并截图（反惰性）

一份**判断/纪律**层 skill，专治「宣称跑了 e2e / 截了图，其实没有」。核心主张：**产品对外行为的改动，验证要有真 app 跑出来的 tracked 证据**——UI 可见 → 截图；UI 不可见但改产品行为 → 真实运行日志文本；纯内部实现 → 相称测试即可。不许拿自动化测试 / 后端日志顶替真 app 证据，不许拿「慢 / flaky / 投入产出比」当跳过借口，真跑不起来就诚实报阻塞。

> 背景与设计依据见 `docs/specs/0044-e2e-real-app-screenshot-evidence-skill.md`（issue #113）。

## 目录结构

| 文件 | 作用 |
|---|---|
| `SKILL.md` | skill 原文：核心原则 + 反惰性 rationalization 表 + red flags + 工具无关通用流程 + 合格证据判据 + 完成判据。**原样移植，别重写**。 |
| `references/north-coder.md` | 项目专属 runbook **范例**（north-coder 的端口 / 二进制 / env）。 |
| `references/_runbook-template.md` | runbook **填空模板**：把「通用方法（SKILL.md，不动）vs 项目专属命令」两分区固化，供每个目标仓库照抄结构。 |
| `examples/reference-app.html` | 自包含最小参考页：点击按钮 → 出现「已生效」文案。供浏览器自演示段取证（`file://` 打开，不碰生产端口/数据）。 |

## 在 OpenAgents 里它如何生效（无需安装即已起效）

本仓库把这套判断的核心纪律**硬化进了 in-code 面**，不依赖任何 `.claude/` 写入：

- **派单 prompt**（`openagents/orchestrator.py`，Spec-0044/T3）：被派 agent 的实现任务里带三分类取证判断 + 反测试顶替 + 诚实报阻塞 + 指向本目录原文。
- **reviewer rubric**（`openagents/reviewer.py`，Spec-0044/T2）：PR 若声称验证过某产品对外行为却无 tracked 证据 → 判 REWORK，理由「宣称验证过但无证据」。

## 人工安装进 `.claude/skills/`（可选；agent 不执行此步）

若希望 `claude` 直接把它当作**项目原生 skill** 加载（按 `description` 关键词自动触发），把本目录拷进 `.claude/skills/`：

```sh
cp -r docs/skills/end-to-end-ui-screenshots .claude/skills/
```

> ⚠️ 这一步是**人工操作**。本环境有硬约束：agent 禁止写入 `.claude/`，故此步不由 agent 执行。未安装时，判断仍经由上面的 in-code prompt/rubric 生效，只是不走 `claude` 原生 skill 触发。

## 目标仓库 runbook 指引

通用方法（`SKILL.md`）工具无关、**一个字都别改**。每个被 OpenAgents 服务的目标仓库照 `references/_runbook-template.md` 的结构，为自己补一份 runbook（起服务 / 端口 / 驱动 UI 的**具体命令**），范例见 `references/north-coder.md`：

```sh
cp docs/skills/end-to-end-ui-screenshots/references/_runbook-template.md \
   docs/skills/end-to-end-ui-screenshots/references/<你的项目>.md
# 然后把模板里的 <...> 占位替换成本项目真实的端口 / 启动命令 / 驱动步骤
```

## 端到端验证脚本

```sh
bash scripts/e2e-spec-0044-e2e-screenshot-skill.sh
```

- **离线确定性段**（默认执行）：ruff + pytest + grep 锚点（SKILL.md 原文锚点、reviewer.py 无证据=REWORK 字样、orchestrator.py 三分类判断字样）。
- **浏览器自演示段**（需 browser MCP）：对 `examples/reference-app.html` 走 `navigate → interact → screenshot → console/network 断言 → RED 反验 → 证据入 docs/evidence/spec-0044/` 闭环；无 browser MCP 时诚实报阻塞。
