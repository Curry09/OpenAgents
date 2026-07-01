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

    return parser


# RFC-0001 T1: 业务对象工厂，延迟 import 各子任务模块；测试可对这些工厂打桩，
# 保持 cli 测试 hermetic（不触达真实 gh / claude / 浏览器）。
def _state_for(*, repo_root: Path):
    from openagents.state import State

    return State(path=repo_root / ".openagents" / "state.json")


# RFC-0011 决策 7：在接线处解析一次本实例身份，注入下游（Orchestrator / Messages / reply-comment）。
# resolve_agent_id 幂等（env > state > 首次生成落盘），多处调用得同一 id，保证 solve / poll / vigil
# 跨进程一致。单列为工厂，便于测试打桩、不触达真实 state。
def _agent_id_for(*, ctx: ProjectContext) -> str:
    from openagents import identity

    return identity.resolve_agent_id(state=_state_for(repo_root=ctx.repo_root))


# Spec-0020/T4：单列 backend 工厂——issue 前门对齐（align）与 Orchestrator 共用同一个
# ClaudeCodeBackend 抽象，延迟 import 保持 cli 顶层轻、测试可对工厂打桩（不触达真实 LLM）。
def _backend_for():
    from openagents.backends.claude_code import ClaudeCodeBackend

    return ClaudeCodeBackend()


def _orchestrator_for(*, ctx: ProjectContext):
    from openagents.orchestrator import Orchestrator

    return Orchestrator(
        backend=_backend_for(),
        state=_state_for(repo_root=ctx.repo_root),
        work_dir=ctx.repo_root,
        agent_id=_agent_id_for(ctx=ctx),
    )


def _messages_for(*, ctx: ProjectContext):
    from openagents.messages import Messages
    from openagents.orchestrator import DEFAULT_BASE

    return Messages(
        orchestrator=_orchestrator_for(ctx=ctx),
        state=_state_for(repo_root=ctx.repo_root),
        agent_id=_agent_id_for(ctx=ctx),
        # 注入 work_dir + base，使 _process_coding 的 BEHIND 拉式同步能调 update_branch / 解冲突。
        work_dir=str(ctx.repo_root),
        base=DEFAULT_BASE,
        # 注入 backend（复用既有工厂），使 merge 闸冲突时派 coding agent 语义解冲突（含 OVERVIEW.md
        # 经 spec render 重渲）；缺 backend 则解冲突恒不启用，回落 needs-human。
        backend=_backend_for(),
    )


# Spec-0027/T3：fleet 编排器工厂——注入起真子进程的 spawn / 真跨进程 queue。延迟 import
# 保持 cli 顶层轻、测试可对本工厂打桩（返回假 Fleet，不真起子进程、不触达真实 gh/后端）。
def _fleet_for():
    from openagents.fleet import Fleet, default_queue, default_spawn

    return Fleet(spawn=default_spawn, queue_factory=default_queue)


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
    # RFC-0015 / Spec-0023/T1：统一冷启动兜底——确保全部流程标签就位（幂等：已存在即 no-op），
    # 预建 openagents / rfc-approved / needs-human，消除后续 add_label 报 not found。test 分支
    # 门控退役后日常 base 改回恒存在的 main，已无需任何分支自举。
    github.ensure_prerequisites()
    print(f"✓ 项目已就绪：{ctx.repo_root}（远端：{ctx.remote}）")
    # Spec-0030/T3：项目就绪后追加一段非阻塞前端 e2e 环境体检（检测 browser MCP + 权限模式），
    # 缺失只打印告知与设置方式、不改退出码（恒 return 0）。仅此一处接线，编排核心不感知体检。
    from openagents import envcheck

    print()
    print(envcheck.check().text)
    return 0


