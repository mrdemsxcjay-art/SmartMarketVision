import type {
  CandleResponse,
  DataState,
  DetectionsResponse,
  Quote,
  StructureResponse,
  SystemStatus,
} from '../types/market'

const TREND_CLASS: Record<string, string> = {
  BULLISH: 'trend-bull',
  BEARISH: 'trend-bear',
  RANGE: 'trend-range',
  UNDEFINED: 'trend-undef',
}

const DATA_STATE_CLASS: Record<DataState, string> = {
  CONNECTED: 'state-ok',
  CACHED: 'state-ok',
  STALE: 'state-warn',
  DATA_UNAVAILABLE: 'state-bad',
  MARKET_CLOSED: 'state-idle',
}

function clock(iso: string | null | undefined): string {
  if (!iso) return '--:--:--'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return date.toLocaleTimeString('fr-FR', { hour12: false })
}

export function MarketSummary({ quote, digits }: { quote: Quote | null; digits: number }) {
  if (!quote) {
    return (
      <section className="card summary-card" aria-label="Market summary">
        <div className="summary-value muted">—</div>
        <p className="muted">En attente des données…</p>
      </section>
    )
  }

  const unavailable = quote.data_state === 'DATA_UNAVAILABLE' || quote.price === null
  const positive = (quote.change ?? 0) >= 0

  return (
    <section className="card summary-card" aria-label="Market summary">
      <div className="summary-top">
        <div>
          <span className="label">Prix</span>
          <div className="summary-value" data-testid="quote-price">
            {unavailable ? 'DATA UNAVAILABLE' : quote.price!.toFixed(digits)}
          </div>
          {!unavailable && (
            <div className={`change ${positive ? 'change-up' : 'change-down'}`} data-testid="quote-change">
              {positive ? '▲' : '▼'} {quote.change!.toFixed(digits)} ({quote.change_percent!.toFixed(3)}%)
            </div>
          )}
        </div>
        <div className="summary-side">
          <span className="label">Paire / TF</span>
          <strong>
            {quote.symbol} · {quote.timeframe}
          </strong>
          <span className={`state-pill ${DATA_STATE_CLASS[quote.data_state]}`} data-testid="quote-state">
            {quote.data_state}
          </span>
        </div>
      </div>

      <dl className="kv">
        <div>
          <dt>Dernière bougie</dt>
          <dd>{clock(quote.candle_time)}</dd>
        </div>
        <div>
          <dt>Dernière mise à jour</dt>
          <dd>{clock(quote.last_update)}</dd>
        </div>
        <div>
          <dt>Statut marché</dt>
          <dd>{quote.market?.is_open ? `OUVERT · ${quote.market.active_sessions.join('/') || '—'}` : 'FERMÉ'}</dd>
        </div>
      </dl>

      {quote.error && <p className="warning-line">⚠ {quote.error}</p>}
      {unavailable && (
        <p className="warning-line">
          Aucun prix n'est affiché car le provider n'a pas répondu. Aucune valeur n'est inventée.
        </p>
      )}
    </section>
  )
}

