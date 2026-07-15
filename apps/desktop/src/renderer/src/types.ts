// Spec-0073/T3: 镜像 daemon JSON 的共享 TS 类型（单一契约，前端各扩展点都依赖它）。
// 字段与 openagents/desktop/daemon.py 的 build_board / pending_category 一一对应。

// 待看四类，高→低优先级（与 daemon.PENDING_* 及 nav/pending.ts 同序）。
export type PendingCategory = 'needs-human' | 'pr-to-merge' | 'new-comment' | 'just-changed'

export const PENDING_ORDER: PendingCategory[] = [
  'needs-human',
  'pr-to-merge',
  'new-comment',
  'just-changed'
]

// /board 返回数组的一项：一个 subject 的成果/状态快照。
export interface BoardEntry {
  subject: string // "issue:170" | "pr:170"
  status: string | null // work_queue 状态：queued | claimed
  worker?: string | null
  attempts?: number | null
  // 以下为 daemon 的 GitHub 富化字段（离线时缺省）。
  pr?: number | null
  labels?: string[]
  needs_human?: boolean
  pr_ready_to_merge?: boolean
  has_new_human_comment?: boolean
  just_changed?: boolean
  // enqueued 顺序，用于同级待看的稳定定序（缺省回落 subject 字典序）。
  enqueued_at?: string | null
  // daemon 已算好的待看类别；null = 不在待看集。
  pending: PendingCategory | null
}

// SSE /stream/<subject> 的一帧：一行 agent 会话文本。
export interface StreamLine {
  line: string
}
