# PR #162 运行时验证证据 — Spec-0064 声明式 stages 策略路由 + recipes 6→3 收敛

独立 executor 真跑（与写代码者不共享上下文）。形态：纯后端配置 + 编排 + CLI 收敛，无 product-facing
前端；自检工具无 Playwright / Chrome DevTools MCP，故按 spec method 走离线确定性测法（沿用 0060/0061/0062）。
所有探针真执行代码、不触真实 LLM/网络/仓库（monkeypatch）。

## 判定点与结果（全绿）

| # | 意图（intent，不可弱化） | 怎么验 | 证据文件 | 结果 |
|---|---|---|---|---|
| 1 | e2e 脚本（ruff + 针对性 pytest + grep 锚点）整体通过 | 真跑 `scripts/e2e-spec-0064-*.sh` | `01-e2e-script-full.log` | ✅ EXIT=0，"✅ Spec-0064 离线 e2e 全绿" |
| 2 | 配置层三态每闸合法取值 + 硬闸名 reject + 不许零闸守卫 + rfc:skip 告警 + 每仓 override + 全默认回落 | 独立探针喂假 YAML 串 | `02-probe-config.log` | ✅ 22/22 |
| 3 | run_vigil 按注入 config 三态真驱动 agent/human/skip 分支；流水线序 conflict→ci→e2e→review→merge；conflict 在读 CI 前判 mergeable(DIRTY/UNKNOWN 短路)；CI/e2e/review 失败→派 implementer→下轮从 conflict 重进；round_cap 硬闸不受 stages 管辖 | 独立探针注入 canned 裁决 + 记录调用序 | `03-probe-orchestration.log` | ✅ 27/27 |
| 4 | 人面向仅 vigil/issue/backfill-rfc/release(+init/board) + 隐藏 reply-comment；旧九命令零残留；post_signed_comment 漏签由真 post_comment 补(非只 warn) | 独立探针解析 argparse + 假 github 模拟漏签 | `04-probe-cli-identity.log` | ✅ 26/26 |
| 5 | 全量 pytest 绿（T6 删旧后无回归） | 真跑 `pytest -q` | `05-full-pytest.log` | ✅ 557 passed |
| 6 | recipes/ 仅剩 {stages,vigil,backfill,__init__}.py；对已删 recipe/planner 裸 import 零命中；planner.py 已删 | 目录列举 + 严格 import-statement grep | 见下"补充锚点" | ✅ |

## 关键分支的真实观察（编排层探针，节选）

- **流水线序**：全 agent 全绿一轮的调用序恰为 `ci→e2e→review→merge→close_issue`（CLEAN 时跳解冲突）。
- **conflict 是 CI 硬依赖**：mergeability=DIRTY → 先调 conflict(reason=resolved)、`CALLS 无 ci`；
  mergeability=UNKNOWN → `ev is None`（本轮不推进）、`CALLS 无 ci`。
- **打回回环（本 spec 补的真缺口）**：
  - `ci:agent` + CI 红 → `reason=ci` 且真派 implementer，且未走到 e2e/review/merge（下轮从头重进）。
  - `e2e:agent` + 证据陈旧 → `reason=e2e` 且派 implementer。
  - `review:agent` + REWORK → `reason=review` 且派 implementer。
- **三态其余两分支**：`ci:human`/`review:human` → blocked(不派 implementer、state 置 blocked)；
  `ci:skip`/`e2e:skip`/`review:skip` → 真跳过该闸放行；`merge:human` → hold-merge 不自动合。
- **硬闸恒在**：`gates.round_cap()` 跑满上限即 raise GateError（reviewer 恒 REWORK 的死循环兜底），
  且 head-advanced/evidence-stamp/round-cap 三硬闸名全不在 `_STAGE_VALID_OWNERS`（stages 无从 skip 关）。

## 补充锚点（命令与观察）

```
$ ls openagents/recipes/*.py
  __init__.py  backfill.py  stages.py  vigil.py         # 6→3 收敛 ✓
$ ls openagents/agents/planner.py
  No such file or directory                             # T6 已删 ✓
$ grep -rnE '^(from|import) .*\b(recipes\.(solve_issue|merge_pr|poll_comments|rfc_lifecycle|fleet)|agents\.planner)\b' openagents/ tests/
  (zero real import statements)                          # 裸 import 零命中 ✓
```
（对已删模块的其余 grep 命中均在注释/docstring 文字提及，非 import 语句；test_fleet*.py 导入的是
存活的 `utils.fleet`/`utils.fleet_config` 进程监管器，非已删 `recipes.fleet`。）

## 复现

```bash
bash scripts/e2e-spec-0064-declarative-stages-converge.sh          # 官方脚本
uv run python docs/e2e-results/162/probe_config.py                 # 配置层
uv run python docs/e2e-results/162/probe_orchestration.py          # 编排层
uv run python docs/e2e-results/162/probe_cli_identity.py           # CLI + 签名闭环
uv run --extra dev pytest -q                                       # 全量
```

结论：spec e2e 块声明的架构契约在离线确定性链路上成立，intent 全部达成。最终裁决交 code review。
