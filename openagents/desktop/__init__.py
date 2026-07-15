"""# Spec-0073/T2: 本地 daemon 接口（HTTP+SSE），供 Electron 桌面 app 读 work_queue/GitHub/流。

只听 `127.0.0.1`，两个端点：`GET /board`（work_queue 快照 + 每 subject 待看类别）与
`GET /stream/<subject>`（SSE 逐条推该 subject 的 ring buffer 行）。见 `daemon` 模块。
"""

from __future__ import annotations
