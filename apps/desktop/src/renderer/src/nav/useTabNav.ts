// Spec-0073/T6: Tab advances to the next pending subject and wraps around.
// Read pending entries and selection from context without importing other features.
import { useEffect } from 'react'
import { useDesktop } from '../App'
import { nextPending } from './pending'

export function useTabNav(): void {
  const { pending, selected, open } = useDesktop()

  useEffect(() => {
    const onKeyDown = (evt: KeyboardEvent): void => {
      if (evt.key !== 'Tab') {
        return
      }
      const target = nextPending(pending, selected)
      if (target === null) {
        return // Preserve normal Tab focus behavior when nothing is pending.
      }
      evt.preventDefault()
      open(target)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [pending, selected, open])
}
