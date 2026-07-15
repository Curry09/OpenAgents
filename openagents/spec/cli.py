"""spec CLI（console_script: `spec`）：new / add-task / render / validate / abandon / graph。

2026-06-24 spec-markdown-form：spec 组改为单 markdown 文件；`spec amend` 退役（直接编辑组
markdown 即可，历史交给 git）；新增 `spec graph` 生成「对代码的唯一映射」ARCHITECTURE.md。

薄路由层（理念 1 奥卡姆）：把子命令转发到 mutate / render / validate / graph / ownership，自己不含
业务逻辑。
- spec new       <slug> --issue --title    → mutate.create_group
- spec add-task  <group> --id --title …    → mutate.add_task
- spec render                              → 写 OVERVIEW.md
- spec validate                            → 有 error 退出码非 0
- spec abandon   <group> <task> --reason   → mutate.abandon（从快照移除，历史在 git）
- spec graph     [--check]                 → 写 ARCHITECTURE.md / 校验 docstring + 漂移
- spec ownership [--group --changed --check] → 打印单一 writer 表 / 校验 changeset 无越权写（Spec-0071）

默认 specs 根为 docs/specs（可用 --specs-root 覆盖）；graph 默认扫 openagents 包。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from openagents.spec import graph, model, mutate, ownership
from openagents.spec.render import write_overview
from openagents.spec.schema import PRIORITY_VALUES, STATUS_VALUES
from openagents.spec.validate import validate

_DEFAULT_SPECS_ROOT = Path("docs/specs")
_DEFAULT_PACKAGE_ROOT = Path("openagents")


def _csv(value: str) -> list[str]:
    """逗号分隔串 → 去空白的非空项列表（供 --files / --depends-on）。"""
    return [item.strip() for item in value.split(",") if item.strip()]


def main(*, argv: list[str] | None = None) -> int:
    """Entry point for the `spec` console_script. 返回进程退出码（0 成功 / 非 0 失败）。"""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2

    specs_root = args.specs_root
    if args.command == "new":
        return _cmd_new(
            specs_root=specs_root,
            slug=args.slug,
            title=args.title,
            issue=args.issue,
            summary=args.summary,
            number=args.number,
        )
    if args.command == "add-task":
        return _cmd_add_task(specs_root=specs_root, args=args)
    if args.command == "render":
        return _cmd_render(specs_root=specs_root)
    if args.command == "validate":
        return _cmd_validate(specs_root=specs_root)
    if args.command == "abandon":
        return _cmd_abandon(
            specs_root=specs_root, group=args.group, task=args.task, reason=args.reason
        )
    if args.command == "graph":
        return _cmd_graph(specs_root=specs_root, package_root=args.package_root, check=args.check)
    if args.command == "ownership":
        return _cmd_ownership(
            specs_root=specs_root,
            group=args.group,
            changed=args.changed,
            check=args.check,
        )
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    """构造 argparse 解析器。--specs-root 放共享父解析器，子命令前后皆可写。"""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--specs-root",
        type=Path,
        default=_DEFAULT_SPECS_ROOT,
        help="specs 源数据根目录（默认 docs/specs）",
    )

    parser = argparse.ArgumentParser(prog="spec", description=__doc__, parents=[common])
    sub = parser.add_subparsers(dest="command")

    new = sub.add_parser("new", help="新建 spec 组（markdown 单文件）", parents=[common])
    new.add_argument("slug", help="组 slug（kebab-case 英文短名）")
    new.add_argument("--issue", type=int, required=True, help="关联 issue 编号")
    new.add_argument("--title", required=True, help="组标题")
    # Spec-0015：人话 TL;DR 必填——把「写 summary」做成建组硬步骤。
    new.add_argument("--summary", required=True, help="组级人话 TL;DR（必填）")
    new.add_argument("--number", default=None, help="组编号 NNNN（缺省取本地下一号）")

    add = sub.add_parser("add-task", help="往 spec 组加一个子任务", parents=[common])
    add.add_argument("group", help="组编号 NNNN 或文件名")
    add.add_argument("--id", required=True, dest="task_id", help="Task ID，如 T1")
    add.add_argument("--title", required=True, help="Task 标题")
    add.add_argument("--priority", choices=list(PRIORITY_VALUES), required=True, help="优先级")
    add.add_argument(
        "--status", choices=list(STATUS_VALUES), default="pending", help="状态（默认 pending）"
    )
    add.add_argument("--files", type=_csv, default=[], help="涉及文件（逗号分隔）")
    add.add_argument(
        "--depends-on", type=_csv, default=[], dest="depends_on", help="依赖（逗号分隔）"
    )
    add.add_argument("--scope", default="", help="子任务范围（Markdown）")
    add.add_argument("--acceptance", default="", help="验收标准（Markdown）")

    sub.add_parser("render", help="渲染 OVERVIEW.md", parents=[common])
    sub.add_parser("validate", help="校验 specs（schema + 语义）", parents=[common])

    abandon = sub.add_parser("abandon", help="从快照移除一个 Task（历史在 git）", parents=[common])
    abandon.add_argument("group", help="组编号 NNNN 或文件名")
    abandon.add_argument("task", help="Task ID，如 T3")
    abandon.add_argument("--reason", required=True, help="移除原因（记入提交信息）")

    g = sub.add_parser(
        "graph", help="生成/校验 ARCHITECTURE.md（对代码的唯一映射）", parents=[common]
    )
    g.add_argument(
        "--package-root",
        type=Path,
        default=_DEFAULT_PACKAGE_ROOT,
        help="要扫描的包（默认 openagents）",
    )
    g.add_argument("--check", action="store_true", help="CI 模式：校验 docstring 齐全 + 无漂移")

    own = sub.add_parser(
        "ownership",
        help="打印单一 writer 所有权表 / 校验 changeset 无越权写（Spec-0071）",
        parents=[common],
    )
    own.add_argument("--group", default=None, help="组编号 NNNN（--check 时必填，指定校验哪个组）")
    own.add_argument(
        "--changed",
        type=_csv,
        default=[],
        help="改动文件（逗号分隔，仓库相对路径）——供 --check 校验越权写",
    )
    own.add_argument(
        "--check",
        action="store_true",
        help="校验模式：--changed 里有本组无主写（越权写）则退出码 1",
    )

    return parser


def _cmd_new(
    *, specs_root: Path, slug: str, title: str, issue: int, summary: str, number: str | None
) -> int:
    """new 子命令：转发 mutate.create_group，打印新建文件。"""
    path = mutate.create_group(
        specs_root=specs_root, slug=slug, title=title, issue=issue, summary=summary, number=number
    )
    print(f"✓ 已新建 spec 组 {path.name}（{path}）")
    return 0


def _cmd_add_task(*, specs_root: Path, args: argparse.Namespace) -> int:
    """add-task 子命令：转发 mutate.add_task。"""
    task = mutate.add_task(
        specs_root=specs_root,
        group=args.group,
        task_id=args.task_id,
        title=args.title,
        priority=args.priority,
        status=args.status,
        files=args.files,
        depends_on=args.depends_on,
        scope=args.scope,
        acceptance=args.acceptance,
    )
    print(f"✓ 已加 Task {args.group}/{task.id}（{task.status}）")
    return 0


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


def _cmd_abandon(*, specs_root: Path, group: str, task: str, reason: str) -> int:
    """abandon 子命令：转发 mutate.abandon。"""
    mutate.abandon(specs_root=specs_root, group=group, task_id=task, reason=reason)
    print(f"✓ 已 abandon {group}/{task}")
    return 0


def _cmd_ownership(*, specs_root: Path, group: str | None, changed: list[str], check: bool) -> int:
    """ownership 子命令：--check 校验 changeset 无越权写（退出码 1）；否则打印单一 writer 所有权表。

    Spec-0071/T2: 把「单一 writer」文件所有权做成可查询/可校验的运行期面。--check 需 --group 指定
    校验哪个组，据 `spec.ownership.unowned_writes` 判无主写；无 --check 则逐组打印 owner→path 表。
    """
    groups = model.load_all(specs_root=specs_root)
    if check:
        if group is None:
            print("[error] --check 需配合 --group NNNN 指定校验哪个组")
            return 2
        target = next((g for g in groups if g.number == group), None)
        if target is None:
            print(f"[error] 找不到组 {group}（specs_root={specs_root}）")
            return 2
        offenders = ownership.unowned_writes(
            group=target, changed_paths=changed, specs_root=specs_root
        )
        for path in offenders:
            print(f"[error] {path}: 越权写（组 {target.number} 无 Task 声明该文件，且非生成物）")
        if offenders:
            print(f"✗ 越权写检测失败：{len(offenders)} 个无主写")
            return 1
        print(f"✓ 越权写检测通过（组 {target.number}，{len(list(changed))} 个改动全部有主/生成物）")
        return 0

    # 无 --check：打印单一 writer 所有权表（owner Task → 声明文件，按组、按 path 排序）。
    print("# 单一 writer 所有权表（Spec-0071：owner Task → 声明文件）")
    for grp in groups:
        index = ownership.build_index(group=grp)
        for path in sorted(index.by_path):
            print(f"{index.by_path[path]}\t{path}")
    return 0


def _cmd_graph(*, specs_root: Path, package_root: Path, check: bool) -> int:
    """graph 子命令：--check 校验 docstring + 漂移；否则生成 ARCHITECTURE.md。"""
    if not check:
        path = graph.write_architecture(specs_root=specs_root, package_root=package_root)
        print(f"✓ 已生成 {path}")
        return 0

    # --check：1) docstring 齐全；2) ARCHITECTURE.md 与代码无漂移。
    missing = graph.missing_docstrings(package_root=package_root)
    current = specs_root / graph.ARCHITECTURE_FILENAME
    expected = graph.render_architecture(package_root=package_root)
    drift = (not current.is_file()) or current.read_text(encoding="utf-8") != expected

    for path_str in missing:
        print(f"[error] {path_str}: 缺 docstring（文件级/模块级注释规范）")
    if drift:
        print(f"[error] {current}: 与代码不一致，请运行 `spec graph` 重新生成")
    if missing or drift:
        print("✗ graph 校验失败")
        return 1
    print("✓ graph 校验通过（docstring 齐全、无漂移）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
