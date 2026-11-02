# Third-party sources and licenses

English | [简体中文](THIRD_PARTY.zh-CN.md)

OpenAgents' own code is distributed under the [MIT License](LICENSE). Dependencies and externally supplied materials retain their respective licenses and attribution.

## Dependency sources

| Component | Source and version record | Distribution |
| --- | --- | --- |
| Python dependencies | [`pyproject.toml`](pyproject.toml) and [`uv.lock`](uv.lock) | Installed as separate packages; consult each package's license |
| NexAU optional backend | [hzhua/nexau](https://github.com/hzhua/nexau), commit `28511d9f0362191a6c378fd441b2be55309a9e32` | Apache-2.0; fixed Git dependency, not a vendored source tree |
| Desktop dependencies, including Electron, React, and Vite | [`apps/desktop/package.json`](apps/desktop/package.json) and [`package-lock.json`](apps/desktop/package-lock.json) | Installed through npm; bundled distributions must retain applicable notices |
| Claude Code | Externally installed CLI | Distributed separately under its own terms |

The base package and the `nexau` extra have different dependency sets. Source and wheel metadata declare the same fixed NexAU Git source. Keep its upstream license, copyright, and any applicable notices when distributing it. OpenAgents' MIT license does not grant access to model services or change their terms.

## Reused project code

AHE-Beta reuses the `openagents/spec/` tooling. Copies of that code must preserve OpenAgents' license and source provenance; the receiving project's license does not replace the original notices.

## Target repositories and generated material

Target repository code, task datasets, model output, and user-provided materials are not relicensed merely by being processed by OpenAgents. Review their source licenses and distribution permissions when publishing evidence or release assets. Runtime records may also contain private task content; see [Security](SECURITY.md) before sharing them.
