"""Spec-0050/T1：build_agent_context 单元测试。

打桩 github.list_comments（内存评论账本，不触达 gh/网络），覆盖：
- 三块结构：PR 号 + 对话历史（带作者 + 轮次）+ 本轮反馈；
- 分类去噪：认领便签 / 其它机器噪声过滤，裁决 / 作者 refine / 人类评论保留；
- 隐藏签名剥离；
- 时序升序 + 轮次标注；
- 截断保留最近若干条 + 标注省略；
- 空历史 / 空 extra_detail 各自优雅降级（不产空标题块）；
- list_comments 抛 GithubError → fail-open 降级为空历史。
"""

from openagents import agentcontext, github, identity


def _comment(*, author, body, created_at, agent_id=None):
    """造一条评论；agent_id 非空则盖 OpenAgents 签名（模拟机器评论）。"""
    signed = identity.sign(body=body, agent_id=agent_id) if agent_id else body
    return github.Comment(id="n", author=author, body=signed, created_at=created_at)


def _patch(monkeypatch, comments):
    monkeypatch.setattr(github, "list_comments", lambda *, pr_number: list(comments))


def test_contains_pr_number_and_three_history_classes_with_author_and_round(monkeypatch):
    # 三类历史（裁决 / 作者 refine / 人类评论）+ PR 号 + 本轮反馈都在，带作者与轮次标注。
    comments = [
        _comment(
            author="reviewer-bot",
            body="## 评审闸裁决\n- 裁决：❌ REWORK\n- 反馈摘要：result.md 仍是 skipped",
            created_at="2026-07-01T00:00:00Z",
            agent_id="rev",
        ),
        _comment(
            author="author-bot",
            body="🤖 已根据评审意见更新 spec：已把 result.md 改成 PASS",
            created_at="2026-07-02T00:00:00Z",
            agent_id="auth",
        ),
        _comment(
            author="alice",
            body="人类补充：请以文件真实内容为准",
            created_at="2026-07-03T00:00:00Z",
        ),
    ]
    _patch(monkeypatch, comments)
    ctx = agentcontext.build_agent_context(pr_number=128, extra_detail="本轮反馈X")

    assert "本 PR 是 #128" in ctx
    assert "## 本 PR 对话历史（供背景参考）" in ctx
    # 三类历史正文各自在。
    assert "评审闸裁决" in ctx and "result.md 仍是 skipped" in ctx
    assert "已根据评审意见更新 spec" in ctx
    assert "人类补充：请以文件真实内容为准" in ctx
    # 作者 + 轮次标注。
    assert "第 1 轮 · reviewer-bot" in ctx
    assert "第 2 轮 · author-bot" in ctx
    assert "第 3 轮 · alice" in ctx
    # 本轮反馈块。
    assert "## 本轮具体反馈\n本轮反馈X" in ctx


def test_claim_note_and_signatures_are_filtered(monkeypatch):
    # 认领便签整条过滤；保留评论里的隐藏 agent 签名被剥离，不出现在上下文里。
    comments = [
        github.Comment(
            id="c",
            author="claim-bot",
            body=identity.build_claim_note(agent_id="claimer"),
            created_at="2026-07-01T00:00:00Z",
        ),
        _comment(
            author="alice",
            body="真实人类评论",
            created_at="2026-07-02T00:00:00Z",
        ),
    ]
    _patch(monkeypatch, comments)
    ctx = agentcontext.build_agent_context(pr_number=1, extra_detail="")

    assert "认领本 issue" not in ctx  # 认领便签正文被滤
    assert "openagents:claim" not in ctx  # 认领标记被滤
    assert "openagents:agent=" not in ctx  # 任何 agent 签名被剥
    assert "真实人类评论" in ctx


def test_other_machine_noise_is_filtered(monkeypatch):
    # 带签名但既非裁决也非 refine 的机器评论（如指路牌）作纯噪声过滤。
    comments = [
        _comment(
            author="bot",
            body="🤖 端到端指路牌：见 docs/evidence/...",
            created_at="2026-07-01T00:00:00Z",
            agent_id="botx",
        ),
        _comment(author="alice", body="留下来的人类评论", created_at="2026-07-02T00:00:00Z"),
    ]
    _patch(monkeypatch, comments)
    ctx = agentcontext.build_agent_context(pr_number=1, extra_detail="")

    assert "端到端指路牌" not in ctx
    assert "留下来的人类评论" in ctx


def test_history_sorted_ascending_by_created_at(monkeypatch):
    # 乱序输入 → 按 created_at 升序渲染，轮次随时序递增。
    comments = [
        _comment(author="c", body="第三条", created_at="2026-07-03T00:00:00Z"),
        _comment(author="a", body="第一条", created_at="2026-07-01T00:00:00Z"),
        _comment(author="b", body="第二条", created_at="2026-07-02T00:00:00Z"),
    ]
    _patch(monkeypatch, comments)
    ctx = agentcontext.build_agent_context(pr_number=1, extra_detail="")

    assert ctx.index("第一条") < ctx.index("第二条") < ctx.index("第三条")
    assert "第 1 轮 · a" in ctx and "第 3 轮 · c" in ctx


def test_truncation_keeps_recent_and_annotates_omitted(monkeypatch):
    # 大量长评论 → 超上限 → 保留最近若干条 + 头部标注省略；最新一条必在。
    comments = [
        _comment(
            author=f"u{i}",
            body=f"评论{i}内容" + "填" * 500,
            created_at=f"2026-07-{i:02d}T00:00:00Z",
        )
        for i in range(1, 21)
    ]
    _patch(monkeypatch, comments)
    ctx = agentcontext.build_agent_context(pr_number=1, extra_detail="")

    assert "更早的" in ctx and "条历史已省略" in ctx
    assert "评论20内容" in ctx  # 最新一条保留
    assert "评论1内容" not in ctx  # 最早的被裁掉


def test_empty_history_and_empty_detail_degrade_gracefully(monkeypatch):
    # 无历史 + 空 extra_detail → 只剩 PR 号一行，不产任何空标题块。
    _patch(monkeypatch, [])
    ctx = agentcontext.build_agent_context(pr_number=7, extra_detail="")

    assert ctx == "本 PR 是 #7。"
    assert "对话历史" not in ctx
    assert "本轮具体反馈" not in ctx


def test_empty_detail_only_omits_feedback_block(monkeypatch):
    _patch(monkeypatch, [_comment(author="a", body="有历史", created_at="2026-07-01T00:00:00Z")])
    ctx = agentcontext.build_agent_context(pr_number=7, extra_detail="   ")

    assert "有历史" in ctx
    assert "本轮具体反馈" not in ctx  # 空白 detail 不产反馈块


def test_github_error_falls_open_to_empty_history(monkeypatch):
    # list_comments 抛 GithubError → 不抛出、历史降级为空，仍返回 PR 号 + 本轮反馈。
    def _boom(*, pr_number):
        raise github.GithubError("gh 抖动")

    monkeypatch.setattr(github, "list_comments", _boom)
    ctx = agentcontext.build_agent_context(pr_number=9, extra_detail="仍要送达的反馈")

    assert "本 PR 是 #9" in ctx
    assert "仍要送达的反馈" in ctx
    assert "对话历史" not in ctx
