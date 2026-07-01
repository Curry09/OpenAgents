# OpenAgents

**RFC 驱动的多 Agent 协作框架。** 让 AI agent 替你完成「从 issue 到 PR」的完整工程闭环——先把要做的事写成 RFC、由人评审批准,再派一个 coding agent(如 Claude Code)按 RFC 写代码、开真实 GitHub PR,并根据评审评论与 CI 结果自动迭代,直到合并。

人退到宏观位置:你审 RFC、审 PR、按一次 release;**细节交给 agent**。

---

## 前置条件

- **Python ≥ 3.12** 与 [uv](https://docs.astral.sh/uv/)
- **已鉴权的 [`gh` CLI](https://cli.github.com/)**:首次用 `gh auth login` 登录,用 `gh auth status` 确认通过。
  > OpenAgents **不存储任何 token**,鉴权全部委托给 `gh`。
- **已安装的 [`claude` CLI](https://docs.claude.com/claude-code)**(默认 coding 后端)

---

## 安装

```bash
uv tool install --from . openagents
```

装好后 `openagents` 在任意目录可用。改了源码后用 `--force` 重装更新:

```bash
uv tool install --force --from . openagents
```

> 注意:`openagents` 是一份 uv tool 快照——改了代码不重装,命令会跑旧代码。

---

## 用法

日常只要三条命令——`init` 绑定、`issue` 立需求、`vigil` 守全程。

```bash
openagents init                 # 绑定当前目录到仓库
openagents issue "你的需求"      # 提 issue(自动打 openagents 发现标签)
openagents vigil                # 守夜人:发现 → 派单 → 开 PR → 守候迭代
```

### `init` —— 绑定项目

```bash
openagents init
```

把当前目录绑定 / 初始化为 OpenAgents 项目,并确保流程标签就位。缺 git / 远端时会提示你新建。除 `board` 外的所有命令执行前都会先做这项绑定预检。

### `issue` —— 立一个需求

```bash
openagents issue "支持导出 CSV"        # 建前先复述对齐、请你确认
openagents issue "修复登录超时" --yes  # 跳过确认(供自动化)
```

往当前仓库提一个 issue,自动打上 `openagents` 发现标签,这样才能被 `vigil` 发现、派单。也可以直接在 GitHub 网页提 issue,但需手动打上 `openagents` 标签。

常用选项:`--body <正文>`、`--label <标签>`(可重复)、`--yes`(跳过复述确认)。

### `vigil` —— 守夜人,一条命令跑完全程

`vigil` 让 OpenAgents **无人值守**地跑完整闭环:循环「发现带标签的新 issue → 派单求解 → 起草 RFC 开 PR → 守候 PR 的评论 / CI → 迭代」,人只需要审 RFC、审 PR。

```bash
openagents vigil                          # 默认按 openagents 标签门控,间隔 60s 循环
openagents vigil --once                   # 只跑一轮后退出
openagents vigil --label bug --label p0   # 自定义发现标签门控(可重复)
openagents vigil --hold spec              # 分级监督:在 RFC 批准前停下等人
openagents vigil --hold spec,merge        # 可组合:spec(RFC 批准前停)/ merge(合并前停)
```

特性:标签门控的 issue 发现、「发现段 + 守候段」两段循环、单 issue 错误隔离(单轮出错不拖垮整个循环)、对已关闭 PR/issue 识别终止信号、崩溃后从孤儿 run 恢复、`gh` 瞬时错误指数退避重试。

全新仓库可以直接 `vigil`(无需先 `init`)——进主循环前会自举一次流程标签,使无人值守进程能自恢复。

---

## 搭配 Claude Code 使用(推荐)

OpenAgents 默认的 coding 后端就是 **[Claude Code](https://docs.claude.com/claude-code)**,两者天然互补:

- **用 Claude Code 开发 OpenAgents 本身,用 OpenAgents 跑闭环**。本项目正在「用自己开发自己」(dogfooding),在仓库里用 Claude Code 交互式地改 RFC / 写代码,再让 `openagents vigil` 无人值守地把 issue 推进到 PR。
- **交互式补位,自治式兜底**。需要人紧密参与、边想边改的部分交给 Claude Code 面对面协作;明确成型、可无人值守推进的 issue 交给 `vigil` 自动跑。
- **确保 `claude` CLI 已登录可用**:OpenAgents 会调用它作为 coding agent,先用 `claude` 跑通一次交互确认鉴权无误,再启动 `vigil`。

> ⚠️ `vigil` / `issue` 会**真的**调用 Claude 改代码、用 `gh` 开真 PR / 发评论。**建议先在练习仓库上试。**
