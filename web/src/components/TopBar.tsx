import { formatBytes } from '../format'
import { GearIcon } from '../icons'

interface TopBarProps {
  connected: boolean
  host: string
  selectedCount: number
  selectedBytes: number | null
  downloadDisabled: boolean
  onDownload: () => void
  onToggleSettings: () => void
}

export function TopBar(props: TopBarProps) {
  const { connected, host, selectedCount, selectedBytes } = props
  const selectionLabel =
    selectedCount === 0
      ? ''
      : selectedBytes != null
        ? `${selectedCount} selected · ${formatBytes(selectedBytes)}`
        : `${selectedCount} selected`
  return (
    <header className="topbar">
      <div className="topbar-left">
        <span className="wordmark">GO Ultra</span>
        <span className={connected ? 'conn on' : 'conn'}>
          <i className="dot" />
          {connected ? host : 'not connected'}
        </span>
      </div>
      <div className="topbar-right">
        {selectionLabel && <span className="sel-label">{selectionLabel}</span>}
        <button className="primary" disabled={props.downloadDisabled} onClick={props.onDownload}>
          Download
        </button>
        <button className="icon-btn" aria-label="Settings" onClick={props.onToggleSettings}>
          <GearIcon />
        </button>
      </div>
    </header>
  )
}
