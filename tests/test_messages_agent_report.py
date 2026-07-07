"""Spec-0051/T5: messages 回执收口——_post_agent_report + _report_already_posted + 防刷屏去重。

聚焦收口层本身（不跑整链，整链在 test_agent_report_integration.py）：
- _report_header / _normalize_report 纯函数（标题锚点 + 规范化去签名尾巴）；
- _post_agent_report 唯一 IO 出口：盖签名贴出、重复同内容去重、去重查询抖动 fail-open 照发、
  post_comment 抛错只 _progress 不阻断（尽力而为）；
- _report_already_posted：同标题同内容判重复、同标题不同内容照发、不同标题不抑制。

内存假 GitHub 评论账本：post_signed_comment 桩把「盖真签名后的正文 + 递增 created_at」记进 ledger，
list_comments 回读——使去重读得到刚贴的回执（真实回环）。
"""

import pytest

from openagents import identity
from openagents import messages as messages_module
from openagents.github import Comment
from openagents.messages import Messages, _normalize_report, _report_header

_AGENT_ID = "agent-self"


class _CommentLedger:
    """内存假 GitHub 评论账本：记 body（盖真签名）+ 递增 created_at，list_comments 回读。"""

    def __init__(self):
        self.comments: list[Comment] = []
        self._seq = 0

    def post_signed_comment(self, *, pr_number, body, agent_id):
        self._seq += 1
        signed = identity.sign(body=body, agent_id=agent_id)
        self.comments.append(
            Comment(
                id=f"c{self._seq}",
                author="openagents",
                body=signed,
                created_at=f"2026-01-01T00:00:{self._seq:02d}Z",
            )
        )

    def list_comments(self, *, pr_number):
        return list(self.comments)


def _msgs():
    # 回执收口的两个方法只用 self._agent_id + github/identity 模块函数，orchestrator/state 用不到。
    return Messages(orchestrator=object(), state=object(), agent_id=_AGENT_ID)


def _patch_ledger(monkeypatch):
    ledger = _CommentLedger()
    monkeypatch.setattr(messages_module.identity, "post_signed_comment", ledger.post_signed_comment)
    monkeypatch.setattr(messages_module.github, "list_comments", ledger.list_comments)
    return ledger


# --------------------------------------------------------------------------- #
# 纯函数：标题锚点 + 规范化
# --------------------------------------------------------------------------- #


def test_report_header_picks_first_h2():
    assert _report_header(body="## 实现自述\n\n干了 X") == "## 实现自述"
    # 首行是空行也能取到 `## ` 标题（robust）。
    assert _report_header(body="\n\n## 证据执行\n- 结论：✅") == "## 证据执行"
    # 无 `## ` 标题 → None（非回执评论）。
    assert _report_header(body="人类随手回的一句评论") is None


def test_normalize_report_strips_signature_and_blanks():
    signed = identity.sign(body="## 实现自述\n\n干了 X", agent_id="a1")
    # 规范化后去掉空行 + 签名尾巴，只留内容行。
    assert _normalize_report(body=signed) == "## 实现自述\n干了 X"
    # 同内容不同签名 → 规范化后相等（去重看内容不看谁贴的）。
    other = identity.sign(body="## 实现自述\n\n干了 X", agent_id="a2")
    assert _normalize_report(body=signed) == _normalize_report(body=other)


# --------------------------------------------------------------------------- #
# _post_agent_report：贴出 / 去重 / 尽力而为
# --------------------------------------------------------------------------- #


def test_post_agent_report_signs_and_posts(monkeypatch):
    ledger = _patch_ledger(monkeypatch)
    msgs = _msgs()
    msgs._post_agent_report(pr_number=5, body="## 实现自述\n\n干了 X")
    assert len(ledger.comments) == 1
    # 盖了本实例签名。
    assert identity.parse_agent_id(body=ledger.comments[0].body) == _AGENT_ID


def test_post_agent_report_dedups_same_content(monkeypatch):
    ledger = _patch_ledger(monkeypatch)
    msgs = _msgs()
    msgs._post_agent_report(pr_number=5, body="## 证据执行\n- 结论：✅ 通过")
    msgs._post_agent_report(pr_number=5, body="## 证据执行\n- 结论：✅ 通过")
    # 同内容重复 poll → 命中去重、不新增。
    assert len(ledger.comments) == 1


