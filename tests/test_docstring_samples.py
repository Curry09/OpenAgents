# Spec-0059/T3: Three standard drop-out assertion tests - engine module docstring + run_vigil function docstring compliance.

"""Assert the two sample files carry PEP-257-aligned docstrings after Spec-0059/T3.

Sample proof T1 The rules are set on the real file:`runtime.engine` Modules docstring Get rid of it. `\"\"\"#` Write,spec-id Move Up
To Top of File `#` Notes, supplements `Exports:`；`recipes.vigil.run_vigil` Function docstring Fill `Args:` with `Raises:`。

Exports:
    No object (pytest with example module) is exported.
"""

from __future__ import annotations

from pathlib import Path

from openagents.recipes import vigil
from openagents.runtime import engine


def test_engine_module_docstring_is_clean():
    doc = engine.__doc__
    assert doc is not None
    # The first character, which is not `#`:spec-id, has been moved up to the top of the file `#` comment, without contamination of __doc__/help().
    assert doc.lstrip()[0] != "#", "engine module doingcstring should not start with #"
    # Lists the exported objects (PEP 257 "list the cards, options and operations exported").
    assert "Exports:" in doc


def test_engine_spec_id_moved_to_top_comment():
    src = Path(engine.__file__).read_text(encoding="utf-8")
    # Spec-id `#` Comment Line (Cluster to argparse `# Author:` usage) at the top of the file.
    assert "# Spec-0060/T2" in src.splitlines()[0]
    # The module Docstring no longer has a `"""#` sequence (`#` is a text in three quotation marks that will enter __doc__).
    assert '"""#' not in src


def test_run_vigil_docstring_has_args_and_raises():
    doc = vigil.run_vigil.__doc__
    assert doc is not None
    assert "Args:" in doc
    assert "Raises:" in doc
