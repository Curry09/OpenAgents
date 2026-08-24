"""# Spec-0060/T5: runtime.context —— 组装占位符的值，供 recipe 传给 engine.run_agent。

recipe 零业务判断、engine 不认识流程，那么「每个阶段该给 agent 填哪些占位符 + 注入哪些上下文」
就归本模块承担（读侧调 utils.github 注入 issue 正文 / PR 历史）。每个 `for_<phase>` 方法产出一个
**占位符 dict**：含 engine 的保留字 `work_dir`（worktree 路径）/ `context`（上下文串），以及该阶段
agent PROMPT 所需的模板占位符（issue_number / pr_number / issue_body / feedback / branch …）。

只做「读 + 组装」，不含任何业务判断（判断在 agent），也不碰 git/subprocess（那在 utils/deliver）。
`workspace` 属性暴露 worktree 路径，供 recipe 交付后传给 `gates.assert_head_advanced`。
"""

from __future__ import annotations

from pathlib import Path

# Spec-0074/T1: alias-import 换轨——平台操作经 forge 分发层按配置委托 github/gitea driver，调用点零改动。
from openagents.utils import forge as github


class Context:
    """# Spec-0060/T5: solve_issue 一次 run 的上下文源——按阶段产出占位符 dict。

    构造期锁定 work_dir（worktree 路径）/ issue_number / branch / pr_number；读侧惰性调
    utils.github（issue 正文、PR 历史）。为测试可 hermetic，issue/PR 读经注入的 github 门面
    （默认真实 utils.github，测试可替换）。
    """

    def __init__(
        self,
        *,
        work_dir: Path,
        issue_number: int,
        branch: str,
        pr_number: int | None = None,
    ) -> None:
        self._work_dir = Path(work_dir)
        self._issue_number = issue_number
        self._branch = branch
        self._pr_number = pr_number

    @property
    def workspace(self) -> Path:
        """worktree 路径——交付后 recipe 传给 gates.assert_head_advanced 读客观 head。"""
        return self._work_dir

    def for_plan(self, *, issue_number: int) -> dict:
        """起草阶段占位符：issue 编号 + 正文。"""
        return {
            "work_dir": self._work_dir,
            "context": self._issue_context(issue_number=issue_number),
            "issue_number": issue_number,
            "issue_body": self._issue_body(issue_number=issue_number),
        }

    def for_implement(self, *, issue_number: int) -> dict:
        """首轮实现阶段占位符：issue/PR 编号 + 空反馈（feedback="" 表首轮）。"""
        return {
            "work_dir": self._work_dir,
            "context": self._issue_context(issue_number=issue_number),
            "issue_number": issue_number,
            "pr_number": self._pr_number or 0,
            "feedback": "",
        }

    def for_iterate(self, *, issue_number: int, feedback: str) -> dict:
        """迭代阶段占位符：同 implement 但带 reviewer 的返工反馈。"""
        payload = self.for_implement(issue_number=issue_number)
        payload["feedback"] = feedback
        return payload

    def for_review(self, *, issue_number: int) -> dict:
        """评审阶段占位符：PR 编号 + issue 正文 + PR 历史上下文。"""
        return {
            "work_dir": self._work_dir,
            "context": self._pr_context(issue_number=issue_number),
            "pr_number": self._pr_number or 0,
            "issue_body": self._issue_body(issue_number=issue_number),
        }

    def for_deliver(self, *, issue_number: int) -> dict:
        """交付阶段占位符：分支名 + PR 编号（deliver agent 据此 commit/push/解冲突）。"""
        return {
            "work_dir": self._work_dir,
            "context": "",
            "branch": self._branch,
            "pr_number": self._pr_number or 0,
        }

    def _issue_body(self, *, issue_number: int) -> str:
        """读 issue 正文（经 utils.github）。"""
        return github.get_issue(number=issue_number).body

    def _issue_context(self, *, issue_number: int) -> str:
        """起草/实现阶段的上下文串：issue 标题 + 正文。"""
        issue = github.get_issue(number=issue_number)
        return f"issue #{issue.number}「{issue.title}」\n\n{issue.body}"

    def _pr_context(self, *, issue_number: int) -> str:
        """评审阶段的上下文串：issue 正文 + PR 历史评论（无 PR 号则只给 issue 正文）。"""
        base = self._issue_context(issue_number=issue_number)
        if self._pr_number is None:
            return base
        comments = github.list_comments(pr_number=self._pr_number)
        if not comments:
            return base
        history = "\n".join(f"- @{c.author}: {c.body}" for c in comments)
        return f"{base}\n\nPR #{self._pr_number} 历史评论：\n{history}"


