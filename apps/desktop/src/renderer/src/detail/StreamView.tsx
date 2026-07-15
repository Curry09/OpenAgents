// Spec-0073/T5: 大窗上半——把 SSE 逐条累积的 agent 会话行实时渲染，新行到底自动贴底。
import { useEffect, useRef } from 'react'

export interface StreamViewProps {
  lines: string[]
}

export default function StreamView({ lines }: StreamViewProps): JSX.Element {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (el !== null) {
      el.scrollTop = el.scrollHeight
    }
  }, [lines])

  return (
    <div className="stream" ref={ref} data-testid="stream">
      {lines.map((line, idx) => (
        <div key={idx} className="stream__line">
          {line}
        </div>
      ))}
    </div>
  )
}
