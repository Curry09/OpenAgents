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

from openagents.utils import github


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
