import type { DownloadState } from '../api'
import { formatBytes, formatEta } from '../format'
import { CloseIcon } from '../icons'

interface ProgressStripProps {
  downloads: DownloadState
  onDismiss: () => void
  onOpenFolder: () => void
}

function progressText(d: DownloadState): { text: string; percent: number } {
  if (d.active) {
    const current = Math.min(d.files_done + 1, d.files_total)
    const parts = [`Copying ${current} of ${d.files_total}`]
    if (d.bytes_total) {
      parts.push(`${formatBytes(d.bytes_done)} of ${formatBytes(d.bytes_total)}`)
    } else if (d.bytes_done) {
      parts.push(formatBytes(d.bytes_done))
    }
    if (d.speed) parts.push(`${formatBytes(d.speed)}/s`)
    const eta = formatEta(d.eta)
    if (eta) parts.push(eta)
    const percent = d.bytes_total
      ? (d.bytes_done / d.bytes_total) * 100
      : (d.files_done / d.files_total) * 100
    return { text: parts.join(' · '), percent }
  }
  const failed = d.errors.length
  const text = failed
    ? `Finished with ${failed} error${failed > 1 ? 's' : ''} — see diagnostics`
    : `Copied ${d.files_done} item${d.files_done === 1 ? '' : 's'} (${formatBytes(d.bytes_done)}) to ${d.dest ?? ''}`
  return { text, percent: 100 }
}

export function ProgressStrip({ downloads, onDismiss, onOpenFolder }: ProgressStripProps) {
  const { text, percent } = progressText(downloads)
  return (
    <div className={downloads.active ? 'progress-strip' : 'progress-strip finished'}>
      <div className="progress-row">
        <span className="progress-text" title={downloads.current?.name ?? ''}>
          {text}
        </span>
        {!downloads.active && (
          <span className="progress-actions">
            {downloads.dest && (
              <button className="link" onClick={onOpenFolder}>
                Open folder
              </button>
            )}
            <button className="icon-btn small" aria-label="Dismiss" onClick={onDismiss}>
              <CloseIcon size={12} />
            </button>
          </span>
        )}
      </div>
      <div className="progress-track">
        <i style={{ width: `${Math.min(100, percent)}%` }} />
      </div>
    </div>
  )
}
