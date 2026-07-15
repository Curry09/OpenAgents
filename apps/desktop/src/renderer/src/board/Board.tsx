// Spec-0073/T4: N 小窗网格。消费 context 的 board 数据渲染成果卡；卡片点击开大窗（onOpen）。
import Card from './Card'
import { useBoard } from './useBoard'

export default function Board(): JSX.Element {
  const { board, open } = useBoard()

  if (board.length === 0) {
    return <div className="board-empty">暂无并行 subject —— 起一条 `openagents vigil --parallel N`</div>
  }

  return (
    <div className="board-grid">
      {board.map((entry) => (
        <Card key={entry.subject} entry={entry} onOpen={open} />
      ))}
    </div>
  )
}
