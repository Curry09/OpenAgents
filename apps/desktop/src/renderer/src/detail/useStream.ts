// Spec-0073/T5: 订 /stream/<subject> 的 hook。累积逐条 SSE 行；subject 切换/卸载时正确清理旧订阅。
import { useEffect, useState } from 'react'
import { useDesktop } from '../App'

export function useStream(subject: string | null): string[] {
  const { client } = useDesktop()
  const [lines, setLines] = useState<string[]>([])

  useEffect(() => {
    setLines([]) // 切 subject：先清空，避免上一路的流串进来
    if (subject === null) {
      return
    }
    const close = client.openStream(subject, (line) => {
      setLines((prev) => [...prev, line])
    })
    return () => close() // 切换/卸载都断旧订阅（幂等 close）
  }, [client, subject])

  return lines
}
