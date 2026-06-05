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

from openagents.config import ProjectContext, ensure_project, resolve_project

# RFC-0002 决策 5 / RFC-0004 决策 2：发现标签——单一真源。
# `openagents issue` 提 issue 时自动附加它（使 issue 可被发现），vigil 发现段默认按它门控；
# 两端共用同一常量，保证「提 issue 用的标签」与「vigil 发现用的标签」永远一致。
DISCOVERY_LABEL = "openagents"


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
    # RFC-0003 决策 2/3：分支基线，默认 main；issue 分支从最新 origin/<base> 拉出。
    p_rfc.add_argument("--base", default="main", help="分支基线（默认 main）")

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
    p_vigil.add_argument("--base", default="main", help="派单起草 RFC 的分支基线（默认 main）")
    p_vigil.add_argument("--once", action="store_true", help="只跑一轮（发现+poll）后退出")

    return parser


# RFC-0001 T1: 业务对象工厂，延迟 import 各子任务模块；测试可对这些工厂打桩，
# 保持 cli 测试 hermetic（不触达真实 gh / claude / 浏览器）。
def _state_for(*, repo_root: Path):
    from openagents.state import State

    return State(path=repo_root / ".openagents" / "state.json")


def _orchestrator_for(*, ctx: ProjectContext):
    from openagents.backends.claude_code import ClaudeCodeBackend
    from openagents.orchestrator import Orchestrator

    return Orchestrator(
        backend=ClaudeCodeBackend(),
        state=_state_for(repo_root=ctx.repo_root),
        work_dir=ctx.repo_root,
    )


def _messages_for(*, ctx: ProjectContext):
    from openagents.messages import Messages

    return Messages(
        orchestrator=_orchestrator_for(ctx=ctx), state=_state_for(repo_root=ctx.repo_root)
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
    from openagents import github

    if args.reason == "ci":
        detail = "\n".join(github.check_status(pr_number=args.pr).failed_logs)
    else:
        detail = _latest_comment_body(pr_number=args.pr) or ""
    _orchestrator_for(ctx=ctx).iterate(pr_number=args.pr, reason=args.reason, detail=detail)
    print(f"✓ 已就 PR #{args.pr} 的 {args.reason} 反馈迭代")
    return 0


def _latest_comment_body(*, pr_number: int) -> str | None:
    # RFC-0005 决策 6：手动触发取最新一条评论作上下文（不按作者过滤——手动由人显式
    # 发起、无自循环风险；与 messages 自动 poll 同样不再按账号过滤）。
    from openagents import github

    comments = github.list_comments(pr_number=pr_number)
    if not comments:
        return None
    return max(comments, key=lambda c: c.created_at).body


def _cmd_issue(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0002 T2：把 title/body/labels 透传给 github 层提 issue（决策 1）。
    from openagents import github

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


def _cmd_vigil(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0004：守夜人主循环。--label 缺省回落到发现标签（决策 2，与提 issue 同源 → DISCOVERY_LABEL）。
    labels = args.label if args.label else [DISCOVERY_LABEL]
    _vigil_for(ctx=ctx).run(interval=args.interval, labels=labels, base=args.base, once=args.once)
    return 0


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
        "vigil": _cmd_vigil,
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
