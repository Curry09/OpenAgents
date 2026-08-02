---
number: "0074"
title: forge 分发层与 Gitea driver：把 GitHub 耦合收敛为可换轨的托管平台接缝
issue: 0
slug: gitea-forge-driver
summary: OpenAgents 的全部平台操作走 utils/github.py（gh CLI 薄封装），编排层（vigil/stages/gates/context/identity/release/cli/backfill）以模块函数形式消费——这既是耦合点也是天然接缝。本 spec 新增 utils/forge.py 分发模块（读 .openagents/openagents.yml 新增的 forge 段选 driver，缺省 github、存量用户零感知）与 utils/gitea.py driver（github.py 同名公共面对 Gitea /api/v1，stdlib urllib 零新依赖），消费方仅改 import 行为 `from openagents.utils import forge as github`（alias-import，数百个调用点零改动）。语义映射：checks→commit combined status、mergeable→bool+UNKNOWN 收敛、draft→WIP 标题前缀、blocked_by→issue dependencies、update_branch→POST /pulls/{index}/update、Closes #N→Gitea 原生 closing keywords、鉴权→token 环境变量（延续「不存 token」纪律，gh 委托改 env 委托）。merger 提示词内硬编码的 gh 命令参数化为 $merge_command/$verify_command 占位符，由 stages.merge 经 driver 提供的命令文本注入；Gitea 侧命令是新增的隐藏 CLI 子命令 `openagents merge-pr --pr N`（token 处理留在 driver 内，不进提示词）。首个消费方是 auto-designer（自进化 harness 编排，其基建在本地 Gitea，见其 spec-0032）。
e2e:
  intent: 证明「forge 可换轨」在离线确定性链路上成立——forge 缺省回落 github（存量零回归）；forge=gitea 时全部公共面函数打到 Gitea REST 且语义映射正确（checks/mergeable/draft/deps/merge/update/标签幂等）；merger 提示词无 gh 字面量、merge/verify 命令按 forge 注入；配置校验拒绝 forge=gitea 缺 gitea 段。
  method: "形态：纯后端（forge 分发 + gitea driver + 配置段 + 提示词参数化），无前端可导航；不触真实 LLM/网络/仓库，全部离线确定性测法（沿用 Spec-0071 同款）：\n1. 针对性 pytest：\n   - test_forge.py：缺省 github 委托、configure(gitea) 后委托 gitea、常量（DISCOVERY_LABEL 等）import 时零 IO 直出、reset 后惰性发现走 .openagents/openagents.yml（tmp_path 造仓）、坏 YAML fail-open 回落 github。\n   - test_gitea_driver.py：假 HTTP 层（monkeypatch gitea._http）覆盖全部公共面函数的请求形状（method/path/body）与响应解析；语义映射逐条——combined status 三态归类+零 status 计数 0、mergeable bool→MERGEABLE/CONFLICTING/缺失→UNKNOWN、WIP 前缀 is_draft/mark_ready 往返、dependencies GET/POST 形状与 404→[]、update 422 已最新→False、merge 已合并幂等、标签 add/remove 幂等容错、create_issue 标签名→id 解析、瞬时 5xx 退避重试。\n   - test_agent_config.py 追加：forge/gitea 段 schema、forge=gitea 缺 gitea 段报错、缺省 forge=github。\n   - test_agents_merger.py 更新：PROMPT 含 $merge_command/$verify_command、无 gh 字面量。\n   - test_stages.py（如有）/新增断言：stages.merge 注入 merge_command/verify_command。\n2. grep 锚点：forge.py 首行 '# Spec-0074/T1'；gitea.py 首行 '# Spec-0074/T2'；vigil/stages/gates/context/identity/release/cli/backfill 的 import 行均为 'from openagents.utils import forge as github' 形态；agents/merger.py 无 'gh pr merge' 字面量。\n3. ruff check + ruff format --check 全绿。\n4. 对真实 Gitea 1.22（消费方 auto-designer 的 deploy/gitea 实例）手工冒烟一轮：建 issue→打 label→开 PR→merge→issue 自动关（消费方 spec-0032/T5 的验收项，不进本仓 CI）。\n脚本：scripts/e2e-spec-0074-gitea-forge-driver.sh（ruff + 上述 pytest + grep 锚点）。\n"