# Spec-0061/T4: 循环型 recipe（vigil 发现段 / poll_comments 守候段）的占位符组装。
#
# 与 `Context`（solve_issue 一次 run 绑死单 issue/PR）不同，vigil 逐 issue 扫、poll_comments 逐
# PR 扫，没有「一次 run 的单一上下文实例」，故这两个阶段的占位符以**模块级函数**组装：入参是
# recipe 已在去重/游标逻辑里拉到手的 issue / comment 对象（不再二次读 github），只做纯组装。


def for_triage(*, work_dir: Path, issue: object) -> dict:
    """分诊阶段占位符：issue 编号 + 正文 + 标题上下文，供 recipes.vigil 派 triager agent。

    入参 `issue` 是 vigil 发现段 `github.list_issues` 已拉到的 Issue（含 number/title/body），
    直接取字段组装，不再二次读 github。`context` 给 agent 一段 issue 标题+正文的可读上下文。
    """
    return {
        "work_dir": Path(work_dir),
        "context": f"issue #{issue.number}「{issue.title}」\n\n{issue.body}",
        "issue_number": issue.number,
        "issue_body": issue.body,
    }


def for_architecture(
    *, work_dir: Path, issue_number: int, design_digest: str, spec_text: str
) -> dict:
    """Build the pre-implementation architecture review context."""
    return {
        "work_dir": Path(work_dir),
        "context": spec_text,
        "issue_number": issue_number,
        "design_digest": design_digest,
        "spec_text": spec_text,
    }


def for_admit(*, work_dir: Path, issue: object, dialogue: str) -> dict:
    """准入裁决占位符：issue 正文 + **准入对话逐字稿**，供 recipes.vigil 派 admitter agent。

    对话是这个阶段唯一的判据（人点没点头，只在人说的那句话里），故它必须是独立占位符——塞进
    `issue_body` 里冒充正文，等于把「人说的话」和「issue 原文」混成一坨，agent 分不清在判哪个。
    """
    return {
        "work_dir": Path(work_dir),
        "context": f"issue #{issue.number}「{issue.title}」的准入对话",
        "issue_number": issue.number,
        "issue_body": issue.body,
        "dialogue": dialogue,
    }


def for_reply(*, work_dir: Path, pr_number: int, branch: str, comment: object) -> dict:
    """回复阶段占位符：PR 编号 + 分支 + 那条人类评论正文，供 recipes.poll_comments 派 replier。

    入参 `comment` 是 poll_comments 守候段 `identity.new_human_comments` 已拉到的那条待回应人类
    评论（含 body），直接取字段组装，不再二次读 github。`context` 即评论正文（回应对象本身）。
    """
    return {
        "work_dir": Path(work_dir),
        "context": comment.body,
        "pr_number": pr_number,
        "branch": branch,
        "comment_body": comment.body,
    }


def for_issue_reply(*, work_dir: Path, issue_number: int, comment: object) -> dict:
    """# Spec-0016/T3：issue 回复阶段占位符：issue 编号 + 那条人类评论正文，供 recipes.vigil 派 replier。

    与 `for_reply`（PR 版）同风格，但 issue 键：**无** `pr_number`、**无** `branch`（issue 尚无工作
    分支，replier.ISSUE_PROMPT 只吃 `$issue_number` / `$comment_body`——只答疑不改代码，见 T3）。入参
    `comment` 是 vigil reconcile 分支②（issue 支）`identity.new_human_comments_on_issue` 已拉到的那条
    待回应人类评论（含 body），直接取字段组装，不再二次读 github。`context` 即评论正文（回应对象本身）。
    """
    return {
        "work_dir": Path(work_dir),
        "context": comment.body,
        "issue_number": issue_number,
        "comment_body": comment.body,
    }
