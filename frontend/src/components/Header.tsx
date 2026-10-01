import type { StreamStatus } from '../types/market'

interface Props {
  streamStatus: StreamStatus
  lastMessageAt: Date | null
  provider: string
  serverTime: string | null
  scannerRunning: boolean
}

const STREAM_LABEL: Record<StreamStatus, { text: string; dot: string; hint: string }> = {
  LIVE: { text: 'LIVE', dot: 'dot-green', hint: 'flux temps réel actif' },
  RECONNECTING: { text: 'RECONNECTING', dot: 'dot-amber', hint: 'reconnexion en cours' },
  DISCONNECTED: { text: 'DISCONNECTED', dot: 'dot-red', hint: 'aucune donnée récente' },
}

function formatClock(value: Date | null): string {
  if (!value) return '--:--:--'
  return value.toLocaleTimeString('fr-FR', { hour12: false })
}

export function Header({ streamStatus, lastMessageAt, provider, serverTime, scannerRunning }: Props) {
  const status = STREAM_LABEL[streamStatus]
  return (
    <header className="app-header">
      <div className="brand">
        <div className="brand-mark">SMV</div>
        <div>
          <h1>SMART MARKET VISION</h1>
          <p className="brand-sub">
            Scanner de marché Forex · observation uniquement (aucun ordre exécuté)
          </p>
        </div>
      </div>

      <div className="header-status">
        <span className={`pill ${streamStatus === 'LIVE' ? 'pill-live' : 'pill-idle'}`} data-testid="stream-status">
          <span className={`dot ${status.dot}`} aria-hidden />
          {status.text}
        </span>
        <span className="meta-line">
          dernier événement <strong data-testid="last-event-time">{formatClock(lastMessageAt)}</strong>
        </span>
        <span className="meta-line">
          provider <strong>{provider}</strong> · scanner{' '}
          <strong>{scannerRunning ? 'actif' : 'arrêté'}</strong>
        </span>
        {serverTime && (
          <span className="meta-line muted">heure serveur UTC {serverTime.replace('T', ' ').slice(0, 19)}</span>
        )}
      </div>
    </header>
  )
}
