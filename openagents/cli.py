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

from openagents import github
from openagents.config import ProjectContext, ensure_project, resolve_project

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
    # RFC-0012 决策 2：默认由 main 改为长期 test 分支（体验服），PR base 同源锁 test。
    p_rfc.add_argument("--base", default="test", help="分支基线（默认 test）")

    p_refine = sub.add_parser("refine-rfc", help="按 PR 最新评审评论精炼 RFC")
    p_refine.add_argument("pr", type=int, help="PR 编号")

    p_impl = sub.add_parser("implement", help="RFC 获批后按 RFC 实现代码并转正 PR")
    p_impl.add_argument("pr", type=int, help="PR 编号")

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

    sub.add_parser("poll", help="拉取并处理所有 PR 的新评论（一次性）")

    p_watch = sub.add_parser("watch", help="按间隔循环 poll（自动化拉取）")
    p_watch.add_argument("--interval", type=int, default=60, help="轮询间隔（秒），默认 60")

    # RFC-0009 决策 6：自动 poll 路径的手动对应物——一次性把 open PR 同步到最新 main。
    p_sync = sub.add_parser("sync-prs", help="把最新 main 并入其余 open PR（合并后手动同步）")
    p_sync.add_argument(
        "--merged",
        type=int,
        default=None,
        metavar="N",
        help="要排除的已合并 PR 编号（缺省：不排除）",
    )
    p_sync.add_argument(
        "--rebase", action="store_true", help="用 rebase 而非 merge 方式同步（默认 merge）"
    )

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
    p_vigil.add_argument("--base", default="test", help="派单起草 RFC 的分支基线（默认 test）")
    p_vigil.add_argument("--once", action="store_true", help="只跑一轮（发现+poll）后退出")

    # RFC-0012 决策 7：promote —— 人唯一的宏观决策点：预检通过则把 test 快进到 main。
    sub.add_parser("promote", help="把 test 体验服快进到 main（预检通过后扬升）")

    return parser


# RFC-0001 T1: 业务对象工厂，延迟 import 各子任务模块；测试可对这些工厂打桩，
# 保持 cli 测试 hermetic（不触达真实 gh / claude / 浏览器）。
def _state_for(*, repo_root: Path):
    from openagents.state import State

    return State(path=repo_root / ".openagents" / "state.json")


# RFC-0011 决策 7：在接线处解析一次本实例身份，注入下游（Orchestrator / Messages /
# sync-prs 扇出）。resolve_agent_id 幂等（env > state > 首次生成落盘），多处调用得同一 id，
# 保证 solve / poll / vigil / sync-prs 跨进程一致。单列为工厂，便于测试打桩、不触达真实 state。
def _agent_id_for(*, ctx: ProjectContext) -> str:
    from openagents import identity

    return identity.resolve_agent_id(state=_state_for(repo_root=ctx.repo_root))


def _orchestrator_for(*, ctx: ProjectContext):
    from openagents.backends.claude_code import ClaudeCodeBackend
    from openagents.orchestrator import Orchestrator

    return Orchestrator(
        backend=ClaudeCodeBackend(),
        state=_state_for(repo_root=ctx.repo_root),
        work_dir=ctx.repo_root,
        agent_id=_agent_id_for(ctx=ctx),
    )


def _messages_for(*, ctx: ProjectContext):
    from openagents.messages import Messages

    return Messages(
        orchestrator=_orchestrator_for(ctx=ctx),
        state=_state_for(repo_root=ctx.repo_root),
        agent_id=_agent_id_for(ctx=ctx),
    )


# RFC-0004：守夜人——复用 orchestrator/messages/state 工厂，附 work_dir 供发现段去重。
def _vigil_for(*, ctx: ProjectContext):
    from openagents.vigil import Vigil

    return Vigil(
        orchestrator=_orchestrator_for(ctx=ctx),
        messages=_messages_for(ctx=ctx),
        state=_state_for(repo_root=ctx.repo_root),
        work_dir=ctx.repo_root,
    )


