// Spec-0073/T4: Check board cards, statuses, and selection.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DesktopContext, type DesktopContextValue } from '../App'
import type { BoardEntry } from '../types'
import Board from './Board'
import { stageLabel } from './Card'

function provide(board: BoardEntry[], open = vi.fn()): DesktopContextValue {
  return {
    client: {} as DesktopContextValue['client'],
    board,
    pending: [],
    selected: null,
    open
  }
}

function renderBoard(value: DesktopContextValue): void {
  render(<DesktopContext.Provider value={value}>{<Board />}</DesktopContext.Provider>)
}

describe('Board', () => {
  it('renders one card per entry with the right status and badge', () => {
    const board: BoardEntry[] = [
      { subject: 'issue:1', status: 'claimed', pending: 'automation-failed', automation_failed: true },
      { subject: 'pr:2', status: 'claimed', pending: 'pr-to-merge', pr: 2, pr_ready_to_merge: true }
    ]
    renderBoard(provide(board))
    expect(screen.getByText('issue:1')).toBeInTheDocument()
    expect(screen.getByText('pr:2')).toBeInTheDocument()
    expect(screen.getByText('automation-failed')).toBeInTheDocument()
    expect(screen.getByText('✅ PR#2 awaiting merge')).toBeInTheDocument()
  })

  it('opens the subject when its card is clicked', () => {
    const open = vi.fn()
    const board: BoardEntry[] = [{ subject: 'issue:1', status: 'claimed', pending: null }]
    renderBoard(provide(board, open))
    fireEvent.click(screen.getByText('issue:1'))
    expect(open).toHaveBeenCalledWith('issue:1')
  })

  it('renders the empty state', () => {
    renderBoard(provide([]))
    expect(screen.getByText(/No active subjects/)).toBeInTheDocument()
  })
})

describe('stageLabel', () => {
  it('prioritizes automation failure over other statuses', () => {
    expect(stageLabel({ subject: 'issue:1', status: 'claimed', pending: null, automation_failed: true })).toContain(
      'automation-failed'
    )
  })
  it('labels an entry without a PR as queued', () => {
    expect(stageLabel({ subject: 'issue:1', status: 'queued', pending: null })).toContain('Queued')
  })
})
