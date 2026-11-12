// Spec-0073/T4: Summarize a subject’s phase, PR, evidence, comments, and failure status.
import type { BoardEntry } from '../types'

export interface CardProps {
  entry: BoardEntry
  onOpen: (subject: string) => void
}

// Combine queue state and forge metadata into a short status label.
function stageLabel(entry: BoardEntry): string {
  if (entry.automation_failed) {
    return '✗ automation-failed'
  }
  if (entry.pr_ready_to_merge) {
    return `✅ PR#${entry.pr ?? '?'} awaiting merge`
  }
  if (entry.pr) {
    return `↻ PR#${entry.pr} In progress`
  }
  if (entry.status === 'claimed') {
    return '↻ In progress'
  }
  return '… Queued'
}

export default function Card({ entry, onOpen }: CardProps): JSX.Element {
  const isPending = entry.pending !== null
  const className = `card${isPending ? ' is-pending' : ''}`
  return (
    <div
      className={className}
      data-subject={entry.subject}
      data-pending={entry.pending ?? ''}
      role="button"
      tabIndex={0}
      onClick={() => onOpen(entry.subject)}
      onKeyDown={(evt) => {
        if (evt.key === 'Enter' || evt.key === ' ') {
          onOpen(entry.subject)
        }
      }}
    >
      <div className="card__subject">{entry.subject}</div>
      <div className="card__stage">{stageLabel(entry)}</div>
      {entry.automation_failed && <span className="badge badge--automation-failed">automation-failed</span>}
    </div>
  )
}

export { stageLabel }
