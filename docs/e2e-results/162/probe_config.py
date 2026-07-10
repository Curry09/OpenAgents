"""独立验证探针（不用仓库自带测试）：喂不同 openagents.yml 串，断言配置层三态校验/守卫。
证明 intent：agent_config 加载出的三态策略 + 每闸合法取值校验 + 不许零闸守卫 + rfc:skip 告警 + 每仓 override。
"""
import sys, tempfile, warnings
from pathlib import Path
from openagents.utils import agent_config as ac

PASS, FAIL = [], []
def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("✓" if cond else "✗") + " " + name)

def load(text):
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
        f.write(text); p = Path(f.name)
    return ac.load_agent_config(path=p)

def load_err(text):
    try:
        load(text); return None
    except ac.AgentConfigError as e:
        return str(e)

# 1. 整份省略/不存在 → 全默认回落
cfg = ac.load_agent_config(path=Path("/nonexistent/openagents.yml"))
check("整份缺失→全默认(全 agent stages)", all(cfg.stages.owner_of(stage=s)=="agent" for s in
      ("triage","rfc","conflict","ci","e2e","review","merge")))
check("整份缺失→claude_code 默认后端", cfg.agents.backend_for(role="implementer")=="claude_code")
check("整份缺失→release manual", cfg.release.mode=="manual")
check("整份缺失→单仓 path=.", len(cfg.repos)==1)

# 2. 三态解析真正驱动 owner
cfg = load("version: 1\nstages:\n  merge: human\n  rfc: agent\n")
check("stages.merge=human 解析生效", cfg.stages.owner_of(stage="merge")=="human")
check("未声明的 ci 回落 agent 默认", cfg.stages.owner_of(stage="ci")=="agent")

# 3. 每闸合法取值：conflict/merge 拒 skip
check("conflict:skip 被拒", load_err("stages:\n  conflict: skip\n") is not None)
check("merge:skip 被拒", load_err("stages:\n  merge: skip\n") is not None)
# rfc 仅 agent/skip：rfc:human 被拒
check("rfc:human 被拒(rfc 仅 agent/skip)", load_err("stages:\n  rfc: human\n") is not None)

# 4. 硬闸名进 stages 直接 reject
for hg in ("head-advanced","evidence-stamp","round-cap"):
    check(f"硬闸名 {hg} 进 stages 被 reject", load_err(f"stages:\n  {hg}: agent\n") is not None)
# 恒 agent 阶段名进 stages reject
for al in ("implement","deliver"):
    check(f"恒agent阶段 {al} 进 stages 被 reject", load_err(f"stages:\n  {al}: agent\n") is not None)

# 5. 「不许零闸」守卫：review:skip + merge:agent 被拒
err = load_err("stages:\n  review: skip\n  merge: agent\n")
check("零闸组合 review:skip+merge:agent 被拒", err is not None and "零闸" in err)
# 但 review:skip + merge:human 站得住（人兜底）
check("review:skip+merge:human 放行(人兜底)", load_err("stages:\n  review: skip\n  merge: human\n") is None)

# 6. rfc:skip 出显式告警
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    load("stages:\n  rfc: skip\n  merge: human\n")
    check("rfc:skip 出 warnings.warn 告警", any("rfc" in str(x.message).lower() for x in w))

# 7. 每仓 override 合并生效
cfg = load("""version: 1
stages:
  merge: human
repos:
  - path: .
  - path: ../other
    base: develop
    stages: { merge: agent }
""")
top = next(r for r in cfg.repos if r.path.name != "other")
other = next(r for r in cfg.repos if r.path.name == "other")
check("顶层仓沿用 merge:human", top.stages.owner_of(stage="merge")=="human")
check("override 仓 merge:agent 覆盖生效", other.stages.owner_of(stage="merge")=="agent")
check("override 仓 base=develop 合并生效", other.base=="develop")
# 每仓 override 后仍守零闸：review:skip 顶层 + repo merge:agent → 拒
check("override 后仍守零闸(repo merge:agent 撞顶层 review:skip)",
      load_err("stages:\n  review: skip\n  merge: human\nrepos:\n  - path: .\n    stages: { merge: agent }\n") is not None)

# 8. agents 段混接后端声明面（理念2）
cfg = load("agents:\n  implementer: { backend: codex }\n  reviewer: { backend: claude_code }\nstages:\n  merge: human\n")
check("agents.implementer=codex 声明面生效", cfg.agents.backend_for(role="implementer")=="codex")

print(f"\n=== 配置层探针：{len(PASS)} passed, {len(FAIL)} failed ===")
if FAIL:
    print("FAILED:", FAIL); sys.exit(1)
