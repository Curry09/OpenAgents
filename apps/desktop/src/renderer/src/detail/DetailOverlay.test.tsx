// Spec-0073/T5: Check streaming, subject changes, and subscription cleanup.
import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DesktopContext, type DesktopContextValue } from '../App'
import type { BoardEntry } from '../types'
import DetailOverlay from './DetailOverlay'

// Record subscriptions so tests can deliver lines and verify cleanup.
function makeFakeClient() {
  const subs: { subject: string; onLine: (line: string) => void; closed: boolean }[] = []
  const client = {
    fetchBoard: vi.fn(),
    openStream(subject: string, onLine: (line: string) => void): () => void {
      const sub = { subject, onLine, closed: false }
      subs.push(sub)
      return () => {
        sub.closed = true
      }
    }
  }
  return { client, subs }
}

function provide(
  over: Partial<DesktopContextValue>,
  client: DesktopContextValue['client']
): DesktopContextValue {
  return {
    client,
    board: [],
    pending: [],
    selected: 'issue:1',
    open: vi.fn(),
    ...over
  }
}

let fake: ReturnType<typeof makeFakeClient>

beforeEach(() => {
  fake = makeFakeClient()
})

describe('DetailOverlay', () => {
  it('renders streamed lines in order', () => {
    render(
      <DesktopContext.Provider value={provide({ selected: 'issue:1' }, fake.client as never)}>
        <DetailOverlay />
      </DesktopContext.Provider>
    )
    act(() => {
      fake.subs[0].onLine('First line')
      fake.subs[0].onLine('Café output')
    })
    expect(screen.getByTestId('stream')).toHaveTextContent('First line')
    expect(screen.getByTestId('stream')).toHaveTextContent('Café output')
  })

  it('switches subjects and closes the old subscription on Next', () => {
    const open = vi.fn()
    const board: BoardEntry[] = [
      { subject: 'issue:1', status: 'claimed', pending: 'automation-failed' },
      { subject: 'issue:2', status: 'claimed', pending: 'automation-failed' }
    ]
    const pending = board
    render(
      <DesktopContext.Provider
        value={provide({ selected: 'issue:1', board, pending, open }, fake.client as never)}
      >
        <DetailOverlay />
      </DesktopContext.Provider>
    )
    fireEvent.click(screen.getByText('Next ▶'))
    expect(open).toHaveBeenCalledWith('issue:2')
  })

  it('closes the detail overlay', () => {
    const open = vi.fn()
    render(
      <DesktopContext.Provider value={provide({ selected: 'issue:1', open }, fake.client as never)}>
        <DetailOverlay />
      </DesktopContext.Provider>
    )
    fireEvent.click(screen.getByText('Close ✕'))
    expect(open).toHaveBeenCalledWith(null)
  })

  it('closes the SSE subscription on unmount', () => {
    const { unmount } = render(
      <DesktopContext.Provider value={provide({ selected: 'issue:1' }, fake.client as never)}>
        <DetailOverlay />
      </DesktopContext.Provider>
    )
    expect(fake.subs[0].closed).toBe(false)
    unmount()
    expect(fake.subs[0].closed).toBe(true)
  })
})
