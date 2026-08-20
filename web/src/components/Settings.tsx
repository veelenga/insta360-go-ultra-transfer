interface SettingsProps {
  connected: boolean
  host: string
  dest: string
  showLrv: boolean
  busy: boolean
  onHostChange: (value: string) => void
  onDestChange: (value: string) => void
  onShowLrvChange: (value: boolean) => void
  onConnect: () => void
  onDisconnect: () => void
  onOpenLogs: () => void
  onClose: () => void
}

export function Settings(props: SettingsProps) {
  return (
    <>
      <div className="scrim" onClick={props.onClose} />
      <div className="settings-pop">
        <label className="field">
          <span>Camera address</span>
          <div className="field-row">
            <input
              value={props.host}
              onChange={e => props.onHostChange(e.target.value)}
              spellCheck={false}
            />
            <button className="secondary" disabled={props.busy} onClick={props.onConnect}>
              {props.connected ? 'Reconnect' : 'Connect'}
            </button>
          </div>
        </label>
        <label className="field">
          <span>Save downloads to</span>
          <input
            value={props.dest}
            onChange={e => props.onDestChange(e.target.value)}
            spellCheck={false}
          />
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            checked={props.showLrv}
            onChange={e => props.onShowLrvChange(e.target.checked)}
          />
          Show LRV proxy files
        </label>
        <div className="settings-foot">
          <button className="secondary" onClick={props.onOpenLogs}>
            Diagnostics log
          </button>
          {props.connected && (
            <button className="secondary" onClick={props.onDisconnect}>
              Disconnect
            </button>
          )}
        </div>
      </div>
    </>
  )
}
