// Spec-0073/T6: 装 Tab 键 handler，把焦点/大窗跳到下一个「待看」subject（循环到底回头，无待看则无操作）。
// context 的纯消费者：读 pending 列表与 selected，调 open 切换。不 import 其它 feature。
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
        return // 无待看：Tab 无操作（不吞事件、不打断默认焦点行为）
      }
      evt.preventDefault()
      open(target)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [pending, selected, open])
}
