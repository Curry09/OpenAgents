// Spec-0073/T6: Derive pending categories and Tab navigation order from board entries.
// Prioritize failures, merge-ready PRs, human comments, then recent changes; break ties by enqueue order.
import { PENDING_ORDER, type BoardEntry, type PendingCategory } from '../types'

// Lower ranks come first. Entries without pending actions are excluded.
const RANK: Record<PendingCategory, number> = {
  'automation-failed': 0,
  'pr-to-merge': 1,
  'new-comment': 2,
  'just-changed': 3
}

// Infer the category from forge flags if the daemon did not supply one.
export function pendingCategory(entry: BoardEntry): PendingCategory | null {
  if (entry.pending !== undefined && entry.pending !== null) {
    return entry.pending
  }
  if (entry.automation_failed) {
    return 'automation-failed'
  }
  if (entry.pr_ready_to_merge) {
    return 'pr-to-merge'
  }
  if (entry.has_new_human_comment) {
    return 'new-comment'
  }
  if (entry.just_changed) {
    return 'just-changed'
  }
  return null
}

// Use the enqueue timestamp and then the subject for a stable order.
function orderKey(entry: BoardEntry): string {
  return entry.enqueued_at ?? entry.subject
}

// Keep pending entries and sort them by rank and enqueue order.
export function orderPending(board: BoardEntry[]): BoardEntry[] {
  return board
    .filter((entry) => pendingCategory(entry) !== null)
    .sort((a, b) => {
      const ra = RANK[pendingCategory(a) as PendingCategory]
      const rb = RANK[pendingCategory(b) as PendingCategory]
      if (ra !== rb) {
        return ra - rb
      }
      return orderKey(a) < orderKey(b) ? -1 : orderKey(a) > orderKey(b) ? 1 : 0
    })
}

// Cycle to the next subject, starting at the first when no current subject is in the list.
export function nextPending(pending: BoardEntry[], current: string | null): string | null {
  if (pending.length === 0) {
    return null
  }
  const idx = pending.findIndex((entry) => entry.subject === current)
  if (idx === -1) {
    return pending[0].subject
  }
  return pending[(idx + 1) % pending.length].subject
}

export { PENDING_ORDER }
