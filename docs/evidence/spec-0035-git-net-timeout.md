# Spec-0035 证据：裸 git 网络超时 fail-open + 发现段进度日志（真 app 触发）

取证类别：**②**——本组改动无 UI，但改产品对外行为（stderr 进度日志 + 卡死时的 fail-open 兜底）。
下列日志均由**已安装的真实 `openagents` 代码**触发：T1 真跑 `git ls-remote` 到 live origin
（github.com/Curry09/OpenAgents）、T4 真跑 `_intake`/`_admit` 读 live GitHub issue。写副作用
（打 label / POST 评论 / 调 LLM）在 T4 演示中被中和为 no-op/spy，仅为**避免污染 live 仓库**——被观测的
进度日志与 fail-open 分支本身全部走真实代码路径。纯超时抛错的三类 fail-open 分支（去重→True /
fetch→WorkspaceError / push→RuntimeError）另由 hermetic 单测钉死（打桩 `subprocess.run` 抛
`TimeoutExpired`，见 `tests/test_utils_git.py` / `test_workspace.py` / `test_release.py`）。

离线复现全部：`bash scripts/e2e-spec-0035-git-net-timeout.sh`。

## T1 · 去重探针 stderr 面包屑 + 超时 fail-open（真跑 ls-remote 到 live origin）

触发上下文：直调 `openagents.utils.git.remote_branch_exists`，`work_dir=.`，origin =
`https://github.com/Curry09/OpenAgents.git`。第 2 次把 `_GIT_NET_TIMEOUT_SECONDS` 逼到 `0.001s`，
真实 ls-remote 必然超时 → 走 `except subprocess.TimeoutExpired: return True`。

```
[trigger] _GIT_NET_TIMEOUT_SECONDS = 30
… issue 查远端分支去重（openagents/does-not-exist-xyz）…
[result] 正常路径 remote_branch_exists(不存在分支) = False
… issue 查远端分支去重（main）…
[result] 超时 fail-open remote_branch_exists = True（应为 True）
```

- 面包屑「… issue 查远端分支去重（<branch>）…」在真跑 ls-remote **之前**落 stderr（卡住时输出停在这行）。
- 正常路径逐字节不变：不存在的分支 → `False`（真实 ls-remote 无输出）。
- 超时（0.001s）→ 保守 `True`（「可能在途」→ 本轮跳过、下轮重试，绝不重复派单）。

## T4 · 发现段进度日志（真跑 `_intake`/`_admit` 读 live GitHub issue）

### 第一行：`_intake` 拉带标签 issue 前（真实 `github.list_issues` 读 live 仓库）

触发上下文：真实 `v._intake(...)`，`config.labels=["openagents"]`；写副作用（ensure_label /
issue_add_label / issue_comment / triage LLM / _order_edges / _park_needs_human）中和为 no-op/spy。

```
[trigger] 调用真实 v._intake（github.list_issues 走真实网络到 live 仓库）
▶ 发现段：拉取带标签 issue…
[done] _intake 返回
```

「▶ 发现段：拉取带标签 issue…」在真实 `github.list_issues` **之前**落 stderr。本轮 live 仓库无
「带 openagents 标签且未打 ready/needs-human」的可准入 issue，故未进入 per-issue 分诊行——见下第二行单独触发。

### 第二行：`_admit`（agent 态）调 triager LLM 前（真实抓取的 live issue #170）

触发上下文：真实 `v._admit(owner="agent", ...)`，issue 由真实 `github.list_issues([])` 抓取；
`stages.triage`（LLM）与写副作用中和（不烧 token、不改仓库）。

```
[trigger] 真实抓到 open issue #170：'feat(frontend): openagents 桌面 app —— 并行看板 + 大窗流式 + tab 待看导航'
… issue #170 自检分诊方向(LLM)…
[neutralized] LLM 调用被 stub（不烧 token）
[neutralized] would park issue:170
[done] _admit 返回 0
```

「… issue #170 自检分诊方向(LLM)…」在调 triager LLM **之前**落 stderr（卡在 LLM 分诊时输出停在这行、
带 issue 号一眼定位）。返回值 `0`（stub 判 `actionable=False`）与既有控制流一致。
