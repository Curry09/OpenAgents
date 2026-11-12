// Spec-0073/T4: Read board entries and selection actions from context.
import { useDesktop } from '../App'
import { useTabNav } from '../nav/useTabNav'
import type { BoardEntry } from '../types'

export interface UseBoard {
  board: BoardEntry[]
  open: (subject: string) => void
}

export function useBoard(): UseBoard {
  const { board, open } = useDesktop()
  useTabNav() // Install Tab navigation at the board level.
  return { board, open: (subject: string) => open(subject) }
}
