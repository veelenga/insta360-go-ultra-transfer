const MAX_CONCURRENT = 3

let active = 0
const waiters: (() => void)[] = []

export async function acquirePreviewSlot(): Promise<() => void> {
  if (active >= MAX_CONCURRENT) {
    await new Promise<void>(resolve => waiters.push(resolve))
  }
  active++
  let released = false
  return () => {
    if (released) return
    released = true
    active--
    waiters.shift()?.()
  }
}
