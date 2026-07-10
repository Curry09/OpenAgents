"""RFC-0011 T2: identity 模块（身份解析 + 评论签名）的单元测试。

外部副作用全部 mock/注入：
- env：monkeypatch os.environ（OPENAGENTS_AGENT_ID）。
- state：用真实 RuntimeState（tmp_path）或伪 state 控制 get/set_agent_id。
- github.post_comment：monkeypatch，断言盖章后的正文下发。

覆盖：sign/parse 往返；无签名/真人正文解析为 None；resolve_agent_id 的
env > RuntimeState > 自动生成三级优先级与落盘稳定性；post_signed_comment 盖章并下发。

# Spec-0063/T2: identity 改接 runtime.RuntimeState，测试随之从旧 State 迁到 RuntimeState。
"""

import pytest

from openagents.runtime.state import RuntimeState
from openagents.utils import identity as identity_module
from openagents.utils.identity import (
    AGENT_ID_ENV,
    parse_agent_id,
    post_signed_comment,
    resolve_agent_id,
    sign,
)


class _FakeState:
    """伪 RuntimeState：内存维护 agent_id，记录 set 调用次数。"""

    def __init__(self, *, agent_id=None):
        self._agent_id = agent_id
        self.set_calls = []

    def get_agent_id(self):
        return self._agent_id

    def set_agent_id(self, *, agent_id):
        self.set_calls.append(agent_id)
        self._agent_id = agent_id


# --------------------------------------------------------------------------- #
# sign / parse_agent_id 往返
# --------------------------------------------------------------------------- #


def test_sign_then_parse_roundtrips():
    signed = sign(body="正文内容", agent_id="alice")
    assert parse_agent_id(body=signed) == "alice"


def test_sign_appends_marker_at_end_and_keeps_body():
    signed = sign(body="hello", agent_id="bot-1")
    assert signed.startswith("hello")
    assert "<!-- openagents:agent=bot-1 -->" in signed
    # 签名追加在末尾，原正文完整保留。
    assert signed.index("hello") < signed.index("openagents:agent")


def test_parse_agent_id_none_for_unsigned_body():
    assert parse_agent_id(body="一条真人评论，没有签名") is None


def test_parse_agent_id_none_for_empty_body():
    assert parse_agent_id(body="") is None


def test_parse_agent_id_ignores_lookalike_text():
    # 字符集受限（[A-Za-z0-9_-]），正文里的非注释文本不会被误当签名。
    assert parse_agent_id(body="openagents:agent=alice 只是普通文字") is None


def test_sign_roundtrip_with_hex_id():
    signed = sign(body="x", agent_id="a1b2c3d4")
    assert parse_agent_id(body=signed) == "a1b2c3d4"


# --------------------------------------------------------------------------- #
# resolve_agent_id 三级优先级
# --------------------------------------------------------------------------- #


def test_resolve_prefers_env(monkeypatch):
    # env 最优先：即便 state 已有值，也用 env 的。
    monkeypatch.setenv(AGENT_ID_ENV, "from-env")
    state = _FakeState(agent_id="from-state")

    assert resolve_agent_id(state=state) == "from-env"
    # env 命中时不写 state（不污染落盘值）。
    assert state.set_calls == []


def test_resolve_falls_back_to_state(monkeypatch):
    monkeypatch.delenv(AGENT_ID_ENV, raising=False)
    state = _FakeState(agent_id="from-state")

    assert resolve_agent_id(state=state) == "from-state"
    # state 已有值时不重复落盘。
    assert state.set_calls == []


def test_resolve_generates_and_persists_when_missing(monkeypatch):
    monkeypatch.delenv(AGENT_ID_ENV, raising=False)
    state = _FakeState(agent_id=None)

    agent_id = resolve_agent_id(state=state)

    # 自动生成非空、字符集受限。
    assert agent_id
    assert all(c.isalnum() or c in "_-" for c in agent_id)
    # 立即落盘，使后续进程拿到同一 id。
    assert state.set_calls == [agent_id]


def test_resolve_generated_id_is_stable_across_calls(monkeypatch, tmp_path):
    # 用真实 RuntimeState：首次生成落盘，第二次（新 RuntimeState 实例，模拟新进程）复用同值。
    monkeypatch.delenv(AGENT_ID_ENV, raising=False)
    path = tmp_path / ".openagents" / "runtime-state.json"

    first = resolve_agent_id(state=RuntimeState(path=path))
    second = resolve_agent_id(state=RuntimeState(path=path))

    assert first == second


def test_resolve_env_blank_falls_through(monkeypatch):
    # env 设为空白串视同未设，回落到 state / 生成。
    monkeypatch.setenv(AGENT_ID_ENV, "   ")
    state = _FakeState(agent_id="from-state")

    assert resolve_agent_id(state=state) == "from-state"


# --------------------------------------------------------------------------- #
# post_signed_comment
# --------------------------------------------------------------------------- #


def test_post_signed_comment_signs_then_posts(monkeypatch):
    # Spec-0064/T5：post_signed_comment 现会「同步后回读校验漏签」——正常路径回读到自己带签名的评论、
    # 不补签。故除 post_comment 外还需打桩 list_comments 返回刚发的签名评论，使本用例 hermetic。
    from openagents.utils.github import Comment

    posted = {}

    def _post(*, pr_number, body):
        posted.update(pr_number=pr_number, body=body)

    monkeypatch.setattr(identity_module.github, "post_comment", _post)
    monkeypatch.setattr(
        identity_module.github,
        "list_comments",
        lambda *, pr_number: [
            Comment(
                id="1",
                author="alice",
                body="🤖 已更新 RFC\n\n<!-- openagents:agent=alice -->",
                created_at="2026-01-01T00:00:00Z",
            )
        ],
    )

    post_signed_comment(pr_number=5, body="🤖 已更新 RFC", agent_id="alice")

    assert posted["pr_number"] == 5
    # 回读到带本实例签名的评论 → 不补签，posted 仍是原始签名回复。
    assert posted["body"].startswith("🤖 已更新 RFC")
    # 下发的正文带签名，且可解析回 agent_id。
    assert parse_agent_id(body=posted["body"]) == "alice"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
