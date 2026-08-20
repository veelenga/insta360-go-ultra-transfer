interface ConnectScreenProps {
  host: string
  busy: boolean
  error: string | null
  onHostChange: (value: string) => void
  onConnect: () => void
}

export function ConnectScreen(props: ConnectScreenProps) {
  return (
    <div className="connect-screen">
      <div className="connect-card">
        <h1>GO Ultra transfer</h1>
        <p>Join the camera's WiFi hotspot (GO Ultra XXXXXX.OSC), then connect.</p>
        <div className="field-row">
          <input
            value={props.host}
            onChange={e => props.onHostChange(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && props.onConnect()}
            spellCheck={false}
          />
          <button className="primary" disabled={props.busy} onClick={props.onConnect}>
            {props.busy ? 'Connecting…' : 'Connect'}
          </button>
        </div>
        {props.error && <p className="error">{props.error}</p>}
      </div>
    </div>
  )
}
