"""独立探针：CLI 面收敛 + identity 签名闭环。
证明 intent：人面向仅 vigil/issue/backfill-rfc/release(+init/board) + 隐藏 reply-comment；
旧九命令零残留；post_signed_comment 漏签由 edit 补(真 post_comment)非只 warn。
"""
import sys, types
from openagents import cli
from openagents.utils import identity, github

PASS, FAIL = [], []
def check(name, cond):
    (PASS if cond else FAIL).append(name); print(("✓" if cond else "✗")+" "+name)

# --- CLI 收敛 ---
parser = cli.build_parser()
sub = [a for a in parser._subparsers._group_actions if isinstance(a, __import__("argparse")._SubParsersAction)][0]
names = set(sub.choices.keys())
print("registered subcommands:", sorted(names))
# 人面向四命令 + init/board 保留 + 隐藏 reply-comment
for c in ("vigil","issue","backfill-rfc","release"):
    check(f"人面向命令保留：{c}", c in names)
check("隐藏内部命令 reply-comment 仍可解析分发", "reply-comment" in names)
# reply-comment 隐藏：不传 help → 不进 --help 帮助清单（choices 有但 help 项无）
reply_action = sub._choices_actions
help_listed = {a.dest for a in reply_action}
check("reply-comment 从 --help 清单隐去(无 help 项)", "reply-comment" not in help_listed)
# 旧九命令零残留
for old in ("rfc","refine-rfc","implement","iterate","solve","poll","watch","vigil-all","fleet"):
    check(f"旧命令已删：{old} 不可解析", old not in names)
# handler 表也无旧命令路由（读 _dispatch 源里的 handlers dict 键）
import inspect
src = inspect.getsource(cli._dispatch)
for old in ("solve","poll","iterate","vigil-all","fleet","refine-rfc"):
    check(f"_dispatch handlers 无旧路由：{old}", f'"{old}"' not in src)

# --- identity 签名闭环：漏签→edit 补(真 post_comment)，非只 warn ---
POSTS = []
class FakeComment:
    def __init__(self, body, ts): self.body=body; self.created_at=ts
# 场景 A：正常盖章→回读到带签名→不补第二条
def fake_post_ok(*, pr_number, body):
    POSTS.append(body)
def fake_list_ok(*, pr_number):
    # 回读到刚发的带签名评论（POSTS[-1] 已含签名）
    return [FakeComment(POSTS[-1], "2026-01-01T00:00:00Z")] if POSTS else []
o_post, o_list = github.post_comment, github.list_comments
github.post_comment = fake_post_ok; github.list_comments = fake_list_ok
POSTS.clear()
identity.post_signed_comment(pr_number=5, body="hello", agent_id="agentX")
check("正常盖章→签名落地→不补第二条(共1条)", len(POSTS)==1 and "openagents:agent=agentX" in POSTS[0])

# 场景 B：签名被外部截断/改写→回读最近一条无本实例签名→主动补一条签名评论(edit 补)
def fake_list_stripped(*, pr_number):
    # 模拟：回读到的最近评论签名丢了(被截断)
    return [FakeComment("hello（签名被截断）", "2026-01-01T00:00:01Z")]
github.post_comment = fake_post_ok; github.list_comments = fake_list_stripped
POSTS.clear()
identity.post_signed_comment(pr_number=5, body="hello", agent_id="agentX")
check("漏签→真补一条签名评论(post_comment 共2条,非只 warn)", len(POSTS)==2)
check("补签评论确带本实例签名", "openagents:agent=agentX" in POSTS[-1])
github.post_comment, github.list_comments = o_post, o_list

# _verify_signature_or_fix 存在且补签走真 post_comment（非 warnings.warn 告警）
vsrc = inspect.getsource(identity._verify_signature_or_fix)
modsrc = inspect.getsource(identity)
check("_verify_signature_or_fix 用 post_comment 补签", "post_comment" in vsrc)
check("identity 全模块无 warnings.warn(补签是真动作非只告警)", "warnings.warn" not in modsrc)

print(f"\n=== CLI+identity 探针：{len(PASS)} passed, {len(FAIL)} failed ===")
if FAIL:
    print("FAILED:", FAIL); sys.exit(1)