def _cmd_rfc(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0005：起草 RFC 并开 draft PR（状态 rfc-review），等人评审。
    pr = _orchestrator_for(ctx=ctx).start_rfc(issue_number=args.issue, base=args.base)
    print(f"✓ 已为 issue #{args.issue} 起草 RFC 并开 draft PR：{pr.url}")
    return 0


def _cmd_backfill_rfc(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0025/T3：薄路由——把代码路径转发到 backfill_rfc，业务逻辑全在 orchestrator/backfill。
    pr = _orchestrator_for(ctx=ctx).backfill_rfc(path=args.path, base=args.base)
    print(f"✓ 已为 `{args.path}` 反向补全 spec 并开 draft PR：{pr.url}")
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
    from openagents import align

    alignment = align.restate(draft=align.Draft(title=title, body=body), backend=_backend_for())
    print("提 issue 前先对齐一下范围：")
    print(alignment.render())
    answer = input("看起来对吗？确认创建请输入 y / yes：")
    return align.is_confirmed(answer=answer)


def _cmd_reply_comment(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # coding agent 回评论的唯一出口：post_signed_comment 盖本实例签名（agent_id 幂等解析，与
    # poll/vigil 一致）→ 回复带签名 → 不被下一轮 poll 的 new_human_comments 当成新人类评论（防自循环）。
    from openagents import identity

    identity.post_signed_comment(pr_number=args.pr, body=args.body, agent_id=_agent_id_for(ctx=ctx))
    print(f"✓ 已以本 agent 身份回复 PR #{args.pr} 的评论")
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
    from openagents.hold import parse_hold

    labels = args.label if args.label else [DISCOVERY_LABEL]
    # Spec-0020/T4：把 --hold 原始串解析成 Hold（None → 默认全不停），传给 vigil.run；
    # 非法值由 parse_hold 抛 ValueError，经 _run 的异常通道转干净一行提示（不 traceback）。
    hold = parse_hold(raw=args.hold)
    # RFC-0015 / Spec-0023/T1：进主循环前自举一次结构性 prerequisite（流程标签），使无人值守
    # 的守夜进程自恢复——全新仓库直接 vigil（不先 init）也能跑通发现段。test 分支门控退役后
    # 日常 base 改回恒存在的 main，无需分支自举。只在进循环前一次，不进每轮（自恢复定位）。
    github.ensure_prerequisites()
    _vigil_for(ctx=ctx).run(
        interval=args.interval, labels=labels, base=args.base, once=args.once, hold=hold
    )
    return 0


def _cmd_vigil_all(args: argparse.Namespace) -> int:
    # Spec-0027/T3：薄路由——读 fleet 配置（解析+校验+默认合并，T1）→ Fleet.run 并发守夜（T2）。
    # 不取 cwd 项目 ctx：vigil-all 统管的是配置里列出的「别的仓库」，本身可在任意目录运行
    # （配置路径相对 cwd 解析），故不像其它命令那样走 ensure_project preflight（见 _dispatch）。
    from openagents.fleet_config import load_fleet_config

    plans = load_fleet_config(path=Path(args.config))
    _fleet_for().run(plans=plans, once=args.once)
    return 0


def _cmd_release(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0023/T4：人唯一的宏观决策点——预检（无 BLOCKED/needs-human + main CI 绿）通过则
    # 把 main 当前 HEAD 物化为 release/vX.Y.Z 分支 + tag。失败按预检原因设非零退出码，不发布。
    from openagents.release import release

    result = release(state=_state_for(repo_root=ctx.repo_root), bump=args.bump)
    if result.released:
        print(f"✓ 已发布 {result.version}（release/{result.version} 分支 + tag）")
        return 0
    print(f"✗ release 预检未通过：{result.reason}", file=sys.stderr)
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

    # Spec-0027/T3：vigil-all 统管的是配置里列出的别的仓库，cwd 不必是 git 仓库——同 board
    # 跳过 cwd 项目 preflight，直接读配置并扇出（preflight 由各子进程在自己的仓库里做）。
    if args.command == "vigil-all":
        return _cmd_vigil_all(args)

    ctx = ensure_project(interactive=True)
    handlers = {
        "init": _cmd_init,
        "rfc": _cmd_rfc,
        "backfill-rfc": _cmd_backfill_rfc,
        "refine-rfc": _cmd_refine_rfc,
        "implement": _cmd_implement,
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
    from openagents.fleet_config import FleetConfigError
    from openagents.github import GithubError
    from openagents.orchestrator import OrchestratorError
    from openagents.workspace import WorkspaceError

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
        OrchestratorError,
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