tasks:
  - id: T1
    title: forge 分发层：配置段 + alias-import 改线 + merger 提示词参数化 + merge-pr 隐藏命令
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/forge.py
      - openagents/utils/agent_config.py
      - openagents/data/openagents.yml.template
      - openagents/utils/github.py
      - openagents/agents/merger.py
      - openagents/recipes/vigil.py
      - openagents/recipes/stages.py
      - openagents/recipes/backfill.py
      - openagents/runtime/gates.py
      - openagents/runtime/context.py
      - openagents/utils/identity.py
      - openagents/utils/release.py
      - openagents/cli.py
      - tests/test_forge.py
      - tests/test_agents_merger.py
    scope: 新建 utils/forge.py：模块级 configure(name, settings)/reset() + PEP 562 __getattr__ 按当前 forge 委托到 github/gitea driver 模块；未显式 configure 时首次函数访问做惰性发现（从 cwd 向上找 .openagents/openagents.yml 轻量读 forge/gitea 两键，缺失/坏文件 fail-open 回落 github——保证 init/issue/release 等不显式装配置的命令也选对 driver，且与 gh 的 cwd 语义一致）；流程标签常量与 GithubError 在 import 时从 github.py 直接 re-export（forge 中立、零 IO）。agent_config.py：顶层 schema 加 forge（enum github/gitea）与 gitea 段（base_url/owner/repo 必填 + token_env 缺省 GITEA_TOKEN，additionalProperties=False），AgentConfig 加 forge/gitea 字段，手工校验 forge=gitea 必须带 gitea 段；模板追加注释掉的 forge 示例段。八个消费文件仅改 import 行为 alias-import（调用点零改动）。merger.py PROMPT 的 `gh pr merge`/`gh pr view` 硬编码改 $merge_command/$verify_command 占位符；github.py 加 merge_command_text/merge_verify_command_text（返回既有 gh 命令文本，github 侧行为零变化）；stages.merge 注入两占位符。cli.py 加隐藏子命令 merge-pr（--pr/--method，转发 forge.merge_pr + is_merged，输出含 MERGED 供 merger agent 判成功）——Gitea 侧 merger agent 的落合并出口，token 处理留在 driver 内不进提示词（与 reply-comment 同定位）。
    acceptance: pytest 通过：forge 缺省委托 github（既有全量测试零回归）；configure 后委托 gitea；常量 import 零 IO；惰性发现读 tmp 仓配置、坏 YAML 回落 github；agent_config 新段校验（forge=gitea 缺 gitea 段报错）；merger PROMPT 无 gh 字面量且含两占位符；stages.merge 注入命令文本（monkeypatch backend 断言 task 内容）；cli merge-pr 转发 forge（打桩断言）。ruff 全绿。
  - id: T2
    title: Gitea driver：github.py 同名公共面对 Gitea /api/v1（stdlib urllib，零新依赖）
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/utils/gitea.py
      - tests/test_gitea_driver.py
      - scripts/e2e-spec-0074-gitea-forge-driver.sh
    scope: 新建 utils/gitea.py，实现新栈实际消费的 github.py 公共面（ensure_prerequisites/ensure_label/create_issue/get_issue/list_issues/issue_comment/list_issue_comments/issue_add_label/issue_remove_label/close_issue/list_blocked_by/add_blocked_by/create_pr/find_pr_by_branch/pr_for_branch/list_open_prs/pr_head_branch/pr_snapshot/check_snapshot/check_status/check_logs/list_comments/post_comment/add_label/remove_label/has_label/mark_ready/update_branch/merge_pr/branch_ci_green/code_fingerprint/is_merged/is_open/is_closed/is_draft/mergeability/create_repo/merge_command_text/merge_verify_command_text），数据类与 GithubError 直接复用 github.py 定义。全部打 Gitea /api/v1：stdlib urllib.request 单收口 _http（Authorization 头带 token（取 token_env 环境变量）、30s 超时、5xx/超时指数退避×3 对齐 _run_gh，非 2xx 抛 GithubError 带状态码与端点）。语义映射：PR 评论=issue 评论（共享 index 命名空间）；create_issue/标签操作走名→id 解析（模块级缓存 + 409/422 已存在幂等）；checks→GET /commits/{ref}/status（combined state 归类 pass/fail/pending，statuses 计数与最近 created_at，零 status→count 0 state pass）；PR state open/closed+merged→OPEN/CLOSED/MERGED；mergeable bool→MERGEABLE/CONFLICTING、字段缺失→UNKNOWN、merge_state_status 派生 CLEAN/DIRTY/UNKNOWN（无 BEHIND——Gitea 不暴露 behind，update_branch 仅在显式调用时工作，见正文）；draft→WIP 标题前缀（is_draft 认前缀或原生 draft 字段，mark_ready=PATCH 去前缀）；blocked_by→GET/POST /issues/{index}/dependencies（404/特性关闭→[]，POST 已存在幂等）；update_branch→POST /pulls/{index}/update?style=merge|rebase（已最新 422→False）；merge_pr→POST /pulls/{index}/merge {Do:method}（已合并幂等 no-op）；close_issue→PATCH state=closed（404/已关幂等）；code_fingerprint→GET /pulls/{index}.diff 复用 github._strip_diff_file_blocks 后 sha256（失败→"" fail-open）；branch_ci_green→分支 combined status success 或零 status→True；ensure_prerequisites→token 非空 + GET /repos/{owner}/{repo} 可达 + 预建 PROCESS_LABELS；merge_command_text→'openagents merge-pr --pr N'。author_association 映射：评论者==配置 owner→OWNER，否则空串（fail-closed，triage:human 在 Gitea 上仅识别 owner 本人拍板——正文 Unresolved）。凡 1.22 端点实证不符处做最小语义降级并在代码注释记录。
    acceptance: tests/test_gitea_driver.py 假 HTTP 层覆盖上述全部函数的请求形状与响应解析、语义映射逐条断言（见 e2e.method）；不触网络。scripts/e2e-spec-0074-gitea-forge-driver.sh 绿（ruff + pytest + grep 锚点）。对真实 Gitea 1.22 的端到端冒烟由消费方 auto-designer spec-0032/T5 验收。
