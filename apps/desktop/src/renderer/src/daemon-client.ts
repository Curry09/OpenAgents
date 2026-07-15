// Spec-0073/T3: daemon 的 HTTP + SSE client。renderer 侧唯一的网络出口。
// /board 走 fetch 轮询；/stream/<subject> 走 EventSource（浏览器原生 SSE），返回一个 close 句柄。
import type { BoardEntry } from './types'

export class DaemonClient {
  constructor(private readonly baseUrl: string) {}

  // 拉一次 /board 快照。调用方（useBoard）按 interval 轮询它。
  async fetchBoard(): Promise<BoardEntry[]> {
    const resp = await fetch(`${this.baseUrl}/board`)
    if (!resp.ok) {
      throw new Error(`GET /board 失败：HTTP ${resp.status}`)
    }
    return (await resp.json()) as BoardEntry[]
  }

  // 订阅某 subject 的 SSE 流。onLine 逐行回调（先补发已有、再增量续推）。
  // 返回一个幂等 close：切换 subject / 卸载时调用它断流，避免泄漏订阅。
  openStream(
    subject: string,
    onLine: (line: string) => void,
    onError?: (err: Event) => void
  ): () => void {
    const url = `${this.baseUrl}/stream/${encodeURIComponent(subject)}`
    const source = new EventSource(url)
    source.onmessage = (evt) => onLine(evt.data)
    if (onError) {
      source.onerror = onError
    }
    return () => source.close()
  }
}

// 默认 daemon 地址：与 CLI `openagents desktop` 的默认端口一致（Spec-0073/T2）。
export const DEFAULT_DAEMON_URL = 'http://127.0.0.1:8765'
