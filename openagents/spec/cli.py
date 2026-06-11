"""spec CLI（console_script: `spec`）：render / amend / abandon / validate。

Spec-0014/T5: spec CLI + 编号校验脚本 + CI 接线

薄路由层（理念 1 奥卡姆）：把子命令转发到 render / mutate / validate，自己不含业务逻辑。
- spec render                          → 写 OVERVIEW.md
- spec validate                        → 有 error 退出码非 0；仅 warning 退 0 并打印
- spec amend   <group> <task> --reason → mutate.amend
- spec abandon <group> <task> --reason → mutate.abandon

默认 specs 根为 docs/specs（可用 --specs-root 覆盖）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from openagents.spec import mutate
from openagents.spec.render import write_overview
from openagents.spec.validate import validate

_DEFAULT_SPECS_ROOT = Path("docs/specs")


def main(*, argv: list[str] | None = None) -> int:
    """Entry point for the `spec` console_script.

    Spec-0014/T5: 解析子命令并分发；返回进程退出码（0 成功 / 非 0 失败）。
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2

    specs_root = args.specs_root
    if args.command == "render":
        return _cmd_render(specs_root=specs_root)
    if args.command == "validate":
        return _cmd_validate(specs_root=specs_root)
    if args.command == "amend":
        return _cmd_amend(
            specs_root=specs_root, group=args.group, task=args.task, reason=args.reason
        )
    if args.command == "abandon":
        return _cmd_abandon(
            specs_root=specs_root, group=args.group, task=args.task, reason=args.reason
        )
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    """构造 argparse 解析器（四个子命令）。

    --specs-root 放在共享父解析器里，因此既可写在子命令前也可写在其后
    （如 `spec render --specs-root docs/specs`）。
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--specs-root",
        type=Path,
        default=_DEFAULT_SPECS_ROOT,
        help="specs 源数据根目录（默认 docs/specs）",
    )

    parser = argparse.ArgumentParser(prog="spec", description=__doc__, parents=[common])
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("render", help="渲染 OVERVIEW.md", parents=[common])
    sub.add_parser("validate", help="校验 specs（schema + 语义）", parents=[common])

    for name, help_text in (("amend", "改一个 Task（追加历史）"), ("abandon", "废弃一个 Task")):
        sp = sub.add_parser(name, help=help_text, parents=[common])
        sp.add_argument("group", help="组编号 NNNN 或目录名")
        sp.add_argument("task", help="Task ID，如 T3")
        sp.add_argument("--reason", required=True, help="变更原因")

    return parser


def _cmd_render(*, specs_root: Path) -> int:
    """render 子命令：写 OVERVIEW.md 并打印路径。"""
    path = write_overview(specs_root=specs_root)
    print(f"✓ 已生成 {path}")
    return 0


def _cmd_validate(*, specs_root: Path) -> int:
    """validate 子命令：打印 issues；有 error 返回 1，仅 warning 返回 0。"""
    report = validate(specs_root=specs_root)
    for issue in report.issues:
        print(f"[{issue.level}] {issue.where}: {issue.message}")
    if not report.ok:
        print("✗ spec 校验失败（存在 error）")
        return 1
    print("✓ spec 校验通过")
    return 0


def _cmd_amend(*, specs_root: Path, group: str, task: str, reason: str) -> int:
    """amend 子命令：转发 mutate.amend。"""
    new_task = mutate.amend(specs_root=specs_root, group=group, task_id=task, reason=reason)
    print(f"✓ 已 amend {group}/{task} → v{new_task.version}")
    return 0


def _cmd_abandon(*, specs_root: Path, group: str, task: str, reason: str) -> int:
    """abandon 子命令：转发 mutate.abandon。"""
    mutate.abandon(specs_root=specs_root, group=group, task_id=task, reason=reason)
    print(f"✓ 已 abandon {group}/{task}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
