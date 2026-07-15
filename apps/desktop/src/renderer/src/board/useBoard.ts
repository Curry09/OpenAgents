// Spec-0073/T4: 看板 hook——context 纯消费者。读 board 数据 + 开大窗回调，并装 Tab 待看导航（T6）。
import { useDesktop } from '../App'
import { useTabNav } from '../nav/useTabNav'
import type { BoardEntry } from '../types'

export interface UseBoard {
  board: BoardEntry[]
  open: (subject: string) => void
}

export function useBoard(): UseBoard {
  const { board, open } = useDesktop()
  useTabNav() // Tab 键跳下一个待看小窗，装在看板层
  return { board, open: (subject: string) => open(subject) }
}
