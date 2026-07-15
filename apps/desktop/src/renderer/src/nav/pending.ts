// Spec-0073/T6: 待看优先级纯函数。从 board 条目推「待看类别 + 序」，供 Tab 导航循环。
// 优先级（高→低）：① needs-human 挂起 > ② PR 等合并 > ③ 人类新评论待回 > ④ 刚变状态；同级按 enqueued 序。
import { PENDING_ORDER, type BoardEntry, type PendingCategory } from '../types'

// 类别 → 排序权重（越小越靠前）。非待看（pending=null）不入序。
const RANK: Record<PendingCategory, number> = {
  'needs-human': 0,
  'pr-to-merge': 1,
  'new-comment': 2,
  'just-changed': 3
}

// 若 daemon 未给 pending，则从富化布尔位就地推断（与 daemon.pending_category 同规则，前端兜底）。
export function pendingCategory(entry: BoardEntry): PendingCategory | null {
  if (entry.pending !== undefined && entry.pending !== null) {
    return entry.pending
  }
  if (entry.needs_human) {
    return 'needs-human'
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

// 稳定同级定序键：优先 enqueued_at，缺省回落 subject 字典序（保证确定性、可测）。
function orderKey(entry: BoardEntry): string {
  return entry.enqueued_at ?? entry.subject
}

// 把 board 过滤成「待看集」并按四级优先级 + 同级 enqueued 序排序。
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

// 从「当前 subject」在待看序里取下一个（循环到底回头）。无待看→null；当前不在序内→取序首。
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