export function StructurePanel({ structure }: { structure: StructureResponse | null }) {
  return (
    <section className="card" aria-label="Market structure">
      <header className="card-head">
        <h2>Structure du marché</h2>
        <span className="card-head-note">
          {structure ? `${structure.bars_analyzed} bougies · pivots ${structure.pivot_left}/${structure.pivot_right}` : ''}
        </span>
      </header>

      {!structure ? (
        <p className="muted">Analyse en attente…</p>
      ) : (
        <>
          <div className={`trend-badge ${TREND_CLASS[structure.trend] ?? 'trend-undef'}`} data-testid="trend">
            {structure.trend}
          </div>
          <div className="label-row" data-testid="structure-labels">
            {structure.recent_labels.length ? (
              structure.recent_labels.map((label, index) => (
                <span key={`${label}-${index}`} className={`label-chip label-${label}`}>
                  {label}
                </span>
              ))
            ) : (
              <span className="muted">Pas assez de pivots confirmés</span>
            )}
          </div>
          <dl className="kv">
            <div>
              <dt>Dernier swing high</dt>
              <dd>{structure.last_swing_high ? structure.last_swing_high.price.toFixed(5) : '—'}</dd>
            </div>
            <div>
              <dt>Dernier swing low</dt>
              <dd>{structure.last_swing_low ? structure.last_swing_low.price.toFixed(5) : '—'}</dd>
            </div>
            <div>
              <dt>Bougies</dt>
              <dd>{structure.using_closed_candles_only ? 'clôturées uniquement' : 'bougie en cours incluse'}</dd>
            </div>
          </dl>
          <p className="muted small">
            {structure.smc_ict.message} ({structure.swing_count} pivots détectés)
          </p>
          {structure.notes.length > 0 && (
            <ul className="notes">
              {structure.notes.slice(0, 3).map((note, index) => (
                <li key={index}>{note}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}

export function DataStatusPanel({
  status,
  candleResponse,
}: {
  status: SystemStatus | null
  candleResponse: CandleResponse | null
}) {
  return (
    <section className="card" aria-label="Data status">
      <header className="card-head">
        <h2>Statut des données</h2>
      </header>
      {!status ? (
        <p className="muted">Connexion à l'API…</p>
      ) : (
        <>
          <dl className="kv">
            <div>
              <dt>Provider</dt>
              <dd data-testid="provider-name">{status.provider}</dd>
            </div>
            <div>
              <dt>Provider joignable</dt>
              <dd className={status.provider_health.reachable ? 'state-ok' : 'state-bad'}>
                {status.provider_health.reachable ? 'OUI' : 'NON'}
              </dd>
            </div>
            <div>
              <dt>Marchés surveillés</dt>
              <dd>{status.watchlist_size}</dd>
            </div>
            <div>
              <dt>Dernier tick scanner</dt>
              <dd>{clock(status.scanner.last_tick_at)}</dd>
            </div>
            <div>
              <dt>Paires OK / échecs</dt>
              <dd>
                {status.scanner.pairs_scanned_last_tick} / {status.scanner.pairs_failed_last_tick}
              </dd>
            </div>
            <div>
              <dt>Telegram</dt>
              <dd data-testid="telegram-status">{status.telegram.status}</dd>
            </div>
            <div>
              <dt>Bougies en base</dt>
              <dd>{status.database.candles_stored}</dd>
            </div>
            <div>
              <dt>Abonnés temps réel</dt>
              <dd>{status.stream.subscribers}</dd>
            </div>
          </dl>

          {candleResponse && candleResponse.quality_warnings.length > 0 && (
            <details className="details">
              <summary>Qualité des données ({candleResponse.quality_warnings.length})</summary>
              <ul className="notes">
                {candleResponse.quality_warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            </details>
          )}
          {status.provider_health.last_error && (
            <p className="warning-line">dernière erreur provider : {status.provider_health.last_error}</p>
          )}
        </>
      )}
    </section>
  )
}

export function DetectionPanel({ detections }: { detections: DetectionsResponse | null }) {
  return (
    <section className="card detection-card" aria-label="Detections">
      <header className="card-head">
        <h2>Détections</h2>
        <span className="card-head-note">Phase 2-4</span>
      </header>
      <div className="detection-empty" data-testid="detection-state">
        {detections?.status ?? 'NO ACTIVE DETECTION'}
      </div>
      <p className="muted small">
        {detections?.message ??
          'Aucun moteur de détection (chartiste, price action, SMC/ICT) n’est activé en Phase 1. Aucune détection simulée.'}
      </p>
      <ul className="engine-list">
        {Object.entries(detections?.engines ?? {}).map(([engine, state]) => (
          <li key={engine}>
            <span>{engine}</span>
            <span className="muted">{state}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function Footer({ status }: { status: SystemStatus | null }) {
  return (
    <footer className="app-footer">
      <p>
        SMART MARKET VISION · Phase 1 — fondation, données réelles, structure générique.
        <br />
        Outil d'observation : aucune exécution d'ordre, aucun broker, aucune position.{' '}
        {status ? `Sécurité : ordre=${status.safety.order_execution} broker=${status.safety.broker_connection}` : ''}
      </p>
      <p className="muted small">
        Capture visuelle des détections : {status?.capture.status ?? 'CAPTURE_NOT_IMPLEMENTED'} · Telegram :{' '}
        {status?.telegram.status ?? 'NOT_CONFIGURED'}
      </p>
    </footer>
  )
}
