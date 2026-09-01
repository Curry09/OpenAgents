// Spec-0073/T5: 大窗流式 + 快切单测。用一个 fake client 逐条喂 SSE 事件，断言渲染与订阅清理。
import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DesktopContext, type DesktopContextValue } from '../App'
import type { BoardEntry } from '../types'
import DetailOverlay from './DetailOverlay'

// fake client：记录订阅，暴露一个 push 逐条投递 SSE 行；close 时置 closed 便于断言清理。
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
  it('mock SSE 事件逐条渲染进 StreamView', () => {
    render(
      <DesktopContext.Provider value={provide({ selected: 'issue:1' }, fake.client as never)}>
        <DetailOverlay />
      </DesktopContext.Provider>
    )
    act(() => {
      fake.subs[0].onLine('第一行')
      fake.subs[0].onLine('第二行')
    })
    expect(screen.getByTestId('stream')).toHaveTextContent('第一行')
    expect(screen.getByTestId('stream')).toHaveTextContent('第二行')
  })

  it('「下一个」按钮切 subject 并重订流（旧订阅被清理）', () => {
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
    fireEvent.click(screen.getByText('下一个 ▶'))
    expect(open).toHaveBeenCalledWith('issue:2')
  })

  it('关闭按钮触发 open(null)', () => {
    const open = vi.fn()
    render(
      <DesktopContext.Provider value={provide({ selected: 'issue:1', open }, fake.client as never)}>
        <DetailOverlay />
      </DesktopContext.Provider>
    )
    fireEvent.click(screen.getByText('关闭 ✕'))
    expect(open).toHaveBeenCalledWith(null)
  })

  it('卸载时断开 SSE 订阅', () => {
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
