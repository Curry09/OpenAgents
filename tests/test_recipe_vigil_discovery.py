"""Spec-0035/T4: 发现段慢检查进度日志——`_intake` 拉带标签 issue 前 + `_admit` 调 triager LLM 前各一行 stderr。

发现段目前只在**结果**出来时才打日志，网络（拉 issue）/ LLM（triage 分诊）过程全哑。任一道检查被半开
socket / 慢模型挂住时，最后一行日志停在上一步的**结果**行，看不出正卡在哪一步。这里只钉两件事：

1. `_intake` 在 `github.list_issues` **之前**打「▶ 发现段：拉取带标签 issue…」；
2. `_admit`（agent 态）在 `stages.triage` **之前**打「… issue #N 自检分诊方向(LLM)…」。

进度行只落 stderr，**不改任何返回值 / 副作用 / 控制流**——本文件同时钉住「既有行为逐字节不变」。
姊妹文件 `test_recipe_vigil_admit.py` 钉准入对话主干，与本文件不相交（只补进度日志这一条）。全程打桩
github/stages，不触真实网络 / LLM。
"""

from __future__ import annotations

from datetime import UTC, datetime

from openagents.recipes import vigil as vigil_module
from openagents.recipes.vigil import _admit, _intake
from openagents.utils import agent_config, github

_NOW = datetime(2026, 7, 15, 10, 0, 0, tzinfo=UTC)


def _stages(**owners) -> agent_config.StagePolicy:
    return agent_config.StagePolicy(owners=owners)


def _config(**overrides) -> agent_config.AgentConfig:
    defaults = {
        "version": 1,
        "agents": agent_config.AgentPolicy(backends={}),
        "stages": _stages(triage="agent"),
        "release": agent_config.ReleasePolicy(),
        "interval": 1,
        "base": "main",
        "labels": ["openagents"],
        "repos": [],
    }
    return agent_config.AgentConfig(**(defaults | overrides))


def _issue(*, number: int) -> github.Issue:
    return github.Issue(number=number, title="标题", body="正文", labels=())


def _keep_discovered(monkeypatch) -> None:
    """# Spec-0074/T1: 准入测试的最新现态仍带 discovery label。"""
    monkeypatch.setattr(
        vigil_module.github,
        "get_issue",
        lambda *, number: github.Issue(
            number=number, title="标题", body="正文", labels=("openagents",)
        ),
    )


# --------------------------------------------------------------------------------------------------
# T4-A：`_intake` 在拉带标签 issue **之前**打一行进度——卡在拉 issue 时输出停在这行。
# --------------------------------------------------------------------------------------------------


def test_intake_logs_progress_before_listing_issues(monkeypatch, tmp_path, capsys):
    order: list[str] = []
    monkeypatch.setattr(vigil_module.github, "ensure_label", lambda *, name, description: None)

    def _list_issues(*, labels):
        order.append("list_issues")
        return []

    monkeypatch.setattr(vigil_module.github, "list_issues", _list_issues)

    def _spy_log(*, message):
        if "拉取带标签 issue" in message:
            order.append("log")

    monkeypatch.setattr(vigil_module, "_log", _spy_log)

    _intake(backend=object(), work_dir=tmp_path, config=_config(), agent_id="vigil-1", now=_NOW)

    assert order == ["log", "list_issues"], "进度行必须在拉 issue 之前打，否则卡住时看不出停在这步"


