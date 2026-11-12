"""# Spec-0065/T2: Test kit ** off-grid hard gate** — Which test is really shell gone out and blew up `gh` on the spot.

Why must this gate be: `gh` stakes are all in their hands (monkeywatch top `openagents.utils.github.*`).
The production code will be read again on a certain path** ** GitHub (this is the case for the `_park_needs_human` Queue: to avoid re-posting)
For the same reason, it reads back to the comment stream, the old test of leaking a stake ** ** — `gh` on the developer is on the log, it’ll be quiet.
The real issue of reading the real store is green, and it’s only blown up until the CI without `GH_TOKEN`. Local green, CI red, and local green.
is** false** (test data on readline).

The gate is on `subprocess.run`, the real boundary: `argv[0] == "gh"` is all thrown, the rest is (git etc.) set in place.
`subprocess.run` tests (e.g. retest of test_github.py for `_run_gh`) setattr after fixture, natural cover of the gate.
"""

import subprocess

import pytest

_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _no_real_gh(monkeypatch):
    """No test can be actually transferred to `gh`: Either a stake `github.*` or this path should not have touched GitHub."""

    def _guard(argv, *args, **kwargs):
        if isinstance(argv, list | tuple) and argv and argv[0] == "gh":
            command = " ".join(str(arg) for arg in argv)
            raise AssertionError(
                f"The test actually switched GitHub:{command}\n"
                "• The production code read/written GitHub on this path, and the test did not put a stick on it."
                "Please use the openagents.utils.github.* function for the MonkeyPatch."
            )
        return _REAL_RUN(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _guard)


@pytest.fixture(autouse=True)
def _isolate_forge_state():
    """# Spec-0074: Separate the modular level of the distribution level forge and eliminate the inter-testing symmetry.

    `openagents.utils.forge` is the PEP 562 `__getattr__` commissioning module (`vigil.github` is it). A large number of vigil testing uses
    `monkeypatch.setattr(vigil_module.github, "get_issue", ...)` stake-- and `vigil_module.github`** is...
    Forge Module**: `monkeypatch` Judgement `forge.get_issue` Exists (commissioned by __getattr__ to gthub resolution successfully), save that
    True function, write it back as real property**. Real property shrouds __getattr__, and then ** next ** test**
    `forge.get_issue` no longer commissioned github driver, but the real function of the leak  →  Shell really went out to `gh`
     →  Blocked off the web (CI red root cause for this PR). Reset `_active`, free of inertity detections, to cross the test cache.

    Before and after each test:`reset()` Clear. `_active` + Delete everything.**It’s leaking in. forge.__dict__ True Properties**（import It’s always the same.
    Legitimate name) guarantees that forge is always pure as a trust. Zero business intrusion - without touching dozens of `setattr(vigil_module.github, ...)`s.
    """
    from openagents.utils import forge

    baseline = set(
        vars(forge)
    )  # The name of the valid module (with configure/reset/_active/ constant...) for the Import
    forge.reset()
    yield
    for name in list(vars(forge)):
        if name not in baseline:
            delattr(
                forge, name
            )  # Test the real attributes leaked in - delete, restore pure __getattr__ commissioning
    forge.reset()


@pytest.fixture(autouse=True)
def _no_self_update(monkeypatch):
    """#Spec-0070/T1: Turning the whole world off to update the pre-screening - no-op, zero-return, net-free, when `cli.main` is being tested for import/ call.

    `openagents.cli.main()` always runs a self-renewed pre-screening in front of `parse_args` (`selfupdate.precheck`:get setch  → )
    Compare pull/uv install/execvp. The test must never really go to the fetch network / reload / execvp, so autouse has a hard switch
    `OPENAGENTS_NO_SELF_UPDATE=1`, short-circuits  as soon as `precheck` comes in. Use the self-select body to cover it.
    """
    from openagents.utils import selfupdate

    monkeypatch.setenv(selfupdate.DISABLE_ENV, "1")
