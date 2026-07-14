"""# Spec-0064/T5: CLI 入口——人面向收敛为 vigil / issue / backfill-rfc / release 四命令。

唯一命令入口，仅做参数解析与分发；业务逻辑下沉到各模块（命令体内延迟 import，保持 cli.py 文件归属
单一、文件清单不重叠）。

Spec-0064 收敛：`rfc`/`refine-rfc`/`implement`/`iterate`/`solve`/`poll`/`watch`/`vigil-all`/`fleet`
九条自动化环切片命令**并入 `vigil`**（都是 vigil 每轮自动做的事的手动单步版，人不再单敲）；`reply-comment`
降为**隐藏内部命令**（仍走 `utils.identity.post_signed_comment` 单一盖章出口，供子 agent 回评论、防自
循环闭环，不占人心智）。人真正要的宏观触发只剩四个正交动作：
  - `oa vigil` —— 自主环（读 `.openagents/openagents.yml` 决定用哪些 agent、每道闸归谁）；
  - `oa issue` —— 主动提 issue（直连 github.create_issue）；
  - `oa backfill-rfc <path>` —— path 驱动追溯（实现在前、设计在后）；
  - `oa release` —— 仓库级发版（确定性动作、直连 utils.release、无 agent）。
`init`（项目自举）与 `board`（只读观测，Unresolved Q1 暂保留独立）不进本收敛范围、照旧在册。

`.openagents/openagents.yml` 是「用哪些 agent + 每道闸归谁」的单一真源（经 T1 loader）；`--hold`/`--skip`/
`--base`/`--interval`/`--label` 仍可对**单次运行**覆盖 YAML——「单一真源」指声明式默认收敛到一处，不是
消灭所有 flag。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from openagents.utils import github
from openagents.utils.config import ProjectContext, ensure_project, resolve_project

# Spec-0065/T2: `--parallel K` 的上限。每个 worker 是一条常驻线程 + 一条私有 sqlite 连接 + 一个 agent 子进程，
# 且 K 个 worker 同时打 GitHub API（有速率限制）——K 大到某个程度只会换来更多的锁竞争和 429，不会更快。
# 真正的并发上限本就由 issue 依赖图（blocked_by）约束，这个数字只是个防手滑的护栏（`--parallel 99999`）。
_MAX_PARALLEL = 32


def _parallel_k(value: str) -> int:
    """argparse 的 `--parallel` 校验：必须是 `1..{_MAX_PARALLEL}` 的整数，否则当场报错。

    不静默钳位（早前是 `max(1, K)`）：`--parallel 0` 明显是手滑或误解，悄悄给成 1 会让人以为「并行开了但没
    变快」，把一个输入错误变成一个性能谜题。CLI 的错该在 CLI 里响。
    """
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--parallel 需要一个整数，收到 {value!r}") from None
    if not 1 <= parsed <= _MAX_PARALLEL:
        raise argparse.ArgumentTypeError(
            f"--parallel 需要落在 1..{_MAX_PARALLEL}（1 即串行），收到 {parsed}"
        )
    return parsed


# RFC-0002 决策 5 / RFC-0004 决策 2：发现标签——单一真源。`oa issue` 提 issue 时自动附加它，vigil 发现
# 段默认按它门控；两端共用同一常量。RFC-0015：字面量上移至 github，此处别名引用保向后兼容公共名。
DISCOVERY_LABEL = github.DISCOVERY_LABEL


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openagents",
        description="RFC 驱动的多 Agent 框架：拉取 issue → 派单 agent → 提 PR。",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("init", help="绑定/初始化当前目录为 OpenAgents 项目")

    # Spec-0064/T5：自主环——收编 rfc/implement/iterate/poll/watch/vigil-all/fleet 等自动化单步。
    p_vigil = sub.add_parser(
        "vigil", help="守夜人：自主监控 issue → 派单 → 守候 PR（读 openagents.yml）"
    )
    p_vigil.add_argument(
        "--interval", type=int, default=None, help="轮询间隔（秒），覆盖 YAML defaults"
    )
    p_vigil.add_argument(
        "--label",
        action="append",
        default=None,
        metavar="LABEL",
        help="issue 发现的标签门控（可重复），覆盖 YAML defaults",
    )
    p_vigil.add_argument("--base", default=None, help="派单起草改动的分支基线，覆盖 YAML defaults")
    p_vigil.add_argument("--once", action="store_true", help="只跑一轮（发现+守候）后退出")
    p_vigil.add_argument(
        # Spec-0065/T2：并发上限（同时最多几个 subject 在跑 agent）。**K=1 即退化串行**——并行不是
        # 另一种模式，只是这个数字大于 1。上限由 issue 依赖图（blocked_by）天然约束，不需要另设旋钮。
        "--parallel",
        type=_parallel_k,
        default=1,
        metavar="K",
        help=f"并发上限：同时最多 K 个 issue/PR 在跑 agent（默认 1，即串行；上限 {_MAX_PARALLEL}）",
    )
    p_vigil.add_argument(
        "--hold",
        default=None,
        metavar="STAGES",
        help="单次把指定阶段交给人（停等）：如 merge / review,merge（等价 stages.<stage>=human）",
    )
    p_vigil.add_argument(
        "--skip",
        default=None,
        metavar="STAGES",
        help="单次跳过指定阶段（当 PASS 放行）：如 ci / ci,e2e（等价 stages.<stage>=skip）",
    )
    p_vigil.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="openagents 配置文件路径（默认 .openagents/openagents.yml）",
    )

    # Spec-0064/T5：path 驱动追溯——扫存量代码路径反推 spec 并开 draft PR（实现先行、设计后补）。
    p_backfill = sub.add_parser("backfill-rfc", help="扫存量代码路径反推 spec 并开 draft PR")
    p_backfill.add_argument("path", help="要反向补全的代码路径（单文件或目录）")
    p_backfill.add_argument("--base", default="main", help="分支基线（默认 main）")

    # RFC-0002 T2：主动往当前项目仓库提一个 GitHub issue（独立创造工作的动作，直连 github.create_issue）。
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
    p_issue.add_argument(
        "--yes",
        action="store_true",
        help="跳过建 issue 前的对齐确认，直接创建（供 vigil/CI 等自动化路径）",
    )

    # Spec-0023/T4：release —— 人唯一的宏观决策点：预检通过则把持续推进的 main 物化成版本。
    p_release = sub.add_parser("release", help="把 main 当前 HEAD 发布为一个版本（预检通过后物化）")
    p_release.add_argument(
        "--bump",
        choices=["patch", "minor", "major"],
        default="patch",
        help="版本号递增位（默认 patch；从最新 vX.Y.Z tag 递增，无 tag 则起点 v0.1.0）",
    )

    sub.add_parser("board", help="启动本地成果看板")

    # Spec-0064/T5：reply-comment 降隐藏内部命令——被派子 agent（解冲突 agent 等）盖签名回评论的唯一
    # 出口，删了会破坏防自循环闭环（约束③）。仍走 identity.post_signed_comment。**不传 `help=`**：argparse
    # 只在提供 help 时才把子命令登进帮助清单，故省略 help 使它从 `--help` 列表隐去、但仍可解析分发（不占
    # 人心智；help=SUPPRESS 反而会打印字面 "==SUPPRESS==" 噪声）。
    p_reply = sub.add_parser("reply-comment")
    p_reply.add_argument("--pr", type=int, required=True, metavar="N", help="要回复的 PR 编号")
    p_reply.add_argument("--body", required=True, help="回复正文（会自动盖上本 agent 签名）")

    return parser


# --------------------------------------------------------------------------------------------------
# 工厂：backend / state / 身份 / e2e 能力固化（延迟 import 保持 cli 顶层轻、测试可打桩）。
# --------------------------------------------------------------------------------------------------


def _persist_ui_capable(*, ctx: ProjectContext) -> None:
    # Spec-0055/T1：守夜入口启动时把「前端 e2e 能力」固化进 state（单一真相源）。
    from openagents.utils import envcheck

    _new_runtime_state_for(ctx=ctx).set_ui_capable(value=envcheck.ui_capable())


def _agent_id_for(*, ctx: ProjectContext) -> str:
    # RFC-0011 决策 7：接线处解析一次本实例身份，注入下游（vigil / reply-comment）。
    from openagents.utils import identity

    return identity.resolve_agent_id(state=_new_runtime_state_for(ctx=ctx))


def _backend_for():
    # Spec-0020/T4：单列 backend 工厂——延迟 import 保持 cli 顶层轻、测试可对工厂打桩（不触真实 LLM）。
    from openagents.backends.claude_code import ClaudeCodeBackend

    return ClaudeCodeBackend()


def _new_runtime_state_for(*, ctx: ProjectContext):
    # Spec-0061/T4：新栈 RuntimeState 工厂——独立命名空间文件 runtime-state.json。
    from openagents.runtime.state import RUNTIME_STATE_FILENAME, RuntimeState

    return RuntimeState(path=ctx.repo_root / ".openagents" / RUNTIME_STATE_FILENAME)


def _vigil_deps_for(*, ctx: ProjectContext):
    """Spec-0064/T5：新栈守夜依赖三件套 (backend, state, agent_id)——run_vigil 的单一接线点。

    backend/state/身份一次构造，保证同一守夜进程内一致。recipes.vigil 的多仓子进程内联入口
    `_run_repo_inline` 也调本工厂（与 CLI `vigil` 同源），故本工厂是新栈守夜的单一接线点。
    """
    return _backend_for(), _new_runtime_state_for(ctx=ctx), _agent_id_for(ctx=ctx)


def _effective_config(*, ctx: ProjectContext, args: argparse.Namespace):
    """Spec-0064/T5：加载 `.openagents/openagents.yml`（单一真源）+ 叠加本次运行的 flag 覆盖。

    `--hold <stages>` → 把这些阶段单次交给人（owner=human，停等）；`--skip <stages>` → 单次跳过
    （owner=skip）；`--base`/`--interval`/`--label` 覆盖 defaults。覆盖后仍守「不许零闸」（review:skip +
    merge:agent → ValueError），且同阶段同时 hold+skip 矛盾 → ValueError。YAML + flag 并存（约束：flag
    是单次覆盖，不改磁盘配置）。
    """
    import dataclasses

    from openagents.utils.agent_config import (
        OWNER_AGENT,
        OWNER_HUMAN,
        OWNER_SKIP,
        STAGE_MERGE,
        STAGE_REVIEW,
        StagePolicy,
        load_agent_config,
    )

    config_path = (
        Path(args.config) if args.config else ctx.repo_root / ".openagents" / "openagents.yml"
    )
    config = load_agent_config(path=config_path)

    hold_stages = _parse_gate_list(raw=args.hold)
    skip_stages = _parse_gate_list(raw=args.skip)
    conflicting = hold_stages & skip_stages
    if conflicting:
        raise ValueError(f"--hold 与 --skip 对同一阶段矛盾：{sorted(conflicting)}")

    owners = dict(config.stages.owners)
    for stage in hold_stages:
        owners[stage] = OWNER_HUMAN
    for stage in skip_stages:
        owners[stage] = OWNER_SKIP
    # 覆盖后重守「不许零闸」（未审直接盲合进 main）。
    review = owners.get(STAGE_REVIEW, OWNER_AGENT)
    merge = owners.get(STAGE_MERGE, OWNER_AGENT)
    if review == OWNER_SKIP and merge == OWNER_AGENT:
        raise ValueError("不许零闸：--skip review 时须 --hold merge（否则未审代码自动盲合进 main）")

    stages = StagePolicy(owners=owners)
    updates: dict = {"stages": stages}
    if args.base is not None:
        updates["base"] = args.base
    if args.interval is not None:
        updates["interval"] = args.interval
    if args.label:
        updates["labels"] = list(args.label)
    return dataclasses.replace(config, **updates)


def _parse_gate_list(*, raw: str | None) -> set[str]:
    """把 `--hold ci,merge` 逗号串解析成阶段名集合（空/None → 空集）。"""
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


# --------------------------------------------------------------------------------------------------
# 命令 handler。
# --------------------------------------------------------------------------------------------------


def _cmd_init(args: argparse.Namespace, ctx: ProjectContext) -> int:
    github.ensure_prerequisites()
    print(f"✓ 项目已就绪：{ctx.repo_root}（远端：{ctx.remote}）")
    from openagents.utils import envcheck

    print()
    print(envcheck.check().text)
    return 0


def _cmd_vigil(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0065/T2：守夜主循环——读 openagents.yml（+flag 单次覆盖）→ run_vigil 图驱动并行守夜
    # （level-triggered reconcile：生产者按 GitHub 现态判定入队，K 个 worker 领 subject 推进）。
    # `--parallel K` 是并发上限；**K=1 即退化串行**（不是另一种模式）。多仓 → run_fleet 每仓一子进程。
    from openagents.recipes.vigil import run_fleet, run_vigil

    config = _effective_config(ctx=ctx, args=args)
    github.ensure_prerequisites()
    _persist_ui_capable(ctx=ctx)
    if len(config.repos) > 1:
        run_fleet(config=config, once=args.once)
        return 0
    backend, state, agent_id = _vigil_deps_for(ctx=ctx)
    run_vigil(
        backend=backend,
        state=state,
        work_dir=ctx.repo_root,
        config=config,
        once=args.once,
        concurrency=args.parallel,
        agent_id=agent_id,
    )
    return 0


def _cmd_backfill_rfc(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0064/T5：改接 recipes.backfill.backfill_rfc（据代码路径反推 spec 开 draft PR）。
    from openagents.recipes import backfill

    github.ensure_prerequisites()
    result = backfill.backfill_rfc(
        path=args.path, base=args.base, backend=_backend_for(), work_dir=ctx.repo_root
    )
    print(f"✓ 已为 `{args.path}` 反向补全 spec 并开 draft PR #{result['pr_number']}")
    return 0


def _cmd_issue(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0002 T2：提 issue（直连 github.create_issue）+ 追加发现标签去重保序。
    labels = list(dict.fromkeys([*args.label, DISCOVERY_LABEL]))
    if not args.yes and not _confirm_issue_alignment(title=args.title, body=args.body):
        print("✗ 未确认对齐，已取消创建 issue", file=sys.stderr)
        return 1
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
    # Spec-0064/T5：隐藏内部命令——coding agent 回评论的唯一出口。post_signed_comment 盖签名 + 同步后
    # 校验漏签 edit 补（约束③），使回复不被下一轮 poll 当成新人类评论（防自循环）。
    from openagents.utils import identity

    identity.post_signed_comment(pr_number=args.pr, body=args.body, agent_id=_agent_id_for(ctx=ctx))
    print(f"✓ 已以本 agent 身份回复 PR #{args.pr} 的评论")
    return 0


def _cmd_release(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0023/T4：确定性发版动作、无 agent——预检通过则物化 release/vX.Y.Z 分支 + tag。
    from openagents.utils.release import release

    result = release(state=_new_runtime_state_for(ctx=ctx), bump=args.bump)
    if result.released:
        print(f"✓ 已发布 {result.version}（release/{result.version} 分支 + tag）")
        return 0
    print(f"✗ release 预检未通过：{result.reason}", file=sys.stderr)
    return 1


def _cmd_board(args: argparse.Namespace) -> int:
    # RFC-0001 T6：board 不要求 git/remote（跳过 preflight），读新栈 RuntimeState 渲染看板。
    from openagents.utils.results import board

    ctx = resolve_project()
    if ctx is None:
        ctx = ProjectContext(repo_root=Path.cwd(), remote=None)
    path = board(state=_new_runtime_state_for(ctx=ctx))
    print(f"✓ 成果看板：{path}")
    return 0


def _dispatch(args: argparse.Namespace) -> int:
    # board 不操作仓库，跳过 preflight（决策 10）。
    if args.command == "board":
        return _cmd_board(args)

    ctx = ensure_project(interactive=True)
    handlers = {
        "init": _cmd_init,
        "vigil": _cmd_vigil,
        "backfill-rfc": _cmd_backfill_rfc,
        "issue": _cmd_issue,
        "reply-comment": _cmd_reply_comment,
        "release": _cmd_release,
    }
    return handlers[args.command](args, ctx)


def _run(args: argparse.Namespace) -> int:
    # RFC-0003 决策 9：把已知运行期错误转成干净一行提示 + 非零退出，不糊 traceback（业务异常延迟 import）。
    # Spec-0064/T5：错误类型改接收敛后新栈——backfill 编排失败走 recipes.backfill.BackfillError；配置
    # 非法走 utils.agent_config.AgentConfigError；runtime GateError / AgentOutputError；utils 稳定面
    # GithubError / WorkspaceError。
    from openagents.recipes.backfill import BackfillError
    from openagents.runtime.engine import AgentOutputError
    from openagents.runtime.gates import GateError
    from openagents.utils.agent_config import AgentConfigError
    from openagents.utils.git import WorkspaceError
    from openagents.utils.github import GithubError

    try:
        return _dispatch(args)
    except ModuleNotFoundError as exc:
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
        BackfillError,
        AgentConfigError,
        GateError,
        AgentOutputError,
        GithubError,
        WorkspaceError,
        RuntimeError,
        ValueError,
    ) as exc:
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
