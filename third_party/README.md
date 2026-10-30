# Vendored dependencies

`nexau/` contains the complete upstream Git tree at commit `5cd791b1382f1163621c9ff0b50c2cf01c4ba923` (NexAU 0.4.1), without Git metadata or local caches. Its Apache-2.0 LICENSE and original notices are retained; the repository MIT license does not replace them.

All original tracked files are unchanged. `UPSTREAM.json` records their SHA256 values and the upstream Git tree. The only additions are that provenance document and `nexau/_vendor_info.py`, which exposes source identity and verifies the snapshot; it does not change the agent runtime.

`uv sync --locked` resolves NexAU from this directory. It does not clone the retired upstream URL or substitute a registry package. Run the dependency check without installing SDK dependencies:

```bash
python3 scripts/check_vendored_nexau.py
```

Build a portable SDK wheel from the same source:

```bash
uv build third_party/nexau --wheel --out-dir dist/sdk
```

For an OpenAgents wheel installation with its optional NexAU backend, install the local NexAU wheel together with the OpenAgents wheel and the `nexau` extra. The optional extra declares the SDK version; a generic pip invocation does not interpret `[tool.uv.sources]`, so supply the SDK wheel explicitly. CI tests this installation outside the checkout.

Keep upstream files out of first-party lint/test discovery. SDK changes require an explicit reviewed provenance/patch update; never label modified code as an unchanged upstream snapshot. Keep Auto-Designer and OpenAgents copies at the same recorded upstream revision. Existing frozen experiment snapshots are not rewritten.
