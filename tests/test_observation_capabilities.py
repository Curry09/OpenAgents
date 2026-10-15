"""Spec-0092/T3: capabilities are available without project, network or update side effects."""

import json
import os
import subprocess
import sys

import pytest

from openagents import cli
from openagents.observations import capabilities, evidence
from openagents.utils import selfupdate


def forbidden(*args, **kwargs):
    raise AssertionError("side effect in capability query")


def test_capability_is_bound_to_reader_and_has_no_side_effects(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(selfupdate, "precheck", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(cli, "resolve_project", forbidden)
    assert cli.main(["observation-capabilities", "--json"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value == capabilities.describe()
    assert value["marker"] == evidence.MARKER
    assert value["max_transfer_bytes"] == evidence.MAX_TRANSFER
    assert value["max_expanded_bytes"] == evidence.MAX_EXPANDED
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(sys, "argv", ["openagents", "observation-capabilities", "--json"])
    assert cli.main() == 0


@pytest.mark.parametrize("args", [[], ["--unknown"], ["--json", "extra"]])
def test_capability_bad_arguments_never_self_update(monkeypatch, args):
    monkeypatch.setattr(selfupdate, "precheck", forbidden)
    with pytest.raises(SystemExit) as caught:
        cli.main(["observation-capabilities", *args])
    assert caught.value.code == 2


def test_installed_entrypoint_without_credentials(tmp_path):
    executable = os.path.join(os.path.dirname(sys.executable), "openagents")
    result = subprocess.run(
        [executable, "observation-capabilities", "--json"],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert json.loads(result.stdout) == capabilities.describe()
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_declares_versioned_execution_facts_and_required_dispatch():
    # Spec-0093/T1: the companion contract probe exercises these final contexts.
    assert capabilities.describe()["execution_evidence"] == {
        "schema_versions": [1],
        "required_dispatch": True,
        "context_projection": "all-delivery-roles-v1",
    }
