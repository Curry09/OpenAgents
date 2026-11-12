// Spec-0073/T5: Show the live stream and delivery status in a full-screen overlay.
import { useEffect } from 'react'
import { useDesktop } from '../App'
import { nextPending } from '../nav/pending'
import StreamView from './StreamView'
import { useStream } from './useStream'

export default function DetailOverlay(): JSX.Element | null {
  const { board, pending, selected, open } = useDesktop()
  const lines = useStream(selected)

  // Return to the board on Escape.
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
    <div className="overlay" role="dialog" aria-label={`Delivery details for ${selected}`}>
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
            Next ▶
          </button>
          <button type="button" onClick={() => open(null)}>
            Close ✕
          </button>
        </span>
      </div>
      <StreamView lines={lines} />
      {entry?.pr && (
        <div className="overlay__anchor">
          Deliverable: PR #{entry.pr}
          {entry.pending === 'pr-to-merge' && ' — Awaiting merge'}
        </div>
      )}
    </div>
  )
}
