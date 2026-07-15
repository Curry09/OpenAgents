// Spec-0073/T5: 全屏大窗——上半实时流（StreamView），下半成果锚点（PR/阶段）；「下一个 ▶」快切、Esc 关闭。
import { useEffect } from 'react'
import { useDesktop } from '../App'
import { nextPending } from '../nav/pending'
import StreamView from './StreamView'
import { useStream } from './useStream'

export default function DetailOverlay(): JSX.Element | null {
  const { board, pending, selected, open } = useDesktop()
  const lines = useStream(selected)

  // Esc 关闭大窗回看板。
  useEffect(() => {
    const onKey = (evt: KeyboardEvent): void => {
      if (evt.key === 'Escape') {
        open(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  if (selected === null) {
    return null
  }
  const entry = board.find((e) => e.subject === selected) ?? null

  return (
    <div className="overlay" role="dialog" aria-label={`大窗 ${selected}`}>
      <div className="overlay__bar">
        <strong>{selected}</strong>
        <span>
          <button
            type="button"
            onClick={() => {
              const target = nextPending(pending.length > 0 ? pending : board, selected)
              if (target !== null) {
                open(target)
              }
            }}
          >
            下一个 ▶
          </button>
          <button type="button" onClick={() => open(null)}>
            关闭 ✕
          </button>
        </span>
      </div>
      <StreamView lines={lines} />
      {entry?.pr && (
        <div className="overlay__anchor">
          成果：PR #{entry.pr}
          {entry.pending === 'pr-to-merge' && ' —— 等你合并'}
        </div>
      )}
    </div>
  )
}
