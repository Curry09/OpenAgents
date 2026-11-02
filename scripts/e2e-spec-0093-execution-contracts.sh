#!/usr/bin/env bash
# Spec-0093/T3: deterministic, no-credentials/no-model contract and dispatch verification.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --locked --extra dev --extra nexau python scripts/check_observation_reader.py \
  --execution-fixture tests/fixtures/execution_evidence_contract.json
uv run --locked --extra dev --extra nexau pytest -q \
  tests/test_observation_execution_contracts.py \
  tests/test_observation_evidence.py tests/test_observation_reader_contract.py \
  tests/test_execution_contract_delivery.py \
  tests/test_backend_nexau.py tests/test_backend_nexau_http.py \
  tests/test_runtime_engine.py tests/test_runtime_context.py \
  tests/test_v02_openagents_adapter.py tests/test_observation_capabilities.py \
  tests/test_agent_config.py tests/test_agents_architect.py