---

# 0074 · forge 分发层与 Gitea driver：把 GitHub 耦合收敛为可换轨的托管平台接缝

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

OpenAgents 的全部托管平台操作集中在 `utils/github.py`（gh CLI 薄封装），编排层以模块函数形式消费。本 spec 把这个事实耦合点升格为**显式接缝**：新增 `utils/forge.py` 分发模块（按 `.openagents/openagents.yml` 的 `forge` 段选 driver，缺省 github、存量零感知）与 `utils/gitea.py` driver（同名公共面对 Gitea /api/v1）；消费方只改 import 行（`from openagents.utils import forge as github`），数百个调用点零改动。merger 提示词内的 gh 命令参数化为占位符，Gitea 侧经新增隐藏命令 `openagents merge-pr` 落合并。

## Motivation

理念 2（去中心化多后端）已经声明了 coding 后端可混接（Claude Code / Codex / nexau）；托管平台是同构的另一维——「agent 之间通过 PR + comment 机制传递消息」这一设计不依赖 GitHub 本身，依赖的是任何有 issue/PR/label/comment 语义的 forge。第一个真实消费方已经出现：auto-designer（自进化 harness 编排）要把其开发者侧换轨到 OpenAgents，而它的基建钉在**本地 Gitea**（隔离沙箱、无外部凭证的围堵需求），不能也不应迁 GitHub。

改造成本恰好最低的时机也在现在：Spec-0060–0065 大收敛后，github.py 是依赖图的叶子、消费方全部走 `github.fn()` 模块函数调用——alias-import 一行就能换轨，越晚做、消费点越散。

## Guide-level explanation

用户视角：在 Gitea 项目里，`.openagents/openagents.yml` 多写一段——

```yaml
forge: gitea
gitea:
  base_url: http://localhost:3000
  owner: harness
  repo: harness
  token_env: GITEA_TOKEN   # 可省，默认 GITEA_TOKEN；token 本体只放环境变量
```

其余命令、stages 三态、vigil 行为完全不变。不写 `forge` 段 = github（gh CLI），存量用户零感知。鉴权延续「OpenAgents 不存 token」纪律：GitHub 委托 gh，Gitea 委托环境变量。

开发者视角：任何要打平台的代码 import `forge as github`，照常调 `github.list_issues(...)`；forge 按配置把调用委托给对应 driver。新 forge（GitLab 等）= 新增一个同名公共面模块 + enum 加一项。

## Reference-level explanation

### forge.py 分发（T1）

- `configure(*, name, settings)` 显式装载（vigil/CLI 路径、测试）；未配置时首次**函数**访问做惰性发现：从 cwd 向上找 `.openagents/openagents.yml`，轻量读 `forge`/`gitea` 两键（不走 agent_config 全量校验，避免循环依赖），缺失/坏文件 fail-open 回落 github。惰性发现保证 `issue`/`release` 等不装配置的命令也选对 driver，语义与 gh 的 cwd 绑定一致。
- 流程标签常量（DISCOVERY_LABEL 等）与 `GithubError` 在 import 时直接从 github.py re-export——它们 forge 中立，且避免「模块顶层取常量触发 IO」。
- 错误类型不分叉：gitea driver 同样抛 `GithubError`（cli 的错误归一化零改动）。

### 提示词里的平台命令（T1）