def _cmd_init(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0015：统一冷启动兜底——一次性确保 test 分支 + 全部流程标签就位（幂等：已存在
    # 即 no-op）。取代原先只兜底 test 分支的裸 ensure_branch（RFC-0012 决策 8），同时补齐
    # rfc-approved / needs-human 标签的预建，消除后续 add_label 报 not found。
    github.ensure_prerequisites()
    print(f"✓ 项目已就绪：{ctx.repo_root}（远端：{ctx.remote}）")
    return 0


def _cmd_rfc(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0005：起草 RFC 并开 draft PR（状态 rfc-review），等人评审。
    pr = _orchestrator_for(ctx=ctx).start_rfc(issue_number=args.issue, base=args.base)
    print(f"✓ 已为 issue #{args.issue} 起草 RFC 并开 draft PR：{pr.url}")
    return 0


def _cmd_refine_rfc(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0005：取该 PR 最新评论作评审意见，精炼 RFC 并回贴说明。
    detail = _latest_comment_body(pr_number=args.pr)
    if detail is None:
        print(f"✗ PR #{args.pr} 暂无可用于精炼 RFC 的评论", file=sys.stderr)
        return 1
    _orchestrator_for(ctx=ctx).refine_rfc(pr_number=args.pr, detail=detail)
    print(f"✓ 已按评审意见精炼 PR #{args.pr} 的 RFC 并回贴说明")
    return 0


def _cmd_implement(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0005：RFC 获批后按其实现代码并把 draft PR 转正（状态 pr-open）。
    _orchestrator_for(ctx=ctx).implement(pr_number=args.pr)
    print(f"✓ 已按 RFC 实现 PR #{args.pr} 的代码并转正")
    return 0


def _cmd_iterate(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0005：coding 阶段就 comment/CI 反馈手动迭代（与 poll 自动驱动同一操作）。
    if args.reason == "ci":
        detail = "\n".join(github.check_status(pr_number=args.pr).failed_logs)
    else:
        detail = _latest_comment_body(pr_number=args.pr) or ""
    _orchestrator_for(ctx=ctx).iterate(pr_number=args.pr, reason=args.reason, detail=detail)
    print(f"✓ 已就 PR #{args.pr} 的 {args.reason} 反馈迭代")
    return 0


def _latest_comment_body(*, pr_number: int) -> str | None:
    # RFC-0005 决策 6 / RFC-0019：仅供**手动** refine_rfc / iterate 取最近一条评论作上下文
    # （人显式发起、无自循环风险，故不做任何过滤）。自动流转不走这里——它由 reviewer 闸驱动，
    # messages.poll 不读 PR 评论（评论驱动读侧已退役，见 RFC-0012 / RFC-0019）。
    comments = github.list_comments(pr_number=pr_number)
    if not comments:
        return None
    return max(comments, key=lambda c: c.created_at).body


def _cmd_issue(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0002 T2：把 title/body/labels 透传给 github 层提 issue（决策 1）。
    # RFC-0002 决策 5：在用户标签之外追加发现标签并去重（保留出现顺序），
    # 使 openagents 自己提的 issue 总能被守夜人发现。dict.fromkeys 既去重又保序。
    labels = list(dict.fromkeys([*args.label, DISCOVERY_LABEL]))
    # RFC-0002 决策 6：gh issue create --label 要求标签预先存在，先确保发现标签已建。
    github.ensure_label(name=DISCOVERY_LABEL)
    issue = github.create_issue(title=args.title, body=args.body, labels=labels)
    print(f"✓ 已创建 issue #{issue.number}：{issue.title}")
    return 0


def _cmd_poll(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0001 T5: 一次性扫描所有 open PR 的 CI / 新评论并触发 iterate。
    events = _messages_for(ctx=ctx).poll()
    print(f"✓ poll 完成，处理 {len(events)} 个事件")
    return 0


def _cmd_watch(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0001 T5（决策 6）：按间隔循环 poll，自动化拉取直到无 open PR。
    _messages_for(ctx=ctx).watch(interval=args.interval)
    return 0


def _cmd_sync_prs(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0009 决策 6：延迟 import rebase 模块，调扇出同步并打印结果摘要（与既有命令风格一致）。
    from openagents import rebase

    # RFC-0011 决策 7：手动 sync-prs 也需透传本实例 agent_id（冲突留言据此盖章，防自循环）。
    events = rebase.rebase_open_prs(
        merged_pr_number=args.merged, rebase=args.rebase, agent_id=_agent_id_for(ctx=ctx)
    )
    print(f"✓ sync-prs 完成，同步 {len(events)} 个 open PR")
    return 0


def _cmd_vigil(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0004：守夜人主循环。--label 缺省回落到发现标签（决策 2，与提 issue 同源 → DISCOVERY_LABEL）。
    labels = args.label if args.label else [DISCOVERY_LABEL]
    # RFC-0015：进主循环前自举一次结构性 prerequisite（test 分支 + 流程标签），使无人值守
    # 的守夜进程自恢复——全新仓库直接 vigil（不先 init）也能跑通发现段，根除「缺 test 分支
    # 致 prepare 永久死循环」。只在进循环前一次，不进每轮循环（vigil「无人值守自恢复」定位）。
    github.ensure_prerequisites()
    _vigil_for(ctx=ctx).run(interval=args.interval, labels=labels, base=args.base, once=args.once)
    return 0


def _cmd_promote(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0012 决策 7：人唯一的宏观决策点——预检（无 BLOCKED/needs-human + test CI 绿）
    # 通过则把 test 快进到 main。失败按预检原因设非零退出码，不动 main。
    from openagents.promote import promote

    result = promote(state=_state_for(repo_root=ctx.repo_root))
    if result.promoted:
        print("✓ main 已快进到 test（promoted）")
        return 0
    print(f"✗ promote 预检未通过：{result.reason}", file=sys.stderr)
    return 1


def _cmd_board(args: argparse.Namespace) -> int:
    # RFC-0001 T6：board 不要求 git/remote（跳过 preflight），尽力解析 repo 根定位 state。
    from openagents.results import board

    ctx = resolve_project()
    repo_root = ctx.repo_root if ctx is not None else Path.cwd()
    path = board(state=_state_for(repo_root=repo_root))
    print(f"✓ 成果看板：{path}")
    return 0


def _dispatch(args: argparse.Namespace) -> int:
    # board 不操作仓库，跳过 preflight（决策 10）
    if args.command == "board":
        return _cmd_board(args)

    ctx = ensure_project(interactive=True)
    handlers = {
        "init": _cmd_init,
        "rfc": _cmd_rfc,
        "refine-rfc": _cmd_refine_rfc,
        "implement": _cmd_implement,
        "iterate": _cmd_iterate,
        "issue": _cmd_issue,
        "poll": _cmd_poll,
        "watch": _cmd_watch,
        "sync-prs": _cmd_sync_prs,
        "vigil": _cmd_vigil,
        "promote": _cmd_promote,
    }
    return handlers[args.command](args, ctx)


def _run(args: argparse.Namespace) -> int:
    # RFC-0003 决策 9：把已知的运行期错误转成干净的一行提示 + 非零退出，
    # 不再把 Python traceback 糊用户一脸（业务异常延迟 import）。
    from openagents.github import GithubError
    from openagents.orchestrator import OrchestratorError
    from openagents.workspace import WorkspaceError

    try:
        return _dispatch(args)
    except (OrchestratorError, GithubError, WorkspaceError, RuntimeError) as exc:
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
