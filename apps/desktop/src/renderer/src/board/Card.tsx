// Spec-0073/T4: 成果卡——一个 subject 的阶段 / PR / 证据戳 / 评论数 / automation-failed 徽标。点击发 onOpen。
import type { BoardEntry } from '../types'

export interface CardProps {
  entry: BoardEntry
  onOpen: (subject: string) => void
}

// 把队列状态 + 富化字段浓成一句人话阶段（成果优先，字段以 board.html 为起点）。
function stageLabel(entry: BoardEntry): string {
  if (entry.automation_failed) {
    return '✗ automation-failed 机器失败'
  }
  if (entry.pr_ready_to_merge) {
    return `✅ PR#${entry.pr ?? '?'} 等合并`
  }
  if (entry.pr) {
    return `↻ PR#${entry.pr} 推进中`
  }
  if (entry.status === 'claimed') {
    return '↻ 推进中'
  }
  return '… 排队中'
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
