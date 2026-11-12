// Spec-0073/T3: Share board polling data, selection, and pending entries through context.
// Load Board, Detail, and navigation lazily to avoid circular feature dependencies.

import { createContext, lazy, Suspense, useContext, useEffect, useMemo, useState } from 'react'
import { DaemonClient, DEFAULT_DAEMON_URL } from './daemon-client'
import { orderPending } from './nav/pending'
import type { BoardEntry } from './types'

// Lazy imports keep these feature dependencies out of the static import graph.
const Board = lazy(() => import('./board/Board'))
const DetailOverlay = lazy(() => import('./detail/DetailOverlay'))

export interface DesktopContextValue {
  client: DaemonClient
  board: BoardEntry[]
  pending: BoardEntry[] // Sorted by category priority, then enqueue order.
  selected: string | null // Subject shown in the detail overlay; null shows the board.
  open: (subject: string | null) => void
}

// Export the context so component tests can supply a provider without a daemon.
export const DesktopContext = createContext<DesktopContextValue | null>(null)

// Features share the same board state and do not poll independently.
export function useDesktop(): DesktopContextValue {
  const ctx = useContext(DesktopContext)
  if (ctx === null) {
    throw new Error('useDesktop must be used within the DesktopContext in <App>')
  }
  return ctx
}

const POLL_INTERVAL_MS = 2000

export interface AppProps {
  client?: DaemonClient
}

export default function App({ client }: AppProps): JSX.Element {
  const daemon = useMemo(() => client ?? new DaemonClient(DEFAULT_DAEMON_URL), [client])
  const [board, setBoard] = useState<BoardEntry[]>([])
  const [selected, setSelected] = useState<string | null>(null)

  // Poll the board about every two seconds. Retain the last snapshot on failure.
  useEffect(() => {
    let alive = true
    const poll = async (): Promise<void> => {
      try {
        const next = await daemon.fetchBoard()
        if (alive) {
          setBoard(next)
        }
      } catch {
        // Retry a failed poll on the next interval.
      }
    }
    poll()
    const timer = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [daemon])

  const pending = useMemo(() => orderPending(board), [board])

  const value = useMemo<DesktopContextValue>(
    () => ({ client: daemon, board, pending, selected, open: setSelected }),
    [daemon, board, pending, selected]
  )

  return (
    <DesktopContext.Provider value={value}>
      <div className="app-root">
        <Suspense fallback={<div className="loading">Loading dashboard…</div>}>
          <Board />
        </Suspense>
        {selected !== null && (
          <Suspense fallback={<div className="loading">Loading session…</div>}>
            <DetailOverlay />
          </Suspense>
        )}
      </div>
    </DesktopContext.Provider>
  )
}