merger 是唯一在 PROMPT 里硬编码 gh 命令的 agent。改 `$merge_command`/`$verify_command` 占位符，`stages.merge` 经 driver 的 `merge_command_text()`/`merge_verify_command_text()` 注入：github 返回原样 gh 命令（零回归）；gitea 返回 `openagents merge-pr --pr N`——新增的隐藏 CLI 子命令（与 reply-comment 同定位），内部转发 `forge.merge_pr` + `is_merged`，把 token 处理留在 driver 内、不让凭证进提示词。

### Gitea 语义映射（T2）

| GitHub（gh） | Gitea /api/v1 | 降级说明 |
|---|---|---|
| checks（check runs） | `GET /commits/{ref}/status` combined | 零 status → count=0（守夜判「等 CI」职责在调用方，不变） |
| mergeable 三态 | PR `mergeable: bool` | false→CONFLICTING/DIRTY；字段缺失→UNKNOWN；**无 BEHIND**（Gitea 不暴露 behind，update_branch 不会被守夜自动触发；merge 时由 Gitea 服务端 merge 兜底） |
| draft PR | `WIP: ` 标题前缀 | is_draft 认前缀或原生 draft 字段；mark_ready=PATCH 去前缀 |
| 原生 blocked_by | `GET/POST /issues/{index}/dependencies` | 404/特性关闭→无依赖 |
| `gh pr merge` | `POST /pulls/{index}/merge` | 已合并幂等 |
| update branch | `POST /pulls/{index}/update?style=` | 已最新 422→False |
| authorAssociation | 无对应 | 评论者==配置 owner→"OWNER"，否则 ""（fail-closed） |
| `Closes #N` 自动关 | 原生 closing keywords | 相同 |

PR 评论与 issue 评论在 Gitea 共享 index 命名空间（`/issues/{index}/comments` 两用），`list_comments`/`post_comment` 与 issue 版同端点。标签操作需名→id 解析（模块级缓存 + 竞态幂等回退，对齐消费方 GiteaTracker 的既有实践）。

## Drawbacks

1. 公共面以 github.py 为事实契约，无 Protocol 强约束——新函数加进 github.py 而忘加 gitea.py 时，gitea 项目在调用点才炸（AttributeError→由 forge 包成带提示的错误）。以 grep 锚点 + 消费方冒烟兜。
2. author_association 在 Gitea 上只识别 owner，`triage: human` 的多维护者场景受限（首个消费方 triage=skip，不受影响）。
3. 双 driver 语义漂移风险：合并流水线依赖的 mergeable/BEHIND 细节两平台天然不同，已按「保守收敛 + 注释记录」处理。

## Rationale and alternatives

- **alias-import 而非 forge Protocol 大重构**：消费点数百、模块函数式调用已是稳定形态；改 import 行是 O(文件数) 的最小侵入，github.py 公共面即接口契约，不为「第三个 forge」预付抽象费（理念 1）。
- **stdlib urllib 而非 requests/tea CLI**：依赖面保持 ruamel.yaml+jsonschema 不动；tea CLI 覆盖不全且引入外部二进制。
- **merge 动作保留 agent 形态**（`$merge_command` 注入）而非 stages 机械直调：维持 Spec-0017/T3「生命周期动作归 agent + needs-human 最后出口」的取舍；机械化留作后续可选收敛。
- **弃案：消费方 monkeypatch sys.modules**：不改本仓、由消费方运行时替换 github 模块——上游任何函数面变动都会静默破坏，且把内部结构变成外部契约；被否。

## Prior art

- 本仓 Spec-0064（声明式 agents/stages 三态）：forge 段沿同一配置真源与校验风格。
- 消费方 auto-designer spec-0032（需求面/交付面二分）：本 spec 的驱动性用例与真实 Gitea 冒烟验收方。
- 消费方 GiteaTracker（auto-designer spec-0002）：标签名→id 缓存与幂等回退的既有实践。

## Unresolved questions

1. Gitea 1.22 端点实证：dependencies API 形状、PR 响应有无原生 draft 字段、update 端点的「已最新」返回码——T2 开工首件事对真实实例验证，映射表按实证微调。
2. `triage: human` 在 Gitea 的维护者识别（协作者列表 API 可补，等真实需求）。
3. BEHIND 缺失的影响面：PR base 落后时不主动 update_branch，靠 merge 时服务端合并兜底——观察消费方运行数据再定是否补「比较 base sha」的模拟 BEHIND。

## Future possibilities

- GitLab driver（同法：新模块 + enum 一项）。
- forge 能力声明（driver 自述支持哪些可选特性：dependencies/draft/behind），守夜按能力降级而非硬编码注释。
- merger 机械化选项（stages 直调 forge.merge_pr，配置可选）。