def test_intake_progress_line_lands_on_stderr(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(vigil_module.github, "ensure_label", lambda *, name, description: None)
    monkeypatch.setattr(vigil_module.github, "list_issues", lambda *, labels: [])

    _intake(backend=object(), work_dir=tmp_path, config=_config(), agent_id="vigil-1", now=_NOW)

    captured = capsys.readouterr()
    assert "▶ 发现段：拉取带标签 issue…" in captured.err
    assert "拉取带标签 issue" not in captured.out, "进度日志只落 stderr，不污染 stdout"


def test_intake_behaviour_unchanged_admits_and_orders_edges(monkeypatch, tmp_path):
    # 逐字节不变：进度行不改控制流——issue 照常过 triager 准入、打 ready、admitted>0 才排边。
    monkeypatch.setattr(vigil_module.github, "ensure_label", lambda *, name, description: None)
    monkeypatch.setattr(vigil_module.github, "list_issues", lambda *, labels: [_issue(number=5)])
    _keep_discovered(monkeypatch)
    labels: list[tuple[int, str]] = []
    monkeypatch.setattr(
        vigil_module.github,
        "issue_add_label",
        lambda *, number, name: labels.append((number, name)),
    )
    monkeypatch.setattr(
        vigil_module.stages,
        "triage",
        lambda *, backend, work_dir, issue: {"actionable": True, "reason": ""},
    )
    ordered: list[object] = []
    monkeypatch.setattr(
        vigil_module,
        "_order_edges",
        lambda *, backend, work_dir, config, agent_id: ordered.append(True),
    )

    _intake(backend=object(), work_dir=tmp_path, config=_config(), agent_id="vigil-1", now=_NOW)

    assert (5, vigil_module._LABEL_READY) in labels
    assert ordered == [True], "admitted>0 → 照常调 curator 排依赖边（控制流未被进度行改动）"


# --------------------------------------------------------------------------------------------------
# T4-B：`_admit`（agent 态）在调 triager LLM **之前**打一行进度——卡在 LLM 分诊时输出停在这行。
# --------------------------------------------------------------------------------------------------


def test_admit_logs_progress_before_triage_llm(monkeypatch, tmp_path):
    order: list[str] = []
    _keep_discovered(monkeypatch)
    monkeypatch.setattr(vigil_module.github, "issue_add_label", lambda *, number, name: None)

    def _triage(*, backend, work_dir, issue):
        order.append("triage")
        return {"actionable": True, "reason": ""}

    monkeypatch.setattr(vigil_module.stages, "triage", _triage)

    def _spy_log(*, message):
        if "自检分诊方向(LLM)" in message:
            order.append("log")

    monkeypatch.setattr(vigil_module, "_log", _spy_log)

    admitted = _admit(
        owner="agent",
        backend=object(),
        work_dir=tmp_path,
        config=_config(),
        issue=_issue(number=9),
        agent_id="vigil-1",
        discovery_labels=("openagents",),
    )

    assert admitted == 1, "既有返回值不变：actionable → 准入（返回 1）"
    assert order == ["log", "triage"], "进度行必须在调 LLM 之前打，否则卡在分诊时看不出停在这步"


def test_admit_progress_line_carries_issue_number_on_stderr(monkeypatch, tmp_path, capsys):
    _keep_discovered(monkeypatch)
    monkeypatch.setattr(vigil_module.github, "issue_add_label", lambda *, number, name: None)
    monkeypatch.setattr(
        vigil_module.stages,
        "triage",
        lambda *, backend, work_dir, issue: {"actionable": True, "reason": ""},
    )

    _admit(
        owner="agent",
        backend=object(),
        work_dir=tmp_path,
        config=_config(),
        issue=_issue(number=42),
        agent_id="vigil-1",
        discovery_labels=("openagents",),
    )

    err = capsys.readouterr().err
    assert "… issue #42 自检分诊方向(LLM)…" in err, (
        "进度行须带 issue 号，卡住时一眼定位是哪个 issue"
    )


def test_admit_skip_route_does_not_log_triage_progress(monkeypatch, tmp_path, capsys):
    # 回归：skip 态直接放行、不调 triager，故不该打「调 LLM」的进度行（进度只属于真会慢的 agent 态）。
    _keep_discovered(monkeypatch)
    monkeypatch.setattr(vigil_module.github, "issue_add_label", lambda *, number, name: None)

    admitted = _admit(
        owner="skip",
        backend=object(),
        work_dir=tmp_path,
        config=_config(),
        issue=_issue(number=7),
        agent_id="vigil-1",
        discovery_labels=("openagents",),
    )

    assert admitted == 1
    assert "自检分诊方向(LLM)" not in capsys.readouterr().err, "skip 不叫 LLM → 不该打分诊进度行"


def test_intake_does_not_grant_ready_after_discovery_label_is_removed(monkeypatch, tmp_path):
    """# Spec-0074/T1: list 后到 grant 前摘标，旧快照不得继续派单，也不得触发 curator。"""
    discovered = github.Issue(number=5, title="标题", body="正文", labels=("openagents",))
    removed = github.Issue(number=5, title="标题", body="正文", labels=("bug",))
    monkeypatch.setattr(vigil_module.github, "ensure_label", lambda *, name, description: None)
    monkeypatch.setattr(vigil_module.github, "list_issues", lambda *, labels: [discovered])
    monkeypatch.setattr(vigil_module.github, "get_issue", lambda *, number: removed)
    granted: list[tuple[int, str]] = []
    monkeypatch.setattr(
        vigil_module.github,
        "issue_add_label",
        lambda *, number, name: granted.append((number, name)),
    )
    ordered: list[bool] = []
    monkeypatch.setattr(
        vigil_module, "_order_edges", lambda *, backend, work_dir, agent_id: ordered.append(True)
    )

    _intake(
        backend=object(),
        work_dir=tmp_path,
        config=_config(stages=_stages(triage="skip")),
        agent_id="vigil-1",
        now=_NOW,
    )

    assert granted == [], "discovery label 已摘除却仍打 ready = 用旧快照绕过 owner"
    assert ordered == [], "零准入不应触发 curator"
