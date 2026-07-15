// Spec-0073/T3: App 基座 —— 持有 /board 轮询数据 + 选中 subject + 待看列表，经 context 下发；
// 用 React.lazy **动态挂载** Board/Detail/Nav 三个扩展点（动态 import → 基座不静态依赖 feature 模块，
// 避免循环依赖，T4/T5/T6 可各自独立开发、互不 import）。
import { createContext, lazy, Suspense, useContext, useEffect, useMemo, useState } from 'react'
import { DaemonClient, DEFAULT_DAEMON_URL } from './daemon-client'
import { orderPending } from './nav/pending'
import type { BoardEntry } from './types'

// 扩展点：动态 import，故本文件对 board/detail/nav 只有**运行时**依赖、无静态 import 环。
const Board = lazy(() => import('./board/Board'))
const DetailOverlay = lazy(() => import('./detail/DetailOverlay'))

export interface DesktopContextValue {
  client: DaemonClient
  board: BoardEntry[]
  pending: BoardEntry[] // 已按四级优先级 + 同级 enqueued 排序的待看列表
  selected: string | null // 当前进大窗的 subject（null = 停在看板）
  open: (subject: string | null) => void
}

// 导出 context 供 feature 单测直接包一层 Provider 注入 mock（免起整个 App/daemon 轮询）。
export const DesktopContext = createContext<DesktopContextValue | null>(null)

// feature 模块（Board/Detail/Nav）统一经此消费基座数据，不各自 new client / 各自轮询。
export function useDesktop(): DesktopContextValue {
  const ctx = useContext(DesktopContext)
  if (ctx === null) {
    throw new Error('useDesktop 必须在 <App> 的 DesktopContext 内使用')
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

  // /board 轮询：~2s 一拉，失败静默保留上一帧（daemon 未起时不刷屏报错）。
  useEffect(() => {
    let alive = true
    const poll = async (): Promise<void> => {
      try {
        const next = await daemon.fetchBoard()
        if (alive) {
          setBoard(next)
        }
      } catch {
        // 忽略单次轮询失败：下一拍重试。
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
        <Suspense fallback={<div className="loading">加载看板…</div>}>
          <Board />
        </Suspense>
        {selected !== null && (
          <Suspense fallback={<div className="loading">加载会话…</div>}>
            <DetailOverlay />
          </Suspense>
        )}
      </div>
    </DesktopContext.Provider>
  )
}
