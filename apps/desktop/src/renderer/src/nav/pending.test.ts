// Spec-0073/T6: Check pending order and cyclic Tab navigation.
import { describe, expect, it } from 'vitest'
import type { BoardEntry } from '../types'
import { nextPending, orderPending, pendingCategory } from './pending'

function entry(subject: string, over: Partial<BoardEntry> = {}): BoardEntry {
  return { subject, status: 'claimed', pending: null, ...over }
}

describe('pendingCategory', () => {
  it('uses the pending category computed by the daemon', () => {
    expect(pendingCategory(entry('issue:1', { pending: 'pr-to-merge' }))).toBe('pr-to-merge')
  })

  it('infers the pending category in priority order when absent', () => {
    expect(
      pendingCategory(entry('issue:1', { automation_failed: true, pr_ready_to_merge: true }))
    ).toBe('automation-failed')
    expect(pendingCategory(entry('issue:2', { has_new_human_comment: true }))).toBe('new-comment')
    expect(pendingCategory(entry('issue:3'))).toBeNull()
  })
})

describe('orderPending', () => {
  it('sorts by priority and excludes entries with no pending action', () => {
    const board = [
      entry('issue:changed', { pending: 'just-changed' }),
      entry('issue:idle'),
      entry('issue:human', { pending: 'automation-failed' }),
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

  it('uses enqueued_at as the stable tie breaker', () => {
    const board = [
      entry('issue:b', { pending: 'automation-failed', enqueued_at: '2026-07-15T10:00:02Z' }),
      entry('issue:a', { pending: 'automation-failed', enqueued_at: '2026-07-15T10:00:01Z' })
    ]
    expect(orderPending(board).map((e) => e.subject)).toEqual(['issue:a', 'issue:b'])
  })
})

describe('nextPending', () => {
  const pending = [
    entry('issue:human', { pending: 'automation-failed' }),
    entry('issue:merge', { pending: 'pr-to-merge' })
  ]

  it('cycles to the next pending entry and wraps around', () => {
    expect(nextPending(pending, 'issue:human')).toBe('issue:merge')
    expect(nextPending(pending, 'issue:merge')).toBe('issue:human')
  })

  it('selects the first pending entry when the current one is absent', () => {
    expect(nextPending(pending, 'pr:999')).toBe('issue:human')
    expect(nextPending(pending, null)).toBe('issue:human')
  })

  it('returns null when no action is pending', () => {
    expect(nextPending([], 'issue:human')).toBeNull()
  })
})
