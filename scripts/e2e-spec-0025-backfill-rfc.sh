#!/usr/bin/env bash
# Spec-0025 End-to-end test start script: brookfield reverse completion of RFC (Sweeping stock code  →  inverse paragraph 9 spec draft).
#
# Two paragraphs:
#   1) Offline certainty (default execution) - ruff lint/format + pytest (full-range mock, unattractive gh/git/LLM),
#      Overwrite T1 Account Assistant (single file/director form, public symbol/docstring extraction, empty directory/missing path error),
#      T2 Organization (Class-backend rewrite door control & dragft PR; Validate not 0 open PR), T3 CLI sub-command resolution.
#   2) Inverse Completion Clock Exercise (default, all in temporary directory) - a sample code path for a ** without spec**:
#      a. Run `backfill.inventory` certificate inventory list of output + public symbols (invert input end of ant);
#      b. Simulation of inverted antgent: a draft of 9 (four factually completed, difficult to reverse) paragraphs written in `spec` CLI
#         `spec validate` 0 error - Proof of backfill **Pr front hard door control ** passable.
#      (Really backend counter-refer to LLM, cannot be repeated within CI, so here the definitive exit is reset with spec CLI.
#
# Usage:
#   bash scripts/e2e-spec-0025-backfill-rfc.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + Units/Integrated Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Inverse Full-Screen Exercise: Account sample code → Invert 9 Draft paragraph → spec validate 0 error"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 1) Create a "browfield sample code path without spec" - a single inventory module.
SAMPLE="$TMP/widget.py"
cat >"$SAMPLE" <<'PY'
"""Sample stock module: one with no correspondence spec It’s... brownfield widget。"""


def render():
    return "widget"


class Widget:
    pass
PY

# (a) Run T1 inventory: assert list of output documents + public symbols (invert input end of entry for ant).
uv run python - "$SAMPLE" <<'PY'
import sys
from pathlib import Path
from openagents.backfill import inventory, slug_for

inv = inventory(path=Path(sys.argv[1]))
assert inv.single_file is True, inv
assert [m.path for m in inv.modules] == ["widget.py"], inv
assert inv.modules[0].symbols == ("render", "Widget"), inv.modules[0].symbols
assert "widget.py" in inv.render()
assert slug_for(path=Path(sys.argv[1])) == "widget"
print("  ✓ backfill.inventory A list of documents + Public Symbols OK")
PY

# 2) Simulation of the inverted agent 's definitive export: Write a draft of 9 paragraphs (four paragraphs must be filled and hard to reverse the paragraph label "to be completed " ).
ROOT="$TMP/specs"
mkdir -p "$ROOT"
uv run spec new widget-backfill --issue 0 --title "Reverse Completion widget" \
  --summary "One word. TL;DR: for stock widget Module reverse spec。" --specs-root "$ROOT"
GROUP="$ROOT/0001-widget-backfill.md"
test -f "$GROUP"

# The assertion that scaffolds contain 9 paragraph rust headers.
for h in "## Summary" "## Motivation" "## Guide-level explanation" \
         "## Reference-level explanation" "## Drawbacks" \
         "## Rationale and alternatives" "## Prior art" \
         "## Unresolved questions" "## Future possibilities"; do
  grep -qF "$h" "$GROUP" || { echo "✗ Scaffold missing:$h"; exit 1; }
done

# Four paragraphs will be filled; it is difficult to reverse the paragraph "To be completed by hand" (not necessarily, without triggering validate error).
uv run python - "$GROUP" <<'PY'
import sys
from pathlib import Path
from openagents.spec import model

p = Path(sys.argv[1])
g = model.load_group(path=p)
g = model.Group(
    number=g.number, metadata=g.metadata, tasks=g.tasks, history={},
    overview=model.Overview(
        summary="As stock widget Module reverses a self-contained spec。",
        motivation="widget.py It exists and it doesn’t exist. spec, cannot be included RFC Drives a closed ring (backgrounds are repeated in situ).",
        guide_level="When it already exists, it tells people:render() Outputs widget，Widget Is in the class.",
        reference_level="Actual technical structure: single modules widget.py, Public render / Widget。"
                        "bash scripts/e2e-spec-0025-backfill-rfc.sh Do it. e2e。\nT1 Change widget.py。",
        drawbacks="> To be completed manually (brownfield (Inverted difficulty)",
        rationale_alternatives="Option: Pure static production template rejected——I can’t write it. Motivation Semantics.",
        prior_art="> To be completed manually (brownfield (Inverted difficulty)",
    ),
)
p.write_text(model.render_group(group=g), encoding="utf-8")
print("  ✓ Written 9 Draft paragraph: 4 paragraphs must be filled with factually written and difficult to reverse paragraph ”To be completed manually”")
PY

# Add-task (working breakout: files cross+acceptance must be filled).
uv run spec add-task 0001 --id T1 --title "Inventory widget" --priority P1 \
  --files widget.py --scope "Inventory widget.py" --acceptance "render/Widget I’m counting it." \
  --specs-root "$ROOT"

# b) spec validate 0 error - proves that the inverse draft will pass the hard door control before the PR.
uv run spec validate --specs-root "$ROOT"
echo "  ✓ spec validate 0 error: Inverse drafts can be overridden draft PR The front hard door."

echo
echo "✓ Spec-0025 End-to-end through: inventory inventory code → Invert 9 Draft paragraph → validate Door control closed ring is available."
