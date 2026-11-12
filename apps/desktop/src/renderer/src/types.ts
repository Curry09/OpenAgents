// Spec-0073/T3: Mirror the daemon JSON contract in TypeScript.
// See build_board and pending_category in openagents/desktop/daemon.py.

// Categories in descending priority; keep aligned with the daemon and pending.ts.
export type PendingCategory = 'automation-failed' | 'pr-to-merge' | 'new-comment' | 'just-changed'

export const PENDING_ORDER: PendingCategory[] = [
  'automation-failed',
  'pr-to-merge',
  'new-comment',
  'just-changed'
]

// One subject snapshot from /board.
export interface BoardEntry {
  subject: string // "issue:170" | "pr:170"
  status: string | null // Queue state: queued or claimed.
  worker?: string | null
  attempts?: number | null
  // Forge metadata may be absent when offline.
  pr?: number | null
  labels?: string[]
  automation_failed?: boolean
  pr_ready_to_merge?: boolean
  has_new_human_comment?: boolean
  just_changed?: boolean
  // Enqueue timestamp for stable ordering within a category.
  enqueued_at?: string | null
  // Category computed by the daemon; null means no pending action.
  pending: PendingCategory | null
}

// One line of agent output from /stream/<subject>.
export interface StreamLine {
  line: string
}
