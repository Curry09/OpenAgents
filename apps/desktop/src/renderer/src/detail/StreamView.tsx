// Spec-0073/T5: Render streamed output and scroll to the latest line.
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
