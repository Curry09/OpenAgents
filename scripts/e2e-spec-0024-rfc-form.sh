#!/usr/bin/env bash
# Spec-0024 end-to-end test start script: spec turns rust-RFC form (summarize first + single spec self-incorporated, issue #69).
#
# Two paragraphs:
#   1) Offline certainty (default execution) - ruff lint/format + pytest (full-range mock, unattractive gh/git),
#      Overwrite spec data model (group-overview 9 paragraph round-trip, Task thin body), validation quality threshold
#      (Perfect filler non-empty = error, cross spec nudity = warning, files/acceptance cited),
#      Spec new 9 scaffolding, signaturepost from group Overview e2e scripts.
#   2) Process Exercise (Default Execution, All in Temporary Directory) - Run "New Group  →  Write 9 Summary with `spec` CLI
#      "Damd-task  → validate/render/graph Full Green" which proves that a rust-RFC form closed circle is available.
#
# Usage:
#   bash scripts/e2e-spec-0024-rfc-form.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + Units/Integrated Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Process exercise:spec new → Write 9 Paragraph Overview → add-task → validate/render/graph"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ROOT="$TMP/specs"
mkdir -p "$ROOT"

# 1) New group (automatic scaffolding of 9 sections).
uv run spec new demo-feature --issue 999 --title "Presentation feature" \
  --summary "One word. TL;DR: Presentation rust-RFC Form." --specs-root "$ROOT"
GROUP="$ROOT/0001-demo-feature.md"
test -f "$GROUP"

# The assertion that scaffolds contain 9 paragraph rust headers.
for h in "## Summary" "## Motivation" "## Guide-level explanation" \
         "## Reference-level explanation" "## Drawbacks" \
         "## Rationale and alternatives" "## Prior art" \
         "## Unresolved questions" "## Future possibilities"; do
  grep -qF "$h" "$GROUP" || { echo "✗ Scaffold missing:$h"; exit 1; }
done
echo "  ✓ spec new Outputs 9 Scaffold"

# 2) Fill in four sections (summary first: feature contains itself).
uv run python - "$GROUP" <<'PY'
import sys
from pathlib import Path
from openagents.spec import model
p = Path(sys.argv[1])
g = model.load_group(path=p)
g = model.Group(
    number=g.number, metadata=g.metadata, tasks=g.tasks, history={},
    overview=model.Overview(
        summary="For example feature Speak up and be clear.",
        motivation="Current status is not available X  And so it’s   Y(Backgrounds repeat, not cross) spec (b) Reference.",
        guide_level="When it already exists, so tell people: Example……",
        reference_level="Technical programme + DAG。bash scripts/e2e-spec-0024-rfc-form.sh Do it. e2e。\nT1 Change a.py。",
        rationale_alternatives="Alternative A - It’s been rejected because...……",
    ),
)
p.write_text(model.render_group(group=g), encoding="utf-8")
print("  ✓ Filled 9 Summary of the mandatory paragraphs")
PY

# 3) add-task (work breakout: files cross+accuptance must be filled in).
uv run spec add-task 0001 --id T1 --title "implementation a" --priority P1 \
  --files demo/a.py --scope "Change a.py" --acceptance "a The single test is passed." --specs-root "$ROOT"

# 4) Validate / green / green.
uv run spec validate --specs-root "$ROOT"
uv run spec render --specs-root "$ROOT"
test -f "$ROOT/OVERVIEW.md"
echo
echo "✓ Spec-0024 End-to-end through:rust-RFC 9 Paragraph Overview + DAG Job break-up of the closed ring is available."
