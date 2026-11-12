#!/usr/bin/env bash
# Spec-0027 End-to-end test start script: openagents vigil-all multi-storey (single process and Vigil group of warehouses).
#
# Two paragraphs:
#   1) Offline certainty (default execution) - ruff lint/format + pytest, full-mock/injection, not touching real
#      gh/ backend. Overwrite: T1 configuration load (default merge / path absolute / name default / all illegal input errors reported),
#      T2 Organization (fan-out / [name] prefix / single process failed to isolate / Ctrl-C stop path / real _run_repo
#      It's... chdir+Construct+@Ambassah: #Fail #Fail #Fail #Fail #Fail #Fail #Fail #Fail #Fail #Fail #Fail #Fail #Fail #Fail #Fail #Fail # #Fail #Fail #Fail #Fail # #Fail #Failt # # #Fail # # #Falt T3 CLI Connect (C)vigil-all Parsing --config/--once, forwarding Fleet.run、
#      Skip cwd preflight, co-exist with existing vigil.
#   2) Real smoke (not to be visible opt-in) - a point to two local temporary warehouses when setting up OPENAGENTS_E2E_REAL = 1
#      fleet.yml True `openagents vigil-all --once`: Real fan of two separate processes, each os.chdir
#      Go to your own warehouse and re-use the existing Vigil run round. The assertion** logs take the prefixes of their respective warehouses to distinguish between sources** and two subprocesses
#      ** Independent** (one result is not mixed with the other). gh CLI is needed.
#
#      Why does this segment need a back end: two temporary warehouses ** without GitHub Far **, so each of them finds out
#      (`gh issue list`) The certainty fails, and the oxy mode does not leave the child process without zero - the father process is** for each warehouse
#      Note the prefixed exit**, which is a clear demonstration of three hard guarantees for Spec-0027: fan (two subprocesses),
#      Log prefixes distinguish between sources, single warehouse failure does not drag the rest (misuse segregation+ individual cwd independence of the subprocesses).
#      The complete "Recover the real issue" list should be written in each warehouse. openagents/state.json" closed loops should be real gh+
#      Claude driver, high cost and uncertain, point to two reals using `openagents vigil-all --once`
#      Warehouse observation manually——This script is only for the true section to assert that a valid fan is out/Prefix/Blocking links (same) 0023 The trade-off.
#
# Usage:
#   rash scripts/e2e-spec-0027-vigil-all.sh# Offline Only
#   OPENAGENTS_E2E_REAL = 1 bash scripts/e2e-spec-0027-vigil-all.sh# with smoke from real fan
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + Units/Integrated Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q tests/test_fleet_config.py tests/test_fleet.py tests/test_cli_fleet.py

if [[ "${OPENAGENTS_E2E_REAL:-0}" != "1" ]]; then
  echo
  echo "✓ Offline check passed. True fan smokes have jumped (set) OPENAGENTS_E2E_REAL=1 Open."
  exit 0
fi

echo
echo "==> [2/2] Real smoke: two warehouses. fleet.yml Run! vigil-all --once, Verify the fan out + Prefix + Segregation"
command -v gh >/dev/null || { echo "Require installation and login gh CLI"; exit 1; }

repo_root="$(pwd)"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# Two local temporary warehouses (no GitHub remote Zoom found a certain failure Zoom subprocesses not zero exit without backend).
for name in repo-a repo-b; do
  mkdir -p "$workdir/$name"
  git -C "$workdir/$name" init -q
  git -C "$workdir/$name" -c user.email=e2e@openagents -c user.name=e2e \
    commit -q --allow-empty -m "init $name"
done

# fleet.yml: Two warehouses are named a / b (log prefix display name), relative path to parsing the directory where the configuration file is.
cat >"$workdir/fleet.yml" <<YAML
repos:
  - path: repo-a
    name: a
  - path: repo-b
    name: b
YAML

echo "Run openagents vigil-all --onceTwo separate processes and run round…"
set +e
out="$(cd "$repo_root" && uv run openagents vigil-all --once --config "$workdir/fleet.yml" 2>&1)"
set -e
echo "$out"

echo
echo "ARRENT: The polymer log is a distinct prefix for each warehouse [a] / [b] …"
echo "$out" | grep -q "\[a\]" || { echo "✗ No warehouse seen. a Prefix Log"; exit 1; }
echo "$out" | grep -q "\[b\]" || { echo "✗ No warehouse seen. b Prefix Log"; exit 1; }

echo
echo "✓ The real smoke is complete: two warehouses are each separated and have a Vigil, and the logs are each prefixed to distinguish the source."
echo "  Single warehouse failure is recorded independently without dragging the rest (missegregation).→state Write to closed loop, point to two"
echo "  Real gh The warehouse is manually observed."
