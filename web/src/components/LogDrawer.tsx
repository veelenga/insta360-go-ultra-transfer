import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { CloseIcon } from '../icons'

const POLL_INTERVAL_MS = 1000
const MAX_LINES = 2000

interface LogDrawerProps {
  onClose: () => void
}

export function LogDrawer({ onClose }: LogDrawerProps) {
  const [lines, setLines] = useState<string[]>([])
  const [copied, setCopied] = useState(false)
  const cursorRef = useRef(0)
  const bodyRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    let stopped = false
    const tick = async () => {
      try {
        const result = await api.logs(cursorRef.current)
        if (stopped || !result.lines.length) return
        cursorRef.current = result.cursor
        setLines(prev => [...prev, ...result.lines].slice(-MAX_LINES))
      } catch {
        /* server unreachable; retry on next tick */
      }
    }
    tick()
    const timer = setInterval(tick, POLL_INTERVAL_MS)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    const el = bodyRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  const copy = () => {
    navigator.clipboard.writeText(lines.join('\n'))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="drawer">
      <div className="drawer-head">
        <span>Diagnostics</span>
        <button className="secondary" onClick={copy}>
          {copied ? 'Copied' : 'Copy'}
        </button>
        <button className="icon-btn" aria-label="Close" onClick={onClose}>
          <CloseIcon />
        </button>
      </div>
      <pre className="drawer-body" ref={bodyRef}>
        {lines.join('\n')}
      </pre>
    </div>
  )
}