def test_post_agent_report_same_header_different_content_reposts(monkeypatch):
    ledger = _patch_ledger(monkeypatch)
    msgs = _msgs()
    msgs._post_agent_report(pr_number=5, body="## 迭代自述（CI 反馈）\n\n第一轮改了 A")
    msgs._post_agent_report(pr_number=5, body="## 迭代自述（CI 反馈）\n\n第二轮改了 B")
    # 同标题但正文不同（理由各异的连续迭代）→ 照发。
    assert len(ledger.comments) == 2


def test_post_agent_report_different_headers_not_suppressed(monkeypatch):
    ledger = _patch_ledger(monkeypatch)
    msgs = _msgs()
    msgs._post_agent_report(pr_number=5, body="## 迭代自述（CI 反馈）\n\nx")
    msgs._post_agent_report(pr_number=5, body="## 迭代自述（代码评审反馈）\n\nx")
    # 不同标题天然分桶、互不抑制。
    assert len(ledger.comments) == 2


def test_post_agent_report_swallows_post_error(monkeypatch):
    # post_comment 抛错 → 只 _progress、不上抛（尽力而为，不阻断编排）。
    monkeypatch.setattr(messages_module.github, "list_comments", lambda *, pr_number: [])

    def _boom(*, pr_number, body, agent_id):
        raise RuntimeError("gh 挂了")

    monkeypatch.setattr(messages_module.identity, "post_signed_comment", _boom)
    msgs = _msgs()
    # 不抛出即通过。
    msgs._post_agent_report(pr_number=5, body="## 实现自述\n\nx")


def test_post_agent_report_dedup_query_error_fails_open(monkeypatch):
    # 去重查询（list_comments）抖动 → fail-open 照发（宁可多发一条也不漏发回执）。
    posted = []
    monkeypatch.setattr(
        messages_module.github,
        "list_comments",
        lambda *, pr_number: (_ for _ in ()).throw(RuntimeError("查询抖动")),
    )
    monkeypatch.setattr(
        messages_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: posted.append(body),
    )
    msgs = _msgs()
    msgs._post_agent_report(pr_number=5, body="## 实现自述\n\nx")
    assert len(posted) == 1


# --------------------------------------------------------------------------- #
# _report_already_posted
# --------------------------------------------------------------------------- #


def test_report_already_posted_true_only_for_same_content(monkeypatch):
    ledger = _patch_ledger(monkeypatch)
    msgs = _msgs()
    body = "## 证据闸判决\n- 裁决：✅ PASS"
    ledger.post_signed_comment(pr_number=5, body=body, agent_id=_AGENT_ID)
    assert msgs._report_already_posted(pr_number=5, body=body) is True
    # 同标题不同内容 → 不判重复。
    assert msgs._report_already_posted(pr_number=5, body="## 证据闸判决\n- 裁决：❌ FAIL") is False
    # 不同标题 → 找不到同类，不判重复。
    assert msgs._report_already_posted(pr_number=5, body="## 实现自述\n\nx") is False


def test_report_already_posted_no_header_fails_open(monkeypatch):
    _patch_ledger(monkeypatch)
    msgs = _msgs()
    # 无 `## ` 标题（不应发生）→ fail-open 判未贴过（照发）。
    assert msgs._report_already_posted(pr_number=5, body="没有标题的正文") is False


def test_executor_does_not_import_identity():
    """理念 10：executor 保持不 import identity/github（渲染归域、发送归 messages）。

    只查 import 语句行（正文/docstring 里提到 identity 是解释解耦意图，不算耦合）。
    Spec-0055：evidence_gate 已随独立证据闸退役删除，此处只余 executor。
    """
    import openagents.executor as ex

    for mod in (ex,):
        with open(mod.__file__, encoding="utf-8") as fh:
            import_lines = [line for line in fh if line.startswith(("import ", "from "))]
        for line in import_lines:
            assert "identity" not in line, f"{mod.__name__} 不应 import identity：{line!r}"
            assert "github" not in line, f"{mod.__name__} 不应 import github：{line!r}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
