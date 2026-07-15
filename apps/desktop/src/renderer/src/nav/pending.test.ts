// Spec-0073/T6: 待看优先级 + Tab 循环纯函数单测。
import { describe, expect, it } from 'vitest'
import type { BoardEntry } from '../types'
import { nextPending, orderPending, pendingCategory } from './pending'

function entry(subject: string, over: Partial<BoardEntry> = {}): BoardEntry {
  return { subject, status: 'claimed', pending: null, ...over }
}

describe('pendingCategory', () => {
  it('优先用 daemon 已算好的 pending', () => {
    expect(pendingCategory(entry('issue:1', { pending: 'pr-to-merge' }))).toBe('pr-to-merge')
  })

  it('daemon 未给时按布尔位就地推断，遵四级优先级', () => {
    expect(
      pendingCategory(entry('issue:1', { needs_human: true, pr_ready_to_merge: true }))
    ).toBe('needs-human')
    expect(pendingCategory(entry('issue:2', { has_new_human_comment: true }))).toBe('new-comment')
    expect(pendingCategory(entry('issue:3'))).toBeNull()
  })
})

describe('orderPending', () => {
  it('按四级优先级排序，非待看剔除', () => {
    const board = [
      entry('issue:changed', { pending: 'just-changed' }),
      entry('issue:idle'),
      entry('issue:human', { pending: 'needs-human' }),
      entry('issue:merge', { pending: 'pr-to-merge' }),
      entry('issue:comment', { pending: 'new-comment' })
    ]
    expect(orderPending(board).map((e) => e.subject)).toEqual([
      'issue:human',
      'issue:merge',
      'issue:comment',
      'issue:changed'
    ])
  })

  it('同级按 enqueued_at 稳定定序', () => {
    const board = [
      entry('issue:b', { pending: 'needs-human', enqueued_at: '2026-07-15T10:00:02Z' }),
      entry('issue:a', { pending: 'needs-human', enqueued_at: '2026-07-15T10:00:01Z' })
    ]
    expect(orderPending(board).map((e) => e.subject)).toEqual(['issue:a', 'issue:b'])
  })
})

describe('nextPending', () => {
  const pending = [
    entry('issue:human', { pending: 'needs-human' }),
    entry('issue:merge', { pending: 'pr-to-merge' })
  ]

  it('从当前跳下一个，循环到底回头', () => {
    expect(nextPending(pending, 'issue:human')).toBe('issue:merge')
    expect(nextPending(pending, 'issue:merge')).toBe('issue:human')
  })

  it('当前不在待看序内 → 取序首', () => {
    expect(nextPending(pending, 'pr:999')).toBe('issue:human')
    expect(nextPending(pending, null)).toBe('issue:human')
  })

  it('无待看 → null（Tab 无操作）', () => {
    expect(nextPending([], 'issue:human')).toBeNull()
  })
})
