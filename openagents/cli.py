"""RFC-0001 T1: CLI 入口。

唯一命令入口，注册 init/solve/poll/watch/board 子命令，仅做参数解析与分发；
业务逻辑下沉到各模块（命令体内延迟 import，保持 cli.py 文件归属单一、文件清单不重叠）。
除 board 外的命令在执行前先做项目绑定 preflight（决策 10）。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from openagents.config import ProjectContext, ensure_project, resolve_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openagents",
        description="RFC 驱动的多 Agent 框架：拉取 issue → 派单 agent → 提 PR。",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("init", help="绑定/初始化当前目录为 OpenAgents 项目")

    p_solve = sub.add_parser("solve", help="拉取并解决一个 GitHub issue")
    p_solve.add_argument("issue", type=int, help="issue 编号")
    # RFC-0003 决策 2/3：分支基线，默认 main；issue 分支从最新 origin/<base> 拉出。
    p_solve.add_argument("--base", default="main", help="分支基线（默认 main）")

    # RFC-0002 T2：主动往当前项目仓库提一个 GitHub issue。
    p_issue = sub.add_parser("issue", help="往当前项目仓库提一个 GitHub issue")
    p_issue.add_argument("title", help="issue 标题")
    p_issue.add_argument("--body", default="", help="issue 正文，默认空")
    p_issue.add_argument(
        "--label", action="append", default=[], metavar="LABEL", help="给 issue 打标签（可重复）"
    )

    sub.add_parser("poll", help="拉取并处理所有 PR 的新评论（一次性）")

    p_watch = sub.add_parser("watch", help="按间隔循环 poll（自动化拉取）")
    p_watch.add_argument("--interval", type=int, default=60, help="轮询间隔（秒），默认 60")

    sub.add_parser("board", help="启动本地成果看板")

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


def _cmd_init(args: argparse.Namespace, ctx: ProjectContext) -> int:
    print(f"✓ 项目已就绪：{ctx.repo_root}（远端：{ctx.remote}）")
    return 0


def _cmd_solve(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0001 T4 + RFC-0003: 派单个 agent 在每 issue 独立 worktree（基线 origin/<base>）中解决 issue 并开真实 PR。
    pr = _orchestrator_for(ctx=ctx).solve(issue_number=args.issue, base=args.base)
    print(f"✓ 已为 issue #{args.issue} 开 PR：{pr.url}")
    return 0


def _cmd_issue(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0002 T2：把 title/body/labels 透传给 github 层提 issue（决策 1）。
    from openagents import github

    issue = github.create_issue(title=args.title, body=args.body, labels=args.label)
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
        "solve": _cmd_solve,
        "issue": _cmd_issue,
        "poll": _cmd_poll,
        "watch": _cmd_watch,
    }
    return handlers[args.command](args, ctx)


def _run(args: argparse.Namespace) -> int:
    # RFC-0003 决策 9：把已知的运行期错误转成干净的一行提示 + 非零退出，
    # 不再把 Python traceback 糊用户一脸（业务异常延迟 import）。
    from openagents.github import GithubError
    from openagents.orchestrator import OrchestratorError

    try:
        return _dispatch(args)
    except (OrchestratorError, GithubError, RuntimeError) as exc:
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
