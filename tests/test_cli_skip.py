"""Spec-0054/T3: vigil --skip CLI 接线 + hold/skip 矛盾校验的单元测试。

覆盖三态：解析并传入 run（--skip spec,ci）；非法值报干净一行（不 traceback）；
--hold spec --skip spec 矛盾报干净一行；不传 --skip 时 run 收到默认 NONE（零回归）。
"""

from openagents.cli import main
from openagents.skip import NONE, Skip


def _patch_ensure(monkeypatch):
    # vigil 入口会调 github.ensure_prerequisites——打成 no-op，隔离真实 gh。
    monkeypatch.setattr("openagents.github.ensure_prerequisites", lambda: None)


def _patch_vigil_capture(monkeypatch):
    seen = {}

    class _FakeVigil:
        def run(self, *, interval, labels, base, once, hold, skip=None):
            seen["hold"] = hold
            seen["skip"] = skip

    monkeypatch.setattr("openagents.cli._vigil_for", lambda *, ctx: _FakeVigil())
    return seen


def test_vigil_skip_parsed_and_passed(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = _patch_vigil_capture(monkeypatch)
    code = main(["vigil", "--once", "--skip", "spec,ci"])
    assert code == 0
    assert seen["skip"] == Skip(at_spec=True, at_ci=True)


def test_vigil_skip_all_parsed(monkeypatch):
    _patch_ensure(monkeypatch)
    seen = _patch_vigil_capture(monkeypatch)
    code = main(["vigil", "--once", "--skip", "all"])
    assert code == 0
    assert seen["skip"] == Skip(
        at_issue=True, at_spec=True, at_code=True, at_ci=True, at_evidence=True
    )


def test_vigil_default_skip_is_none(monkeypatch):
    # 不传 --skip：run 收到默认全不关 NONE（零回归）。
    _patch_ensure(monkeypatch)
    seen = _patch_vigil_capture(monkeypatch)
    code = main(["vigil", "--once"])
    assert code == 0
    assert seen["skip"] == NONE


def test_vigil_invalid_skip_errors_cleanly(monkeypatch, capsys):
    _patch_ensure(monkeypatch)
    # 非法 --skip → parse_skip 抛 ValueError → _run 转干净一行提示 + 非零退出（不 traceback）。
    code = main(["vigil", "--once", "--skip", "spc"])
    assert code == 1
    err = capsys.readouterr().err
    assert "✗" in err
    assert "spc" in err


def test_vigil_hold_skip_conflict_errors_cleanly(monkeypatch, capsys):
    _patch_ensure(monkeypatch)
    # --hold spec --skip spec：同一 spec 闸矛盾 → reconcile_hold_skip 抛 ValueError → 干净一行。
    code = main(["vigil", "--once", "--hold", "spec", "--skip", "spec"])
    assert code == 1
    err = capsys.readouterr().err
    assert "✗" in err
    assert "spec" in err


def test_vigil_hold_and_skip_different_gates_ok(monkeypatch):
    # --hold merge --skip ci：作用于不同闸，不矛盾，照常传入 run。
    _patch_ensure(monkeypatch)
    seen = _patch_vigil_capture(monkeypatch)
    code = main(["vigil", "--once", "--hold", "merge", "--skip", "ci"])
    assert code == 0
    assert seen["skip"] == Skip(at_ci=True)
