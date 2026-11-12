// Spec-0073/T5: Subscribe to subject output and clean up on switch or unmount.
import { useEffect, useState } from 'react'
import { useDesktop } from '../App'

export function useStream(subject: string | null): string[] {
  const { client } = useDesktop()
  const [lines, setLines] = useState<string[]>([])

  useEffect(() => {
    setLines([]) // Clear the previous subject’s output before subscribing.
    if (subject === null) {
      return
    }
    const close = client.openStream(subject, (line) => {
      setLines((prev) => [...prev, line])
    })
    return () => close() // Close the previous subscription.
  }, [client, subject])

  return lines
}
