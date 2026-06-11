"""RFC-0012 T4: promote 模块 —— test 体验服快进到 main（人唯一的宏观决策点）。

把人的触点收敛到「提 issue」与「promote」两点（RFC-0012 决策 7）：issue→PR 的全过程
在 test 上自动闭环（reviewer 闸 + CI），test 成为不断累加的体验服；人用 test 满意后跑
`openagents promote`，预检通过则把 test 快进到 main。main 不参与日常流转，只被 promote
快进——「累加体验」与「人决定上线」由此解耦（决策 2/7）。

预检（决策 7，全过才扬升）：
  ① 无 STATUS_BLOCKED 的 run —— 没有「评审反复不过、挂起等人」的工作被悄悄跳过；
  ② 无带 needs-human 标签的 open PR —— 同①，从 GitHub 真源再确认一次；
  ③ github.branch_ci_green(source) —— test 分支 HEAD CI 全绿（即便 green-by-construction
     通常已绿，仍显式兜底人手推 test / flaky 的情况，决策 7）。
通过 → ensure_branch(test) 兜底建分支（决策 8）→ `git push origin test:main` 快进 main。

解耦设计（CLAUDE.md 理念 10）：以模块函数方式调 github.* 与注入的 state，git push 走
subprocess——便于单测打桩三者保持 hermetic（不触达真实 gh/git）。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from openagents import github
from openagents.state import BLOCKED_LABEL, STATUS_BLOCKED, State


@dataclass(frozen=True)
class PromoteResult:
    """RFC-0012 决策 7：一次 promote 的结果。

    promoted: 是否完成快进（预检全过且 push 成功）。
    reason: 失败时指明被哪个预检拦下（或 push 失败原因）；成功为 "ok"。
    """

    promoted: bool
    reason: str


def promote(*, state: State, source: str = "test", target: str = "main") -> PromoteResult:
    """RFC-0012 T4：预检通过则把 source（test）快进到 target（main）。

    预检任一不过即返回 promoted=False 且 reason 指明原因，不动 main（决策 7）。
    """
    blocked = [r for r in state.all_runs() if r.status == STATUS_BLOCKED]
    if blocked:
        issues = ", ".join(f"#{r.issue_number}" for r in blocked)
        return PromoteResult(promoted=False, reason=f"存在挂起（{STATUS_BLOCKED}）的 run：{issues}")

    needs_human = [
        pr.number
        for pr in github.list_open_prs()
        if github.has_label(pr_number=pr.number, name=BLOCKED_LABEL)
    ]
    if needs_human:
        prs = ", ".join(f"#{n}" for n in needs_human)
        return PromoteResult(
            promoted=False, reason=f"存在待人介入（{BLOCKED_LABEL}）的 open PR：{prs}"
        )

    if not github.branch_ci_green(branch=source):
        return PromoteResult(promoted=False, reason=f"{source} 分支 CI 未全绿")

    # RFC-0015：快进前统一兜底——一次性确保 test 分支 + 全部流程标签就位（取代原先只
    # 兜底 source 分支的裸 ensure_branch，RFC-0012 决策 8）。默认 source=test/target=main
    # 时与原 ensure_branch(test←main) 等价，并顺带补齐流程标签的预建。
    github.ensure_prerequisites()
    _push_fast_forward(source=source, target=target)
    return PromoteResult(promoted=True, reason="ok")


def _push_fast_forward(*, source: str, target: str) -> None:
    """`git push origin <source>:<target>`：把 source 快进到远端 target（main）。

    不带 --force——非快进（main 有 source 之外的提交）时 git 会拒绝，由调用方看见非零退出。
    失败抛 RuntimeError（CLI 层会转成干净一行提示）。
    """
    result = subprocess.run(
        ["git", "push", "origin", f"{source}:{target}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        reason = (
            result.stderr.strip() or f"git push origin {source}:{target} 返回码 {result.returncode}"
        )
        raise RuntimeError(f"快进 {target} 失败：{reason}")
