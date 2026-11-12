// Spec-0073/T4: Render a grid of subject cards and open the selected subject.
import Card from './Card'
import { useBoard } from './useBoard'

export default function Board(): JSX.Element {
  const { board, open } = useBoard()

  if (board.length === 0) {
    return <div className="board-empty">No active subjects. Start one with `openagents vigil --parallel N`.</div>
  }

  return (
    <div className="board-grid">
      {board.map((entry) => (
        <Card key={entry.subject} entry={entry} onOpen={open} />
      ))}
    </div>
  )
}
