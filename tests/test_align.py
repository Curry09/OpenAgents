"""Spec-0020/T1: 前门对齐模块 align 的单元测试。

打桩 backend（不触达真实 LLM），覆盖：restate 调注入 backend 把草稿复述成 X/Y/Z 三段、
backend 被以关键字参数注入且只调用一次、返回值被正确拆段、render 含三段标识；确认判定
是与复述生成解耦的纯谓词（肯定放行、否定/空不放行、不调 backend）。
"""

from pathlib import Path

from openagents.backends.base import AgentResult
from openagents.utils import align
from openagents.utils.align import Alignment, Draft, is_confirmed, restate


class _StubBackend:
    """记录调用与入参的伪 backend，按预设文本回三段复述（不触达真实 LLM）。"""

    name = "stub"

    def __init__(self, *, summary):
        self.calls = []
        self._summary = summary

    def run(self, *, work_dir, task, context):
        self.calls.append({"work_dir": work_dir, "task": task, "context": context})
        return AgentResult(changed=False, summary=self._summary)


_RESTATED = "要做：加一个登录页\n边界：仅邮箱密码登录\n不做：第三方 OAuth"


def test_restate_splits_into_three_sections():
    backend = _StubBackend(summary=_RESTATED)

    alignment = restate(draft=Draft(title="登录", body="想要登录功能"), backend=backend)

    assert isinstance(alignment, Alignment)
    assert alignment.want == "加一个登录页"
    assert alignment.boundary == "仅邮箱密码登录"
    assert alignment.non_goals == "第三方 OAuth"


def test_restate_calls_backend_once_with_keyword_args():
    backend = _StubBackend(summary=_RESTATED)

    restate(draft=Draft(title="T", body="B"), backend=backend)

    # backend 被以关键字参数注入、恰调用一次；草稿的 title/body 进了 context。
    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert isinstance(call["work_dir"], Path)
    assert "T" in call["context"] and "B" in call["context"]


def test_render_contains_three_section_markers():
    rendered = Alignment(want="X", boundary="Y", non_goals="Z").render()

    assert "要做：" in rendered
    assert "边界：" in rendered
    assert "不做：" in rendered
    assert "X" in rendered and "Y" in rendered and "Z" in rendered


def test_parse_tolerates_missing_section():
    # 缺段回落空串（容错），不抛错。
    backend = _StubBackend(summary="要做：只给一段")

    alignment = restate(draft=Draft(title="T", body="B"), backend=backend)

    assert alignment.want == "只给一段"
    assert alignment.boundary == ""
    assert alignment.non_goals == ""


def test_is_confirmed_affirmative_passes():
    assert is_confirmed(answer="y") is True
    assert is_confirmed(answer="yes") is True
    assert is_confirmed(answer="  Y  ") is True
    assert is_confirmed(answer="YES") is True


def test_is_confirmed_negative_or_empty_does_not_pass():
    assert is_confirmed(answer="n") is False
    assert is_confirmed(answer="no") is False
    assert is_confirmed(answer="") is False
    assert is_confirmed(answer="   ") is False


def test_is_confirmed_does_not_touch_backend():
    # 确认判定是纯谓词——与复述生成解耦，不依赖任何 backend / I/O。
    assert align.is_confirmed.__module__ == "openagents.utils.align"
    assert is_confirmed(answer="random") is False
