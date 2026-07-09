"""RFC-0001 T1 + RFC-0005: CLI 入口。

唯一命令入口，仅做参数解析与分发；业务逻辑下沉到各模块（命令体内延迟 import，
保持 cli.py 文件归属单一、文件清单不重叠）。除 board 外的命令在执行前先做项目
绑定 preflight（决策 10）。

RFC-0005 决策 1：取消一站式 solve，改注册四个**原子步骤**子命令——
rfc（起草 RFC 开 draft PR）/ refine-rfc（按评审精炼 RFC）/ implement（获批后写码转正）/
iterate（coding 阶段就 comment/CI 迭代）——外加 init/issue/poll/watch/board。
跨步骤编排交给 poll 的状态机，CLI 只负责触发单步。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from openagents.utils import github
from openagents.utils.config import ProjectContext, ensure_project, resolve_project

# RFC-0002 决策 5 / RFC-0004 决策 2：发现标签——单一真源。
# `openagents issue` 提 issue 时自动附加它（使 issue 可被发现），vigil 发现段默认按它门控；
# 两端共用同一常量，保证「提 issue 用的标签」与「vigil 发现用的标签」永远一致。
# RFC-0015：字面量上移至 github（流程标签单一来源），此处改为别名引用，保留
# cli.DISCOVERY_LABEL 公共名向后兼容（github 为叶子模块，顶层 import 无循环依赖风险）。
DISCOVERY_LABEL = github.DISCOVERY_LABEL


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openagents",
        description="RFC 驱动的多 Agent 框架：拉取 issue → 派单 agent → 提 PR。",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("init", help="绑定/初始化当前目录为 OpenAgents 项目")

    # RFC-0005：取消一站式 solve，改为四个可单独触发的原子步骤（决策 1）。
    p_rfc = sub.add_parser("rfc", help="为一个 issue 起草 RFC 并开 draft PR")
    p_rfc.add_argument("issue", type=int, help="issue 编号")
    # RFC-0003 决策 2/3：分支基线，issue 分支从最新 origin/<base> 拉出。
    # Spec-0023/T4：test 门控退役，默认改回 main——issue 分支与 PR base 同源锁 main。
    p_rfc.add_argument("--base", default="main", help="分支基线（默认 main）")

    # Spec-0025/T3：brownfield 反向补全——扫存量代码路径反推 9 段 spec 并开 draft PR。
    # 与 rfc 互补：rfc 是 issue 驱动（设计先行），backfill-rfc 是 path 驱动（实现先行）。
    p_backfill = sub.add_parser("backfill-rfc", help="扫存量代码路径反推 spec 并开 draft PR")
    p_backfill.add_argument("path", help="要反向补全的代码路径（单文件或目录）")
    p_backfill.add_argument("--base", default="main", help="分支基线（默认 main）")

    p_refine = sub.add_parser("refine-rfc", help="按 PR 最新评审评论精炼 RFC")
    p_refine.add_argument("pr", type=int, help="PR 编号")

    p_impl = sub.add_parser("implement", help="RFC 获批后按 RFC 实现代码并转正 PR")
    p_impl.add_argument("pr", type=int, help="PR 编号")

    # Spec-0060/T6：走**新栈** solve_issue recipe 的 additive 子命令（旧子命令路由不动）。
    # plan → implement → review(loop while REWORK) → deliver，只按 agent 结构化裁决路由 + 最小硬闸兜底。
    p_solve = sub.add_parser("solve", help="[新栈] 用 solve_issue recipe 端到端求解一个 issue")
    p_solve.add_argument("issue", type=int, help="issue 编号")
    p_solve.add_argument("--base", default="main", help="分支基线（默认 main）")
    p_solve.add_argument(
        "--pr", type=int, default=None, help="已有 PR 编号（用于注入评审历史；缺省自动按分支查找）"
    )

    p_iter = sub.add_parser("iterate", help="就 PR 的 comment/CI 反馈迭代代码")
    p_iter.add_argument("pr", type=int, help="PR 编号")
    p_iter.add_argument(
        "--reason", choices=["comment", "ci"], default="comment", help="反馈来源（默认 comment）"
    )

    # RFC-0002 T2：主动往当前项目仓库提一个 GitHub issue。
    p_issue = sub.add_parser("issue", help="往当前项目仓库提一个 GitHub issue")
    p_issue.add_argument("title", help="issue 标题")
    p_issue.add_argument("--body", default="", help="issue 正文，默认空")
    p_issue.add_argument(
        "--label",
        action="append",
        default=[],
        metavar="LABEL",
        help=f"给 issue 打标签（可重复）；总会附带发现标签 {DISCOVERY_LABEL!r}（决策 5）",
    )
    # Spec-0020/T4：建 issue 前默认先复述对齐、请人确认；--yes 跳过确认直接建（供自动化）。
    p_issue.add_argument(
        "--yes",
        action="store_true",
        help="跳过建 issue 前的对齐确认，直接创建（供 vigil/CI 等自动化路径）",
    )

    # 给 coding agent（如解冲突 agent）用的「以本 agent 身份回评论」工具：内部盖 OpenAgents 签名 →
    # 回复不会被下一轮 poll 当成新人类评论（防自触发）。agent 必须走这个命令回评论，不能用裸 gh。
    p_reply = sub.add_parser("reply-comment", help="以本 agent 身份（带签名）回复某 PR 的评论")
    p_reply.add_argument("--pr", type=int, required=True, metavar="N", help="要回复的 PR 编号")
    p_reply.add_argument("--body", required=True, help="回复正文（会自动盖上本 agent 签名）")

    sub.add_parser("poll", help="拉取并处理所有 PR 的新评论（一次性）")

    p_watch = sub.add_parser("watch", help="按间隔循环 poll（自动化拉取）")
    p_watch.add_argument("--interval", type=int, default=60, help="轮询间隔（秒），默认 60")

    # 拉式同步重构后移除了 push 扇出（含手动 sync-prs）：合并后其余 open PR 各自轮到时在守夜人
    # _process_coding 的 BEHIND 分支由 update_branch 跟上，无需独立的手动扇出入口（理念 1 奥卡姆）。

    sub.add_parser("board", help="启动本地成果看板")

    # RFC-0004：守夜人模式——自主发现新 issue 派单 + 守候 PR（comment/CI），人只审 PR。
    p_vigil = sub.add_parser("vigil", help="守夜人模式：自主监控 issue → 派单 → 守候 PR")
    p_vigil.add_argument("--interval", type=int, default=60, help="轮询间隔（秒），默认 60")
    # default=None：用户传 --label 时替换而非追加默认；handler 缺省回落到 ["openagents"]。
    p_vigil.add_argument(
        "--label",
        action="append",
        default=None,
        metavar="LABEL",
        help="issue 发现的标签门控（可重复），默认 openagents",
    )
    # RFC-0012 决策 2：派单起草 RFC 的分支基线默认改为 test。
    p_vigil.add_argument("--base", default="main", help="派单起草改动的分支基线（默认 main）")
    p_vigil.add_argument("--once", action="store_true", help="只跑一轮（发现+poll）后退出")
    # Spec-0020/T4：分级监督——在指定意图闸门停下等人。默认 None（全自动不停，行为不变）。
    p_vigil.add_argument(
        "--hold",
        default=None,
        metavar="GATE",
        help="在指定闸门停下等人：spec / merge / spec,merge（默认全自动不停）",
    )
    # Spec-0054/T3：逐闸旁路——把指定 CLI 可达闸当 PASS 直接放行（与 --hold 对称）。默认 None
    # （全闸开启、行为不变）。--hold 与 --skip 对同一闸的矛盾意图由 reconcile_hold_skip 报错。
    p_vigil.add_argument(
        "--skip",
        default=None,
        metavar="GATE",
        help="把指定闸当 PASS 放行：issue / spec / code / ci / evidence / all（默认全闸开启）",
    )

    # Spec-0027/T3：vigil-all —— 多仓库统管。单进程读一份 YAML 配置（仓库列表 + 全局默认 +
    # 每仓库覆盖），为每个仓库各起一隔离子进程复用现有 Vigil 并发守夜、聚合日志。与单仓库
    # vigil 并存：vigil 在「当前仓库内」跑，vigil-all 在「任意目录」读配置统管一组仓库。
    p_vigil_all = sub.add_parser(
        "vigil-all", help="多仓库统管：按配置文件并发守夜一组仓库（复用 vigil）"
    )
    p_vigil_all.add_argument(
        "--config",
        default=".openagents/fleet.yml",
        metavar="PATH",
        help="fleet 配置文件路径（默认 .openagents/fleet.yml）",
    )
    p_vigil_all.add_argument(
        "--once", action="store_true", help="每个仓库各跑一轮后退出（cron/CI/e2e 用）"
    )

    # Spec-0023/T4：release —— 人唯一的宏观决策点：预检通过则把持续推进的 main 物化成一个
    # 版本（release/vX.Y.Z 分支 + tag）。取代退役的 test 门控 promote。
    p_release = sub.add_parser("release", help="把 main 当前 HEAD 发布为一个版本（预检通过后物化）")
    p_release.add_argument(
        "--bump",
        choices=["patch", "minor", "major"],
        default="patch",
        help="版本号递增位（默认 patch；从最新 vX.Y.Z tag 递增，无 tag 则起点 v0.1.0）",
    )

    # Spec-0062/T4：新栈多仓库统管 fleet —— 读一份 YAML（同 vigil-all 格式），为每个仓库各起一隔离
    # 子进程跑新栈 vigil 并发守夜。vigil-all 收编为本命令的别名（两栈合一后单一实现，见 _dispatch）。
    p_fleet = sub.add_parser("fleet", help="多仓库统管：按配置并发守夜一组仓库（扇出新栈 vigil）")
    p_fleet.add_argument(
        "--config",
        default=".openagents/fleet.yml",
        metavar="PATH",
        help="fleet 配置文件路径（默认 .openagents/fleet.yml）",
    )
    p_fleet.add_argument(
        "--once", action="store_true", help="每个仓库各跑一轮后退出（cron/CI/e2e 用）"
    )

    return parser


# RFC-0001 T1: 业务对象工厂，延迟 import 各子任务模块；测试可对这些工厂打桩，
# 保持 cli 测试 hermetic（不触达真实 gh / claude / 浏览器）。
def _state_for(*, repo_root: Path):
    from openagents.state import State

    return State(path=repo_root / ".openagents" / "state.json")


# Spec-0055/T1：守夜/单步入口启动时把「前端 e2e 能力」固化进 state（单一真相源）。每次启动重写——
# 环境（装/删 browser MCP、切权限模式）变了下次启动即更新。下游 RFC 起草/评审据它分流测法要求；
# executor 执行时自检工具、不读本状态量。延迟 import + 走工厂 _state_for，保持 cli 测试可打桩、不触真实 ~/.claude.json。
def _persist_ui_capable(*, ctx: ProjectContext) -> None:
    from openagents.utils import envcheck

    _state_for(repo_root=ctx.repo_root).set_ui_capable(value=envcheck.ui_capable())


# RFC-0011 决策 7：在接线处解析一次本实例身份，注入下游（recipes / reply-comment）。
# resolve_agent_id 幂等（env > state > 首次生成落盘），多处调用得同一 id，保证 solve / poll / vigil
# 跨进程一致。单列为工厂，便于测试打桩、不触达真实 state。
# Spec-0062/T4：身份解析仍读旧 State（state.py 本批暂留，归一随 Spec-0063），与新栈 recipe 编排解耦。
def _agent_id_for(*, ctx: ProjectContext) -> str:
    from openagents.utils import identity

    return identity.resolve_agent_id(state=_state_for(repo_root=ctx.repo_root))


# Spec-0020/T4：单列 backend 工厂——issue 前门对齐（align）与各 recipe 共用同一个
# ClaudeCodeBackend 抽象，延迟 import 保持 cli 顶层轻、测试可对工厂打桩（不触达真实 LLM）。
def _backend_for():
    from openagents.backends.claude_code import ClaudeCodeBackend

    return ClaudeCodeBackend()


# Spec-0062/T4：RFC 生命周期五 recipe（draft/backfill/refine/implement/iterate）共用的接线参数——
# backend/state/work_dir/agent_id 一次构造。state 走新栈 RuntimeState（refine/implement/iterate 经
# find_run(pr_number=) 落到真实 state），身份/后端复用既有幂等工厂，保证同进程一致。
def _rfc_kwargs(*, ctx: ProjectContext) -> dict:
    return {
        "backend": _backend_for(),
        "state": _new_runtime_state_for(ctx=ctx),
        "work_dir": ctx.repo_root,
        "agent_id": _agent_id_for(ctx=ctx),
    }


# Spec-0061/T4：新栈 RuntimeState 工厂——独立命名空间文件 runtime-state.json（与旧 state.json
# 文件级零冲突，见 runtime.state）。延迟 import 保持 cli 顶层轻、测试可打桩。
def _new_runtime_state_for(*, ctx: ProjectContext):
    from openagents.runtime.state import RUNTIME_STATE_FILENAME, RuntimeState

    return RuntimeState(path=ctx.repo_root / ".openagents" / RUNTIME_STATE_FILENAME)


# Spec-0061/T4：新栈守夜人工厂——返回 (Vigil, poll)：Vigil 跑发现→分诊→派单，poll 是守候段
# poll_comments 的零参偏函数（供 Vigil.run 每轮调）。backend/state/agent_id 一次构造、两段共享，
# 保证同一守夜进程内身份与状态一致。recipes.fleet 的子进程目标 `_run_repo` 也调本工厂（与 CLI
# `vigil-new` 同源），故本工厂是新栈守夜的单一接线点。
def _new_vigil_for(*, ctx: ProjectContext):
    from functools import partial

    from openagents.recipes.poll_comments import poll_comments
    from openagents.recipes.vigil import Vigil

    backend = _backend_for()
    rstate = _new_runtime_state_for(ctx=ctx)
    agent_id = _agent_id_for(ctx=ctx)
    vigil = Vigil(backend=backend, state=rstate, work_dir=ctx.repo_root, agent_id=agent_id)
    poll = partial(
        poll_comments,
        backend=backend,
        state=rstate,
        agent_id=agent_id,
        work_dir=ctx.repo_root,
    )
    return vigil, poll


# Spec-0062/T4：新栈守候段合并推进偏函数——merge_pr 绑定 backend/state/身份/work_dir/hold/skip，
# 供 Vigil.run 每轮以 merge(runs=, now=) 调用推进 PR 合并。与 _new_vigil_for 分列（后者被 recipes.fleet
# 直接解包 (vigil, poll)，签名不可变），本工厂按每次 vigil 调用注入本轮解析出的 hold/skip。
def _new_merge_for(*, ctx: ProjectContext, hold, skip):
    from functools import partial

    from openagents.recipes.merge_pr import merge_pr

    return partial(
        merge_pr,
        backend=_backend_for(),
        state=_new_runtime_state_for(ctx=ctx),
        agent_id=_agent_id_for(ctx=ctx),
        work_dir=ctx.repo_root,
        hold=hold,
        skip=skip,
    )


# Spec-0062/T4：一轮守候一次性——先 poll_comments 回应 PR 上的新人类评论，再 merge_pr 推进合并
# （runs=None → 默认扫所有 open PR 派生迭代源）。poll/watch 共用；backend/state/身份一次构造两段共享。
def _poll_once(*, ctx: ProjectContext) -> list[dict]:
    from openagents.recipes.merge_pr import merge_pr
    from openagents.recipes.poll_comments import poll_comments

    backend = _backend_for()
    state = _new_runtime_state_for(ctx=ctx)
    agent_id = _agent_id_for(ctx=ctx)
    poll_comments(backend=backend, state=state, agent_id=agent_id, work_dir=ctx.repo_root)
    return merge_pr(backend=backend, state=state, agent_id=agent_id, work_dir=ctx.repo_root)


def _cmd_init(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0015 / Spec-0023/T1：统一冷启动兜底——确保全部流程标签就位（幂等：已存在即 no-op），
    # 预建 openagents / rfc-approved / needs-human，消除后续 add_label 报 not found。test 分支
    # 门控退役后日常 base 改回恒存在的 main，已无需任何分支自举。
    github.ensure_prerequisites()
    print(f"✓ 项目已就绪：{ctx.repo_root}（远端：{ctx.remote}）")
    # Spec-0030/T3：项目就绪后追加一段非阻塞前端 e2e 环境体检（检测 browser MCP + 权限模式），
    # 缺失只打印告知与设置方式、不改退出码（恒 return 0）。仅此一处接线，编排核心不感知体检。
    from openagents.utils import envcheck

    print()
    print(envcheck.check().text)
    return 0


def _cmd_rfc(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0062/T4：改接新栈 recipes.rfc_lifecycle.draft_rfc（判断在 drafter agent、控制流在 recipe）。
    # Spec-0039/T3：起草前自举一次结构性 prerequisite（流程标签，与 _cmd_vigil/_cmd_init/release
    # 同源）——draft_rfc 走 _claim 给 issue 打 DISPATCH_LABEL 认领标签，而 `gh issue edit --add-label`
    # 对仓库中不存在的标签报 not found 抛 GithubError。故 `oa rfc` 与 vigil 一样在入口幂等预建流程标签。
    from openagents.recipes import rfc_lifecycle

    github.ensure_prerequisites()
    result = rfc_lifecycle.draft_rfc(
        issue_number=args.issue, base=args.base, **_rfc_kwargs(ctx=ctx)
    )
    print(f"✓ 已为 issue #{args.issue} 起草 RFC 并开 draft PR #{result['pr_number']}")
    return 0


def _cmd_backfill_rfc(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0062/T4：改接新栈 recipes.rfc_lifecycle.backfill_rfc（据代码路径反推 spec 开 draft PR）。
    from openagents.recipes import rfc_lifecycle

    result = rfc_lifecycle.backfill_rfc(path=args.path, base=args.base, **_rfc_kwargs(ctx=ctx))
    print(f"✓ 已为 `{args.path}` 反向补全 spec 并开 draft PR #{result['pr_number']}")
    return 0


def _cmd_refine_rfc(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0062/T4：改接新栈 recipes.rfc_lifecycle.refine_rfc——取该 PR 最新评论作评审意见精炼 spec。
    from openagents.recipes import rfc_lifecycle

    detail = _latest_comment_body(pr_number=args.pr)
    if detail is None:
        print(f"✗ PR #{args.pr} 暂无可用于精炼 RFC 的评论", file=sys.stderr)
        return 1
    rfc_lifecycle.refine_rfc(pr_number=args.pr, detail=detail, **_rfc_kwargs(ctx=ctx))
    print(f"✓ 已按评审意见精炼 PR #{args.pr} 的 RFC 并回贴说明")
    return 0


def _cmd_implement(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0062/T4：改接新栈 recipes.rfc_lifecycle.implement——按获批 spec 实现代码并把 draft PR 转正。
    from openagents.recipes import rfc_lifecycle

    rfc_lifecycle.implement(pr_number=args.pr, **_rfc_kwargs(ctx=ctx))
    print(f"✓ 已按 RFC 实现 PR #{args.pr} 的代码并转正")
    return 0


def _cmd_solve(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0060/T6：走新栈 solve_issue recipe 的薄接线（additive；旧路由不动）。cli 只做「立沙箱 +
    # 组装上下文 + 调 recipe」的编排 glue，业务判断全在 agent、控制流在 recipe、硬闸在 runtime。
    # worktree 建/拉是 agent 无法自建沙箱的编排 git，仍由 utils.git.Workspace（薄再导出 workspace.py）承担。
    from openagents.recipes.solve_issue import solve_issue
    from openagents.runtime.context import Context
    from openagents.utils import git as gitutils

    github.ensure_prerequisites()
    branch = f"openagents/issue-{args.issue}"
    worktree = gitutils.Workspace(work_dir=ctx.repo_root).prepare(
        issue_number=args.issue, branch=branch, base=args.base
    )
    # PR 号缺省则按分支查找（无则 None——首轮起草尚未开 PR，评审历史注入自动降级为仅 issue 上下文）。
    pr_number = args.pr
    if pr_number is None:
        pr = github.find_pr_by_branch(branch=branch)
        pr_number = pr.number if pr is not None else None
    context = Context(
        work_dir=worktree, issue_number=args.issue, branch=branch, pr_number=pr_number
    )
    report = solve_issue(issue_number=args.issue, backend=_backend_for(), ctx=context)
    print(f"✓ 新栈 solve_issue 完成 issue #{args.issue}：{report.get('summary', '（无摘要）')}")
    return 0


def _cmd_iterate(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0062/T4：改接新栈 recipes.rfc_lifecycle.iterate——coding 阶段就 comment/CI 反馈手动迭代。
    from openagents.recipes import rfc_lifecycle

    if args.reason == "ci":
        detail = "\n".join(github.check_status(pr_number=args.pr).failed_logs)
    else:
        detail = _latest_comment_body(pr_number=args.pr) or ""
    rfc_lifecycle.iterate(
        pr_number=args.pr, reason=args.reason, detail=detail, **_rfc_kwargs(ctx=ctx)
    )
    print(f"✓ 已就 PR #{args.pr} 的 {args.reason} 反馈迭代")
    return 0


def _latest_comment_body(*, pr_number: int) -> str | None:
    # RFC-0005 决策 6 / RFC-0019：仅供**手动** refine_rfc / iterate 取最近一条评论作上下文
    # （人显式发起、无自循环风险，故不做任何过滤）。自动流转不走这里——PR 上的人机对话由新栈
    # 守候段 recipes.poll_comments 驱动（Spec-0062/T4），评论驱动读侧已退役（见 RFC-0012 / RFC-0019）。
    comments = github.list_comments(pr_number=pr_number)
    if not comments:
        return None
    return max(comments, key=lambda c: c.created_at).body


def _cmd_issue(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0002 T2：把 title/body/labels 透传给 github 层提 issue（决策 1）。
    # RFC-0002 决策 5：在用户标签之外追加发现标签并去重（保留出现顺序），
    # 使 openagents 自己提的 issue 总能被守夜人发现。dict.fromkeys 既去重又保序。
    labels = list(dict.fromkeys([*args.label, DISCOVERY_LABEL]))
    # Spec-0020/T4：默认先做一轮前门对齐——用 align（延迟 import）调 backend 把草稿复述成
    # 三段，打印给人、读 y/n；未确认则干净中止（不建、非零退出）。复述/拆解逻辑都在 align，
    # cli 只管打印 + 读输入 + 决定建不建（业务下沉、cli 只编排）。--yes 跳过供自动化路径。
    if not args.yes and not _confirm_issue_alignment(title=args.title, body=args.body):
        print("✗ 未确认对齐，已取消创建 issue", file=sys.stderr)
        return 1
    # RFC-0002 决策 6：gh issue create --label 要求标签预先存在，先确保发现标签已建。
    github.ensure_label(name=DISCOVERY_LABEL)
    issue = github.create_issue(title=args.title, body=args.body, labels=labels)
    print(f"✓ 已创建 issue #{issue.number}：{issue.title}")
    return 0


def _confirm_issue_alignment(*, title: str, body: str) -> bool:
    # Spec-0020/T4：建 issue 前的前门对齐——复述给人看，读应答判定是否放行。
    from openagents.utils import align

    alignment = align.restate(draft=align.Draft(title=title, body=body), backend=_backend_for())
    print("提 issue 前先对齐一下范围：")
    print(alignment.render())
    answer = input("看起来对吗？确认创建请输入 y / yes：")
    return align.is_confirmed(answer=answer)


def _cmd_reply_comment(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # coding agent 回评论的唯一出口：post_signed_comment 盖本实例签名（agent_id 幂等解析，与
    # poll/vigil 一致）→ 回复带签名 → 不被下一轮 poll 的 new_human_comments 当成新人类评论（防自循环）。
    from openagents.utils import identity

    identity.post_signed_comment(pr_number=args.pr, body=args.body, agent_id=_agent_id_for(ctx=ctx))
    print(f"✓ 已以本 agent 身份回复 PR #{args.pr} 的评论")
    return 0


def _cmd_poll(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0062/T4：一次性守候——poll_comments 回应新人类评论 + merge_pr 推进合并（收编旧 poll-comments）。
    # Spec-0055/T1：进 poll 前固化一次 e2e 能力状态量（供本轮起草/评审读）。
    _persist_ui_capable(ctx=ctx)
    events = _poll_once(ctx=ctx)
    print(f"✓ poll 完成，处理 {len(events)} 个事件")
    return 0


def _cmd_watch(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0062/T4：按间隔循环守候一次性（poll_comments + merge_pr），无 open PR 或 Ctrl-C 时退出。
    # Spec-0055/T1：进循环前固化一次 e2e 能力状态量。
    import time

    _persist_ui_capable(ctx=ctx)
    try:
        while github.list_open_prs():
            _poll_once(ctx=ctx)
            if not github.list_open_prs():
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    return 0


def _cmd_vigil(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0062/T4：守夜人主循环全量改接新栈（收编旧 vigil-new）——发现→分诊(triager)→派单(solve_issue)，
    # 每轮守候段回应评论(poll_comments) + 推进合并(merge_pr)。--label 缺省回落发现标签（决策 2）。
    from openagents.utils.hold import parse_hold
    from openagents.utils.skip import parse_skip, reconcile_hold_skip

    labels = args.label if args.label else [DISCOVERY_LABEL]
    # Spec-0020/T4：把 --hold 原始串解析成 Hold（None → 默认全不停）；Spec-0054/T3：--skip 解析成 Skip
    # （None → 全闸开启）再 reconcile 校验与 hold 对同一闸的矛盾意图。非法值 / 矛盾都抛 ValueError，
    # 经 _run 的异常通道转干净一行提示（不 traceback）。hold/skip 经守候段 merge_pr 落地（对称短路）。
    hold = parse_hold(raw=args.hold)
    skip = parse_skip(raw=args.skip)
    reconcile_hold_skip(hold=hold, skip=skip)
    # RFC-0015 / Spec-0023/T1：进主循环前自举一次结构性 prerequisite（流程标签），使无人值守
    # 的守夜进程自恢复——全新仓库直接 vigil（不先 init）也能跑通发现段。只在进循环前一次。
    github.ensure_prerequisites()
    # Spec-0055/T1：进主循环前固化一次 e2e 能力状态量（与 ensure_prerequisites 同为「进循环前一次」）。
    _persist_ui_capable(ctx=ctx)
    vigil, poll = _new_vigil_for(ctx=ctx)
    merge = _new_merge_for(ctx=ctx, hold=hold, skip=skip)
    vigil.run(
        interval=args.interval,
        labels=labels,
        base=args.base,
        once=args.once,
        poll=poll,
        merge=merge,
    )
    return 0


def _cmd_fleet(args: argparse.Namespace) -> int:
    # Spec-0062/T4：多仓库统管薄路由（vigil-all 收编为本命令别名）——读 fleet 配置（utils.fleet_config
    # 解析）→ run_fleet 扇出新栈 vigil（每仓一子进程）。不取 cwd 项目 ctx（统管的是配置里的别的仓库，
    # 可在任意目录运行；preflight 由各子进程在自己仓库里做），故在 _dispatch 里跳过 cwd preflight。
    from openagents.recipes.fleet import run_fleet
    from openagents.utils.fleet_config import load_fleet_config

    plans = load_fleet_config(path=Path(args.config))
    run_fleet(plans=plans, once=args.once)
    return 0


def _cmd_release(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0023/T4：人唯一的宏观决策点——预检（无 BLOCKED/needs-human + main CI 绿）通过则
    # 把 main 当前 HEAD 物化为 release/vX.Y.Z 分支 + tag。失败按预检原因设非零退出码，不发布。
    from openagents.utils.release import release

    result = release(state=_state_for(repo_root=ctx.repo_root), bump=args.bump)
    if result.released:
        print(f"✓ 已发布 {result.version}（release/{result.version} 分支 + tag）")
        return 0
    print(f"✗ release 预检未通过：{result.reason}", file=sys.stderr)
    return 1


def _cmd_board(args: argparse.Namespace) -> int:
    # RFC-0001 T6：board 不要求 git/remote（跳过 preflight），尽力解析 repo 根定位 state。
    from openagents.utils.results import board

    ctx = resolve_project()
    repo_root = ctx.repo_root if ctx is not None else Path.cwd()
    path = board(state=_state_for(repo_root=repo_root))
    print(f"✓ 成果看板：{path}")
    return 0


def _dispatch(args: argparse.Namespace) -> int:
    # board 不操作仓库，跳过 preflight（决策 10）
    if args.command == "board":
        return _cmd_board(args)

    # Spec-0027/T3 + Spec-0062/T4：vigil-all / fleet 统管的是配置里列出的别的仓库，cwd 不必是 git
    # 仓库——同 board 跳过 cwd 项目 preflight，直接读配置并扇出（preflight 由各子进程在自己的仓库里做）。
    # vigil-all 收编为 fleet 的别名，两栈合一后单一实现（同参 --config/--once，同走新栈 run_fleet）。
    if args.command in ("vigil-all", "fleet"):
        return _cmd_fleet(args)

    ctx = ensure_project(interactive=True)
    handlers = {
        "init": _cmd_init,
        "rfc": _cmd_rfc,
        "backfill-rfc": _cmd_backfill_rfc,
        "refine-rfc": _cmd_refine_rfc,
        "implement": _cmd_implement,
        "solve": _cmd_solve,
        "iterate": _cmd_iterate,
        "issue": _cmd_issue,
        "reply-comment": _cmd_reply_comment,
        "poll": _cmd_poll,
        "watch": _cmd_watch,
        "vigil": _cmd_vigil,
        "release": _cmd_release,
    }
    return handlers[args.command](args, ctx)


def _run(args: argparse.Namespace) -> int:
    # RFC-0003 决策 9：把已知的运行期错误转成干净的一行提示 + 非零退出，
    # 不再把 Python traceback 糊用户一脸（业务异常延迟 import）。
    # Spec-0062/T4：错误类型改接新栈——RFC 生命周期编排失败走 recipes.rfc_lifecycle.RfcLifecycleError
    # + runtime 层的 GateError（head 未前移/证据戳不匹配）/ AgentOutputError（agent 结构化输出非法）；
    # WorkspaceError/FleetConfigError 改从 utils 稳定面 import。
    from openagents.recipes.rfc_lifecycle import RfcLifecycleError
    from openagents.runtime.engine import AgentOutputError
    from openagents.runtime.gates import GateError
    from openagents.utils.fleet_config import FleetConfigError
    from openagents.utils.git import WorkspaceError
    from openagents.utils.github import GithubError

    try:
        return _dispatch(args)
    except ModuleNotFoundError as exc:
        # RFC-0003 决策 9（精炼）：宣告过的第三方依赖缺失，不是「真实 bug」而是装环境漏了
        # （如 venv 未 `uv pip install -e .` 时 import ruamel/jsonschema 失败）——转成可操作的
        # 一行提示而非深层 traceback。但 `openagents.*` 自身模块缺失仍是真 bug，照旧抛 traceback。
        top = (exc.name or "").split(".", 1)[0]
        if top == "openagents":
            raise
        print(
            f"✗ 缺少依赖 '{exc.name}'：请在项目根目录重装依赖后重试："
            f"uv pip install -e .（或 uv sync）",
            file=sys.stderr,
        )
        return 1
    except (
        RfcLifecycleError,
        GateError,
        AgentOutputError,
        GithubError,
        WorkspaceError,
        FleetConfigError,
        RuntimeError,
        ValueError,
    ) as exc:
        # Spec-0020/T4：ValueError 纳入已知运行期错误——vigil --hold 非法值由 hold.parse_hold
        # 抛 ValueError，在此转成干净一行提示 + 非零退出，而非把 traceback 糊用户一脸。
        # Spec-0027/T3：fleet 配置非法（缺 repos / 未知键 / path 缺失）由 load_fleet_config 抛
        # FleetConfigError，同样转干净一行——配置即可漂移源，报错要可操作（见 spec Drawbacks）。
        print(f"✗ {exc}", file=sys.stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(sys.stderr)
        return 2
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
