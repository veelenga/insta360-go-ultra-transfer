import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type Status } from './api'
import { buildLibrary, type MediaFile } from './media'
import { TopBar } from './components/TopBar'
import { ProgressStrip } from './components/ProgressStrip'
import { Settings } from './components/Settings'
import { LogDrawer } from './components/LogDrawer'
import { Gallery } from './components/Gallery'
import { PreviewModal } from './components/PreviewModal'
import { ConnectScreen } from './components/ConnectScreen'

const STATUS_POLL_MS = 1000
const DEFAULT_HOST = '192.168.42.1'

function usePersistent(key: string, initial: string) {
  const [value, setValue] = useState(() => localStorage.getItem(key) ?? initial)
  useEffect(() => localStorage.setItem(key, value), [key, value])
  return [value, setValue] as const
}

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [files, setFiles] = useState<MediaFile[]>([])
  const [sizes, setSizes] = useState<Record<string, number>>({})
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())
  const [host, setHost] = usePersistent('host', DEFAULT_HOST)
  const [dest, setDest] = usePersistent('dest', '')
  const [showLrvRaw, setShowLrvRaw] = usePersistent('showLrv', '0')
  const showLrv = showLrvRaw === '1'
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [logsOpen, setLogsOpen] = useState(false)
  const [preview, setPreview] = useState<MediaFile | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [progressDismissed, setProgressDismissed] = useState(false)
  const sizesSettled = useRef(false)
  const wasActive = useRef(false)

  const loadFiles = useCallback(async () => {
    const listing = await api.files()
    setFiles(buildLibrary(listing.uris))
    setSizes(prev => ({ ...prev, ...listing.sizes }))
    sizesSettled.current = false
  }, [])

  useEffect(() => {
    let stopped = false
    const tick = async () => {
      try {
        const next = await api.status()
        if (stopped) return
        setStatus(next)
        if (next.downloads.active && !wasActive.current) setProgressDismissed(false)
        wasActive.current = next.downloads.active
        if (next.connected && !sizesSettled.current) {
          const result = await api.sizes()
          if (stopped) return
          setSizes(prev => ({ ...prev, ...result.sizes }))
          if (!result.scanning) sizesSettled.current = true
        }
      } catch {
        /* server unreachable; retry on next tick */
      }
    }
    tick()
    const timer = setInterval(tick, STATUS_POLL_MS)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    if (!dest && status?.defaultDest) setDest(status.defaultDest)
  }, [dest, status?.defaultDest, setDest])

  const connect = async () => {
    setBusy(true)
    setNotice(null)
    try {
      await api.connect(host.trim())
      await loadFiles()
      setSettingsOpen(false)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const disconnect = async () => {
    await api.disconnect().catch(() => {})
    setSettingsOpen(false)
  }

  const startDownload = async () => {
    try {
      await api.download([...selected], dest.trim())
      setProgressDismissed(false)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error))
    }
  }

  const visibleFiles = useMemo(
    () => files.filter(f => showLrv || f.kind !== 'lrv'),
    [files, showLrv],
  )

  const toggle = (uri: string) =>
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(uri)) next.delete(uri)
      else next.add(uri)
      return next
    })

  const toggleDay = (uris: string[]) =>
    setSelected(prev => {
      const next = new Set(prev)
      const allSelected = uris.every(uri => next.has(uri))
      for (const uri of uris) {
        if (allSelected) next.delete(uri)
        else next.add(uri)
      }
      return next
    })

  const selectedBytes = useMemo(() => {
    let total = 0
    for (const uri of selected) {
      const size = sizes[uri]
      if (size == null) return null
      total += size
    }
    return total
  }, [selected, sizes])

  const connected = status?.connected ?? false
  const downloads = status?.downloads
  const showProgress = downloads && downloads.files_total > 0 && !progressDismissed
  const showConnectScreen = !connected && files.length === 0

  return (
    <>
      <TopBar
        connected={connected}
        host={status?.host ?? host}
        selectedCount={selected.size}
        selectedBytes={selected.size ? selectedBytes : null}
        downloadDisabled={!connected || selected.size === 0 || (downloads?.active ?? false)}
        onDownload={startDownload}
        onToggleSettings={() => setSettingsOpen(open => !open)}
      />
      {showProgress && downloads && (
        <ProgressStrip
          downloads={downloads}
          onDismiss={() => setProgressDismissed(true)}
          onOpenFolder={() => api.openFolder(downloads.dest ?? '').catch(() => {})}
        />
      )}
      {settingsOpen && (
        <Settings
          connected={connected}
          host={host}
          dest={dest}
          showLrv={showLrv}
          busy={busy}
          onHostChange={setHost}
          onDestChange={setDest}
          onShowLrvChange={value => setShowLrvRaw(value ? '1' : '0')}
          onConnect={connect}
          onDisconnect={disconnect}
          onOpenLogs={() => {
            setLogsOpen(true)
            setSettingsOpen(false)
          }}
          onClose={() => setSettingsOpen(false)}
        />
      )}
      <main>
        {notice && !showConnectScreen && <p className="notice">{notice}</p>}
        {showConnectScreen ? (
          <ConnectScreen
            host={host}
            busy={busy}
            error={notice ?? status?.error ?? null}
            onHostChange={setHost}
            onConnect={connect}
          />
        ) : (
          <Gallery
            files={visibleFiles}
            sizes={sizes}
            selected={selected}
            onToggle={toggle}
            onToggleDay={toggleDay}
            onPreview={setPreview}
          />
        )}
      </main>
      {logsOpen && <LogDrawer onClose={() => setLogsOpen(false)} />}
      {preview && (
        <PreviewModal
          file={preview}
          size={sizes[preview.uri] ?? null}
          onClose={() => setPreview(null)}
        />
      )}
    </>
  )
}
