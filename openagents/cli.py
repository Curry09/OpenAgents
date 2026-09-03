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

`.openagents/openagents.yml` 是「用哪些 agent + 每道闸归谁」的单一真源（经 T1 loader）；`--skip`/
`--base`/`--interval`/`--label` 仍可对**单次运行**覆盖 YAML——「单一真源」指声明式默认收敛到一处，不是
消灭所有 flag。
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

# Spec-0069/T1：Shell Tab 补全——直接读现成 argparse parser 生成候选（命令清单单一真源仍是 build_parser，
# 不维护第二份会漂移的补全脚本）。顶层做优雅降级导入：argcomplete 是声明依赖、正常一定装了，但万一环境缺失
# （老快照 / 精简安装），补全应静默不可用而非拖垮整个 CLI。
try:
    import argcomplete
except ImportError:  # pragma: no cover - argcomplete 是声明依赖；缺失时补全静默降级
    argcomplete = None

# Spec-0074/T1: alias-import 换轨——平台操作经 forge 分发层按配置委托 github/gitea driver，调用点零改动。
from openagents.utils import forge as github
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

    # Spec-0067/T2：init 除就绪校验外，顺手把默认 .openagents/openagents.yml 生成出来（幂等）。
    p_init = sub.add_parser("init", help="绑定/初始化当前目录为 OpenAgents 项目（并生成默认配置）")
    p_init.add_argument(
        "--force",
        action="store_true",
        help="用包内最新模板覆盖已存在的 .openagents/openagents.yml（默认幂等、不覆盖用户改动）",
    )

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

    # Spec-0085/T2: finite, explicit v0.2 batch; unlike vigil it never polls or waits for humans.
    p_v02 = sub.add_parser("v02", help="运行一次 v0.2 批次：Spec → DAG → Developer → Acceptance → merge")
    p_v02.add_argument(
        "--issue", type=int, action="append", required=True, metavar="N", help="批次 issue 编号（可重复）"
    )
    p_v02.add_argument(
        "--parallel", type=_parallel_k, default=4, metavar="K", help="Spec/Developer 并发上限（默认 4）"
    )
    p_v02.add_argument("--base", default=None, help="目标分支（默认读配置，通常为 main）")
    p_v02.add_argument(
        "--config", default=None, metavar="PATH", help="配置文件（默认 .openagents/openagents.yml）"
    )
    p_v02.add_argument(
        "--user-test-command",
        default=None,
        metavar="COMMAND",
        help="实际用户测试 harness 命令（需同时提供 --user-test-transcript）",
    )
    p_v02.add_argument(
        "--user-test-transcript",
        default=None,
        metavar="PATH",
        help="JSON 用户事件数组；在候选副本中执行并作为 Acceptance 主证据",
    )
    p_v02.add_argument(
        "--user-test-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="用户测试墙钟上限（默认 900 秒）",
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

    # Spec-0073/T2：desktop 起本地 daemon（HTTP+SSE）供 Electron 桌面 app 读 work_queue/流；只读呈现。
    p_desktop = sub.add_parser(
        "desktop", help="启动本地 daemon（HTTP+SSE）供桌面 app 呈现 vigil --parallel 并行成果"
    )
    p_desktop.add_argument(
        "--host", default="127.0.0.1", metavar="HOST", help="监听地址（默认仅本机 127.0.0.1）"
    )
    p_desktop.add_argument(
        "--port", type=int, default=8765, metavar="PORT", help="监听端口（默认 8765；0=系统分配）"
    )

    # Spec-0066/T3：读 .openagents/timing.jsonl，输出单 issue 各阶段墙钟时长 + 跨 issue p50/p90 文本报告
    # （定位流水线瓶颈：CI 排队 / review 卡顿 / 轮询等待各占多久）。薄路由，聚合逻辑在 runtime.timing。
    p_report = sub.add_parser(
        "report", help="读 timing.jsonl 输出各阶段墙钟时延报告（单 issue 时间线 + p50/p90）"
    )
    p_report.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="openagents 配置文件路径（默认 .openagents/openagents.yml，用于读轮询 interval 作精度下限标注）",
    )

    # Spec-0064/T5：reply-comment 降隐藏内部命令——被派子 agent（解冲突 agent 等）盖签名回评论的唯一
    # 出口，删了会破坏防自循环闭环（约束③）。仍走 identity.post_signed_comment。**不传 `help=`**：argparse
    # 只在提供 help 时才把子命令登进帮助清单，故省略 help 使它从 `--help` 列表隐去、但仍可解析分发（不占
    # 人心智；help=SUPPRESS 反而会打印字面 "==SUPPRESS==" 噪声）。
    # Spec-0074/T1：merge-pr 隐藏内部命令——merger agent 落合并的**平台无关**出口（与 reply-comment 同
    # 定位：不传 help= 从帮助清单隐去、仍可解析分发）。GitHub 侧 merger 仍直接跑 gh pr merge（零变化）；
    # Gitea 侧的 $merge_command 即本命令，token 处理留在 driver 内、凭证不进提示词。
    p_merge_pr = sub.add_parser("merge-pr")
    p_merge_pr.add_argument("--pr", type=int, required=True, metavar="N", help="要合并的 PR 编号")
    p_merge_pr.add_argument(
        "--method", default="merge", choices=["merge", "squash", "rebase"], help="合并方式"
    )

    p_reply = sub.add_parser("reply-comment")
    # Spec-0016/T5：--pr / --issue 二选一（互斥必选组）——issue #149 把签名回复从 PR 扩到 issue 页，
    # 手动出口对称补 --issue。仍不传 help=（隐藏内部命令，Spec-0064/T5 定位不变）。
    p_reply_target = p_reply.add_mutually_exclusive_group(required=True)
    p_reply_target.add_argument("--pr", type=int, metavar="N", help="要回复的 PR 编号")
    p_reply_target.add_argument("--issue", type=int, metavar="N", help="要回复的 issue 编号")
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
    if os.environ.get("OPENAGENTS_BACKEND", "").strip() == "nexau":
        from openagents.backends.nexau import NexAUBackend

        return NexAUBackend()
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

    `--skip <stages>` → 单次跳过（owner=skip）；`--base`/`--interval`/`--label` 覆盖 defaults。
    覆盖后仍守阶段合法取值、架构评审配套和「不许零闸」。YAML + flag 并存（flag 是单次覆盖，
    不改磁盘配置）。
    """
    import dataclasses

    from openagents.utils.agent_config import (
        OWNER_AGENT,
        OWNER_SKIP,
        STAGE_ARCHITECTURE,
        STAGE_CI,
        STAGE_E2E,
        STAGE_MERGE,
        STAGE_REVIEW,
        STAGE_RFC,
        STAGE_TRIAGE,
        StagePolicy,
        load_agent_config,
    )

    config_path = (
        Path(args.config) if args.config else ctx.repo_root / ".openagents" / "openagents.yml"
    )
    config = load_agent_config(path=config_path)

    skip_stages = _parse_gate_list(raw=args.skip)
    skippable = {STAGE_TRIAGE, STAGE_RFC, STAGE_ARCHITECTURE, STAGE_CI, STAGE_E2E, STAGE_REVIEW}
    invalid = skip_stages - skippable
    if invalid:
        raise ValueError(f"--skip 不支持阶段：{sorted(invalid)}")

    owners = dict(config.stages.owners)
    for stage in skip_stages:
        owners[stage] = OWNER_SKIP
    # 覆盖后重守「不许零闸」（未审直接盲合进 main）。
    review = owners.get(STAGE_REVIEW, OWNER_AGENT)
    merge = owners.get(STAGE_MERGE, OWNER_AGENT)
    rfc = owners.get(STAGE_RFC, OWNER_AGENT)
    architecture = owners.get(STAGE_ARCHITECTURE, OWNER_AGENT)
    if rfc != OWNER_SKIP and architecture == OWNER_SKIP:
        raise ValueError("architecture 仅可在 rfc 同时 skip 时跳过")
    if review == OWNER_SKIP and merge == OWNER_AGENT:
        raise ValueError("不许零闸：merge 恒自动执行，review 必须由 agent 把关")

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
    """把逗号分隔的阶段名解析成集合（空/None → 空集）。"""
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


# --------------------------------------------------------------------------------------------------
# 命令 handler。
# --------------------------------------------------------------------------------------------------


def _cmd_init(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0067/T2：就绪校验后顺手 scaffold 默认 .openagents/openagents.yml（幂等，--force 覆盖）——
    # 让首次上手即有一份带注释、可直接改的声明式默认。生成物只是默认，运行时 flag 仍可单次覆盖它。
    from openagents.utils import envcheck
    from openagents.utils.agent_config import scaffold_default_config

    github.ensure_prerequisites()
    print(f"✓ 项目已就绪：{ctx.repo_root}（远端：{ctx.remote}）")

    config_path = ctx.repo_root / ".openagents" / "openagents.yml"
    existed = config_path.exists()
    if scaffold_default_config(path=config_path, force=args.force):
        if existed:
            print("✓ 已用包内模板覆盖配置 .openagents/openagents.yml")
        else:
            print(
                "✓ 已生成默认配置 .openagents/openagents.yml（可编辑；oa vigil --skip 可单次覆盖）"
            )
    else:
        print("· 配置已存在，跳过生成 .openagents/openagents.yml（--force 覆盖）")

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
    from openagents.runtime import legacy

    # Test doubles without RuntimeState's read surface do not model persisted startup state.
    legacy.assert_migrated(state=state, inspect_forge=callable(getattr(state, "list_runs", None)))
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


def _cmd_v02(args: argparse.Namespace, ctx: ProjectContext) -> int:
    """Run one explicit v0.2 batch and print every terminal result."""
    from openagents.runtime.user_test import load_user_test_plan
    from openagents.utils.agent_config import load_agent_config
    from openagents.v02.audit import write_result
    from openagents.v02.model import IssueInput
    from openagents.v02.openagents_adapter import OpenAgentsAdapter
    from openagents.v02.runner import run_batch

    config_path = (
        Path(args.config) if args.config else ctx.repo_root / ".openagents" / "openagents.yml"
    )
    config = load_agent_config(path=config_path)
    github.configure(name=config.forge, settings=config.gitea)
    github.ensure_prerequisites()
    issues = []
    for number in dict.fromkeys(args.issue):
        issue = github.get_issue(number=number)
        issues.append(IssueInput(number=issue.number, title=issue.title, body=issue.body))
    user_test_plan = _user_test_plan_from_args(args=args, loader=load_user_test_plan)
    result = run_batch(
        issues=issues,
        adapter=OpenAgentsAdapter(
            backend=_backend_for(),
            work_dir=ctx.repo_root,
            base=args.base or config.base,
            user_test_plan=user_test_plan,
        ),
        concurrency=args.parallel,
    )
    audit_path = write_result(work_dir=ctx.repo_root, result=result)
    for number in sorted(result.nodes):
        node = result.nodes[number]
        pr = f" PR #{node.pr_number}" if node.pr_number is not None else ""
        detail = f" — {node.reason}" if node.reason else ""
        print(f"{node.status:>21}  issue #{number}{pr}{detail}")
    print(f"审计记录：{audit_path}")
    return 0 if result.nodes and all(node.status == "PASS" for node in result.nodes.values()) else 1


def _user_test_plan_from_args(*, args: argparse.Namespace, loader):
    """Resolve v0.2 user-test flags without mutating the process environment."""
    command = getattr(args, "user_test_command", None)
    transcript = getattr(args, "user_test_transcript", None)
    timeout = getattr(args, "user_test_timeout", None)
    if command is None and transcript is None and timeout is None:
        return loader()
    values = dict(os.environ)
    if command is not None:
        values["OPENAGENTS_USER_TEST_COMMAND"] = command
    if transcript is not None:
        values["OPENAGENTS_USER_TEST_TRANSCRIPT"] = transcript
    if timeout is not None:
        values["OPENAGENTS_USER_TEST_TIMEOUT"] = str(timeout)
    return loader(values)


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
    # Spec-0016/T5：--issue 路由到 issue 版签名出口 post_signed_comment_on_issue（防自循环闭环同构）；
    # --pr 维持既有 post_signed_comment（零回归）。二者由 argparse 互斥必选组保证恰有其一。
    from openagents.utils import identity

    agent_id = _agent_id_for(ctx=ctx)
    if args.issue is not None:
        identity.post_signed_comment_on_issue(number=args.issue, body=args.body, agent_id=agent_id)
        print(f"✓ 已以本 agent 身份回复 issue #{args.issue} 的评论")
        return 0
    identity.post_signed_comment(pr_number=args.pr, body=args.body, agent_id=agent_id)
    print(f"✓ 已以本 agent 身份回复 PR #{args.pr} 的评论")
    return 0


def _cmd_merge_pr(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0074/T1：merger agent 的平台无关落合并出口——转发 forge.merge_pr（已合并幂等视为成功）。
    # 完成判据是输出含 "MERGED"（merger 提示词的 $verify_command 契约）；未合并成功以非零退出。
    if not github.is_merged(pr_number=args.pr):
        github.merge_pr(pr_number=args.pr, method=args.method)
    if github.is_merged(pr_number=args.pr):
        print(f"✓ PR #{args.pr} state: MERGED")
        return 0
    print(f"✗ PR #{args.pr} 未能合并（合并后复读仍非 MERGED）", file=sys.stderr)
    return 1


def _cmd_release(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0023/T4：确定性发版动作、无 agent——预检通过则物化 release/vX.Y.Z 分支 + tag。
    from openagents.utils.release import release

    result = release(state=_new_runtime_state_for(ctx=ctx), bump=args.bump)
    if result.released:
        print(f"✓ 已发布 {result.version}（release/{result.version} 分支 + tag）")
        return 0
    print(f"✗ release 预检未通过：{result.reason}", file=sys.stderr)
    return 1


def _cmd_report(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0066/T3：读 timing.jsonl → timing 聚合器 → stdout 文本报告。薄路由：解析路径 + 取 interval，
    # 聚合/重建全在 runtime.timing（单 issue 时间线 + 跨 issue p50/p90 + 最长尾）。空/缺文件友好提示、退出码 0。
    from openagents.runtime import timing, token_usage, tool_usage

    path = ctx.repo_root / ".openagents" / timing.TIMING_FILENAME
    events = timing.load_events(path=path)
    usage_path = ctx.repo_root / ".openagents" / tool_usage.TOOL_USAGE_FILENAME
    usage_events = tool_usage.load_events(path=usage_path)
    token_path = ctx.repo_root / ".openagents" / token_usage.TOKEN_USAGE_FILENAME
    token_events = token_usage.load_events(path=token_path)
    interval = _report_interval(ctx=ctx, args=args)
    print(
        _render_report(
            events=events,
            interval=interval,
            path=path,
            usage_events=usage_events,
            usage_path=usage_path,
            token_events=token_events,
            token_path=token_path,
        )
    )
    return 0


def _report_interval(*, ctx: ProjectContext, args: argparse.Namespace) -> int:
    # Spec-0066/T3：轮询 interval 作墙钟精度下限标注——从 openagents.yml 读，读不到回落内建默认 60s。
    from openagents.utils.agent_config import AgentConfigError, load_agent_config

    config_path = (
        Path(args.config) if args.config else ctx.repo_root / ".openagents" / "openagents.yml"
    )
    try:
        return load_agent_config(path=config_path).interval
    except (AgentConfigError, FileNotFoundError, OSError):
        return 60  # 缺配置不该让报告失败——回落内建默认轮询间隔


def _render_report(
    *,
    events: list,
    interval: int,
    path: Path,
    usage_events: list | None = None,
    usage_path: Path | None = None,
    token_events: list | None = None,
    token_path: Path | None = None,
) -> str:
    # Spec-0066/T3：把聚合结果排成 stdout 文本表。**显式标注墙钟精度下限 = 轮询 interval**（issue 验收项）。
    from openagents.runtime import timing, token_usage, tool_usage

    usage_events = usage_events or []
    token_events = token_events or []
    if not events and not usage_events and not token_events:
        return (
            f"（timing.jsonl 为空或不存在：{path}）\n"
            "跑一轮 `oa vigil` 后各阶段信号会落到此文件，再来看报告。"
        )

    out: list[str] = []
    if events:
        lines = timing.timelines(events=events)
        stats = timing.phase_stats(events=events, interval=interval)
        out.append("═══ openagents 阶段墙钟时延报告 ═══")
        out.append(
            f"⚠ 墙钟精度下限 = 轮询 interval（本次 {interval}s）：各段时延有 ±{interval}s 粒度误差，勿当精确值。"
        )
        out.append("")
        out.append("── 单 subject 时间线（各阶段墙钟停留）──")
        for line in lines:
            head = f"{line.subject}"
            if line.pr is not None:
                head += f"（PR #{line.pr}）"
            out.append(f"• {head}  总计 {_fmt_duration(seconds=line.total)}")
            for segment in line.segments:
                out.append(f"    {segment.phase:<20} {_fmt_duration(seconds=segment.seconds)}")
        out.append("")
        out.append("── 跨 subject 每阶段分布（p50 / p90 + 最长尾）──")
        out.append(f"    {'phase':<20} {'p50':>10} {'p90':>10}   最长尾")
        for stat in stats.phases:
            out.append(
                f"    {stat.phase:<20} {_fmt_duration(seconds=stat.p50):>10} "
                f"{_fmt_duration(seconds=stat.p90):>10}   "
                f"{stat.max_subject}（{_fmt_duration(seconds=stat.max_seconds)}）"
            )
    if usage_events:
        if out:
            out.append("")
        out.append("═══ agent 工具与取证预算报告 ═══")
        out.append(f"数据：{usage_path or tool_usage.TOOL_USAGE_FILENAME}（只含工具名，不含参数）")
        out.append(
            f"    {'role':<18} {'调用':>6} {'编辑前取证均值':>14} {'最大':>8} "
            f"{'超预算':>8} {'缺原因':>8}"
        )
        for row in tool_usage.aggregate(events=usage_events):
            out.append(
                f"    {row['role']:<18} {row['invocations']:>6} "
                f"{row['average_lookup_before_edit']:>14.1f} "
                f"{row['max_lookup_before_edit']:>8} {row['budget_exceeded']:>8} "
                f"{row['exceeded_without_reason']:>8}"
            )
    if token_events:
        if out:
            out.append("")
        out.append("═══ agent token 用量与采集覆盖率 ═══")
        out.append(f"数据：{token_path or token_usage.TOKEN_USAGE_FILENAME}")
        out.append(
            f"    {'role':<16} {'calls':>6} {'reported':>9} {'missing':>8} "
            f"{'input':>10} {'cache-r':>10} {'cache-w':>10} {'reason':>9} "
            f"{'output':>10} {'total':>11} {'total(r/d)':>11}"
        )
        for row in token_usage.aggregate(events=token_events):
            total_kinds = f"{row['reported_total_count']}/{row['derived_total_count']}"
            out.append(
                f"    {row['role']:<16} {row['invocations']:>6} {row['reported']:>9} "
                f"{row['unavailable']:>8} {row['input_tokens']:>10} "
                f"{row['cache_read_input_tokens']:>10} "
                f"{row['cache_creation_input_tokens']:>10} {row['reasoning_tokens']:>9} "
                f"{row['output_tokens']:>10} {row['total_tokens']:>11} {total_kinds:>11}"
            )
        out.append(
            "注：missing 不计入 token 合计；total(r/d) = provider 显式总数/分量派生总数的调用数。"
        )
    return "\n".join(out)


def _fmt_duration(*, seconds: float) -> str:
    # Spec-0066/T3：秒 → 人读时长（0s / 45s / 3m0s / 1h2m）。纯展示，不改聚合值。
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{secs}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h{mins}m"


def _cmd_board(args: argparse.Namespace) -> int:
    # RFC-0001 T6：board 不要求 git/remote（跳过 preflight），读新栈 RuntimeState 渲染看板。
    from openagents.utils.results import board

    ctx = resolve_project()
    if ctx is None:
        ctx = ProjectContext(repo_root=Path.cwd(), remote=None)
    path = board(state=_new_runtime_state_for(ctx=ctx))
    print(f"✓ 成果看板：{path}")
    return 0


def _cmd_desktop(args: argparse.Namespace) -> int:
    # Spec-0073/T2：起本地 daemon（HTTP+SSE）。只读 work_queue + streams ring buffer，不操作仓库/远端，
    # 故跳过 preflight（同 board）。db 在 <repo>/.openagents/vigil-queue.db（vigil --parallel 落盘处）。
    from openagents.desktop import daemon

    ctx = resolve_project()
    repo_root = ctx.repo_root if ctx is not None else Path.cwd()
    db_path = repo_root / ".openagents" / "vigil-queue.db"
    board_fn = daemon.default_board_fn(db_path=db_path, enrich=None)
    daemon.run(host=args.host, port=args.port, board_fn=board_fn)
    return 0


def _dispatch(args: argparse.Namespace) -> int:
    # board 不操作仓库，跳过 preflight（决策 10）。
    if args.command == "board":
        return _cmd_board(args)
    # Spec-0073/T2：desktop 只读本地 work_queue/流，不操作仓库/远端，同样跳过 preflight。
    if args.command == "desktop":
        return _cmd_desktop(args)
    # Spec-0066/T3：report 只读本地 timing.jsonl，不操作仓库/远端，同样跳过 preflight（无 remote 也能出报告）。
    if args.command == "report":
        ctx = resolve_project()
        if ctx is None:
            ctx = ProjectContext(repo_root=Path.cwd(), remote=None)
        return _cmd_report(args, ctx)

    ctx = ensure_project(interactive=True)
    handlers = {
        "init": _cmd_init,
        "vigil": _cmd_vigil,
        "v02": _cmd_v02,
        "backfill-rfc": _cmd_backfill_rfc,
        "issue": _cmd_issue,
        "reply-comment": _cmd_reply_comment,
        "merge-pr": _cmd_merge_pr,
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
    # Spec-0069/T1：必须在 parse_args 之前调（argcomplete 文档规定的唯一正确位置）。它仅在 shell 补全
    # 握手（环境变量 _ARGCOMPLETE 存在）时读 parser 生成候选并 exit；正常运行下立即返回、零副作用，故下方
    # 分发/退出码/错误处理链全部不变。
    if argcomplete is not None:
        argcomplete.autocomplete(parser)
    # Spec-0070/T1：自更新预检——每次命令前保证跑在最新 uv tool 快照上（快照与 git 源码解耦，源码 pull 后
    # 快照不自动更新）。落后且可安全更新则 pull --ff-only + uv tool install --force + execvp 重执行本命令；
    # 否则打印可操作提示并 fail-open 继续（离线/脏工作区/feature 分支绝不阻断、绝不动 WIP）。仅接 openagents
    # 入口（spec 独立命令不接）；传 sys.argv（重执行要完整进程 argv，非 main(argv) 的可选测试入参）。放在
    # argcomplete 之后：补全握手时 argcomplete 已 exit，走不到这里；正常运行才做预检。
    from openagents.utils import selfupdate

    selfupdate.precheck(argv=sys.argv)
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(sys.stderr)
        return 2
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
