"""RFC-0001 T1: CLI 入口。

唯一命令入口，注册 init/solve/poll/watch/board 子命令，仅做参数解析与分发；
业务逻辑下沉到各模块（命令体内延迟 import，保持 cli.py 文件归属单一、文件清单不重叠）。
除 board 外的命令在执行前先做项目绑定 preflight（决策 10）。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from openagents.config import ProjectContext, ensure_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openagents",
        description="RFC 驱动的多 Agent 框架：拉取 issue → 派单 agent → 提 PR。",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("init", help="绑定/初始化当前目录为 OpenAgents 项目")

    p_solve = sub.add_parser("solve", help="拉取并解决一个 GitHub issue")
    p_solve.add_argument("issue", type=int, help="issue 编号")

    sub.add_parser("poll", help="拉取并处理所有 PR 的新评论（一次性）")

    p_watch = sub.add_parser("watch", help="按间隔循环 poll（自动化拉取）")
    p_watch.add_argument("--interval", type=int, default=60, help="轮询间隔（秒），默认 60")

    sub.add_parser("board", help="启动本地成果看板")

    return parser


def _cmd_init(args: argparse.Namespace, ctx: ProjectContext) -> int:
    print(f"✓ 项目已就绪：{ctx.repo_root}（远端：{ctx.remote}）")
    return 0


def _cmd_solve(args: argparse.Namespace, ctx: ProjectContext) -> int:
    print(f"solve #{args.issue}：编排尚未实现（见 RFC-0001 T4）")
    return 0


def _cmd_poll(args: argparse.Namespace, ctx: ProjectContext) -> int:
    print("poll：消息机制尚未实现（见 RFC-0001 T5）")
    return 0


def _cmd_watch(args: argparse.Namespace, ctx: ProjectContext) -> int:
    print(f"watch（间隔 {args.interval}s）：消息机制尚未实现（见 RFC-0001 T5）")
    return 0


def _cmd_board(args: argparse.Namespace) -> int:
    print("board：成果看板尚未实现（见 RFC-0001 T6）")
    return 0


def _dispatch(args: argparse.Namespace) -> int:
    # board 不操作仓库，跳过 preflight（决策 10）
    if args.command == "board":
        return _cmd_board(args)

    ctx = ensure_project(interactive=True)
    handlers = {
        "init": _cmd_init,
        "solve": _cmd_solve,
        "poll": _cmd_poll,
        "watch": _cmd_watch,
    }
    return handlers[args.command](args, ctx)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(sys.stderr)
        return 2
    return _dispatch(args)


if __name__ == "__main__":
    sys.exit(main())
