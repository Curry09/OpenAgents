// Spec-0073/T4: 看板小窗单测（vitest + jsdom + testing-library）。
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
  it('渲染 N 张卡，状态/徽标正确', () => {
    const board: BoardEntry[] = [
      { subject: 'issue:1', status: 'claimed', pending: 'needs-human', needs_human: true },
      { subject: 'pr:2', status: 'claimed', pending: 'pr-to-merge', pr: 2, pr_ready_to_merge: true }
    ]
    renderBoard(provide(board))
    expect(screen.getByText('issue:1')).toBeInTheDocument()
    expect(screen.getByText('pr:2')).toBeInTheDocument()
    expect(screen.getByText('needs-human')).toBeInTheDocument()
    expect(screen.getByText('✅ PR#2 等合并')).toBeInTheDocument()
  })

  it('点击卡片触发 onOpen(subject)', () => {
    const open = vi.fn()
    const board: BoardEntry[] = [{ subject: 'issue:1', status: 'claimed', pending: null }]
    renderBoard(provide(board, open))
    fireEvent.click(screen.getByText('issue:1'))
    expect(open).toHaveBeenCalledWith('issue:1')
  })

  it('空态渲染不报错', () => {
    renderBoard(provide([]))
    expect(screen.getByText(/暂无并行 subject/)).toBeInTheDocument()
  })
})

describe('stageLabel', () => {
  it('needs-human 优先于其它阶段', () => {
    expect(stageLabel({ subject: 'issue:1', status: 'claimed', pending: null, needs_human: true })).toContain(
      'needs-human'
    )
  })
  it('无 PR 且排队 → 排队中', () => {
    expect(stageLabel({ subject: 'issue:1', status: 'queued', pending: null })).toContain('排队中')
  })
})
