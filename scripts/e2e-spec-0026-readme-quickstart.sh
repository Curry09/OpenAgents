#!/usr/bin/env bash
# Spec-0026/T2 peer-to-end test startup script: RADEME "Most Usage / Quickstart" section location and content assertion.
#
# Pure document validation - no call to any real CLI / GitHub, no external dependencies, CI can stabilize runback.
# The assertion that:
#   1) README.md contains the title ##Premise/Quickstart;
#   2) The title line number is after "#installation" and before "# fast start" (in line order);
#   3) The new paragraph code block also contains `openagents init` / `openagents issue` / `openagents vigil` rows.
#
# Usage:
#   bash scripts/e2e-spec-0026-readme-quickstart.sh
set -euo pipefail

cd "$(dirname "$0")/.."

README="README.md"
test -f "$README" || { echo "✗ Missing $README"; exit 1; }

# Takes the first line number (none is empty) of a title.
line_of() { grep -nF "$1" "$README" | head -n1 | cut -d: -f1; }

echo "==> [1/2] ”Assume.”## The best use / Quickstart」In ’## Install with## ”As soon as you can.”"
INSTALL_LN="$(line_of '## Install')"
QUICKSTART_LN="$(line_of '## The best use / Quickstart')"
WALKTHROUGH_LN="$(line_of '## Let’s get this thing on fast.')"

test -n "$INSTALL_LN"     || { echo "✗ Missing## Install"; exit 1; }
test -n "$QUICKSTART_LN"  || { echo "✗ Missing## The best use / Quickstart」"; exit 1; }
test -n "$WALKTHROUGH_LN" || { echo "✗ Missing## ”Steve quickly.”"; exit 1; }

if ! { [ "$INSTALL_LN" -lt "$QUICKSTART_LN" ] && [ "$QUICKSTART_LN" -lt "$WALKTHROUGH_LN" ]; }; then
  echo "✗ Order error: Install(L$INSTALL_LN) → Quickstart(L$QUICKSTART_LN) → Let’s get this thing on fast.(L$WALKTHROUGH_LN)"
  exit 1
fi
echo "  ✓ Order correct: Install(L$INSTALL_LN) → Quickstart(L$QUICKSTART_LN) → Let’s get this thing on fast.(L$WALKTHROUGH_LN)"

echo
echo "==> [2/2] The assertion. Quickstart Paragraph block contains init / issue / vigil Three lines."
# Intercept the paragraph between the Quickstart title and the "Quickstart" paragraph, within which only three lines of command are verified.
SECTION="$(sed -n "${QUICKSTART_LN},${WALKTHROUGH_LN}p" "$README")"
for cmd in "openagents init" "openagents issue" "openagents vigil"; do
  grep -qF "$cmd" <<<"$SECTION" || { echo "✗ Quickstart Paragraph missing command:$cmd"; exit 1; }
  echo "  ✓ Quickstart The paragraph reads:$cmd"
done

echo
echo "✓ Spec-0026 End-to-end through:README The best use/Quickstart The sector is in the right position and the shortest path is ready in three rows."
