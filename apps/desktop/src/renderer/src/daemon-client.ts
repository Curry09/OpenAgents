// Spec-0073/T3: The renderer accesses the daemon through this HTTP and SSE client.
// Fetch board snapshots and use EventSource for subject streams.
import type { BoardEntry } from './types'

export class DaemonClient {
  constructor(private readonly baseUrl: string) {}

  // Fetch one board snapshot for the polling caller.
  async fetchBoard(): Promise<BoardEntry[]> {
    const resp = await fetch(`${this.baseUrl}/board`)
    if (!resp.ok) {
      throw new Error(`GET /board failed: HTTP ${resp.status}`)
    }
    return (await resp.json()) as BoardEntry[]
  }

  // Replay buffered lines first, then emit new lines as they arrive.
  // Close is idempotent; call it on subject changes or unmount.
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

// Use the same default daemon address as openagents desktop (Spec-0073/T2).
export const DEFAULT_DAEMON_URL = 'http://127.0.0.1:8765'
