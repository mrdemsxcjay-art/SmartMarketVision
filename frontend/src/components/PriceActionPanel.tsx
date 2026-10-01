/**
 * PRICE ACTION panel (Phase 3).
 *
 * Four blocks, all fed by real detections only:
 *   * ÉTAT DE MARCHÉ - the measured structural states (impulsion, consolidation)
 *     with the numbers that produced them;
 *   * DÉTECTIONS PRICE ACTION - candlestick patterns, each with its direction,
 *     status, confidence and the count of validated criteria ("5 / 6 critères");
 *   * CONTEXTE - the relation with the real chartist levels (support, resistance,
 *     channel...) and the active chartist formations: informative only;
 *   * HISTORIQUE - what the engine stored.
 *
 * Nothing is computed here, and nothing is a recommendation: the panel never
 * shows BUY / SELL / ENTRY / SL / TP, only DETECTED / CONFIRMED / INVALIDATED /
 * EXPIRED and objective measurements.
 */
import { useMemo, useState } from 'react'
import type {
  ConfluenceResponse,
  DetectionHistoryResponse,
  DetectionsResponse,
  LevelContext,
  PatternDetection,
} from '../types/market'
import { directionLabel, statusLabel } from './PatternsPanel'

const PATTERN_LABEL: Record<string, string> = {
  BULLISH_ENGULFING: 'Englobante haussière',
  BEARISH_ENGULFING: 'Englobante baissière',
  BULLISH_PIN_BAR: 'Pin bar haussier',
  BEARISH_PIN_BAR: 'Pin bar baissier',
  HAMMER: 'Marteau',
  SHOOTING_STAR: 'Étoile filante',
  INSIDE_BAR: 'Inside bar',
  OUTSIDE_BAR: 'Outside bar',
  DOJI: 'Doji',
  IMPULSION: 'Impulsion',
  CONSOLIDATION: 'Consolidation',
  REJECTION: 'Rejet de niveau',
  FAILED_BREAKOUT: 'Cassure manquée',
}

const STATE_PATTERNS = new Set(['IMPULSION', 'CONSOLIDATION'])

export function priceActionLabel(pattern: string): string {
  return PATTERN_LABEL[pattern] ?? pattern
}

function passedCriteria(detection: PatternDetection): number {
  return detection.confidence_factors.filter((factor) => factor.passed).length
}

function criteriaText(detection: PatternDetection): string {
  return `${passedCriteria(detection)} / ${detection.confidence_factors.length} critères`
}

function formatBarTime(time: number | null): string {
  if (!time) return '—'
  const date = new Date(time * 1000)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function levelContextOf(detection: PatternDetection): LevelContext | null {
  const context = detection.evidence_points?.level_context
  if (!context || typeof context !== 'object') return null
  return context as LevelContext
}

/** A few readable measurements, never an interpretation. */
function keyMeasurements(detection: PatternDetection): string[] {
  const measurements = (detection.evidence_points?.measurements ?? {}) as Record<string, unknown>
  const order = [
    'coverage_ratio',
    'body_multiple',
    'body_ratio',
    'dominant_wick_ratio',
    'opposite_wick_ratio',
    'wick_to_body',
    'range_ratio',
    'range_pips',
    'compression',
    'box_height_pips',
    'net_move_pips',
    'efficiency',
    'return_distance_pips',
    'bars_after_breakout',
  ]
  const rows: string[] = []
  for (const key of order) {
    const value = measurements[key]
    if (value === undefined || value === null) continue
    const label = key.replace(/_/g, ' ')
    rows.push(`${label} : ${typeof value === 'number' ? value : String(value)}`)
  }
  return rows.slice(0, 6)
}

interface Props {
  detections: DetectionsResponse | null
  structure: DetectionsResponse | null
  history: DetectionHistoryResponse | null
  confluence: ConfluenceResponse | null
  selectedId: string | null
  onSelect: (detection: PatternDetection | null) => void
  historyError?: string | null
}

export function PriceActionPanel({
  detections,
  structure,
  history,
  confluence,
  selectedId,
  onSelect,
  historyError,
}: Props) {
  const [openId, setOpenId] = useState<string | null>(null)

  const rows = detections?.detections ?? []
  const states = structure?.detections ?? []
  // "active" = still tracked by the engine (DETECTED, or CONFIRMED once the
  // pattern was really validated). INVALIDATED / EXPIRED are history.
  const active = useMemo(
    () => rows.filter((row) => row.status === 'DETECTED' || row.status === 'CONFIRMED'),
    [rows],
  )
  const recent = useMemo(
    () => rows.filter((row) => row.status === 'INVALIDATED' || row.status === 'EXPIRED').slice(0, 8),
    [rows],
  )
  const group = confluence?.groups?.[0] ?? null

  return (
    <section className="card" aria-label="Price action" data-testid="price-action-panel">
      <header className="card-head">
        <h2>
          PRICE ACTION <span className="muted">Phase 3</span>
        </h2>
        <span className="card-head-note">
          {rows.length} motif(s) suivi(s) · {states.length} état(s) mesuré(s)
        </span>
      </header>

      <p className="panel-note" data-testid="price-action-disclaimer">
        Détections issues de bougies clôturées et de critères explicites. Aucun signal de trading :
        le moteur observe et mesure, la décision reste humaine.
      </p>

      {states.length > 0 && (
        <div className="detection-block" data-testid="pa-structure-block">
          <h3>ÉTAT DE MARCHÉ</h3>
          <ul className="detection-list">
            {states.map((state) => (
              <li key={state.id} className="detection-row state" data-testid="pa-structure-row">
                <div className="detection-line">
                  <span className="badge badge-price-action">ÉTAT</span>
                  <strong>{priceActionLabel(state.pattern)}</strong>
                  <span className="muted">
                    {state.symbol} {state.timeframe} · {directionLabel(state.direction)} · barre{' '}
                    {formatBarTime(state.detected_at_bar_time)}
                  </span>
                  <button
                    type="button"
                    className="ghost-button small"
                    onClick={() => onSelect(state)}
                    data-testid="pa-show-chart"
                  >
                    VOIR SUR LE GRAPHIQUE
                  </button>
                </div>
                <div className="criteria">
                  {keyMeasurements(state).map((row) => (
                    <span key={row} className="measurement">
                      {row}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="detection-block" data-testid="pa-active-block">
        <h3>DÉTECTIONS ACTIVES</h3>
        {active.length === 0 ? (
          <p className="muted" data-testid="pa-no-active">
            AUCUNE DÉTECTION PRICE ACTION ACTIVE
          </p>
        ) : (
          <ul className="detection-list">
            {active.map((detection) => (
              <li
                key={detection.id}
                className={`detection-row ${selectedId === detection.id ? 'selected' : ''}`}
                data-testid="pa-row"
              >
                <div className="detection-line">
                  <span className="badge badge-price-action">PA</span>
                  <strong>{priceActionLabel(detection.pattern)}</strong>
                  <span className="muted">
                    {detection.symbol} {detection.timeframe} · {directionLabel(detection.direction)} ·{' '}
                    {formatBarTime(detection.detected_at_bar_time)} · {statusLabel(detection.status)}
                  </span>
                  <span className="confidence" data-testid="pa-criteria">
                    {criteriaText(detection)} · {Math.round(detection.confidence)}%
                  </span>
                  <button
                    type="button"
                    className="ghost-button small"
                    onClick={() => onSelect(detection)}
                    data-testid="pa-show-chart"
                  >
                    VOIR SUR LE GRAPHIQUE
                  </button>
                  <button
                    type="button"
                    className="ghost-button small"
                    onClick={() => setOpenId(openId === detection.id ? null : detection.id)}
                    data-testid="pa-toggle-evidence"
                  >
                    {openId === detection.id ? 'MASQUER' : 'PREUVES'}
                  </button>
                </div>

                <div className="detection-meta">
                  {levelContextOf(detection)?.label && (
                    <span className="context-label" data-testid="pa-context">
                      CONTEXTE : {levelContextOf(detection)?.label}
                    </span>
                  )}
                  {keyMeasurements(detection).map((row) => (
                    <span key={row} className="measurement">
                      {row}
                    </span>
                  ))}
                </div>

                {openId === detection.id && (
                  <div className="evidence" data-testid="pa-evidence">
                    <ul>
                      {detection.evidence.map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                    <h4>Critères</h4>
                    <ul>
                      {detection.confidence_factors.map((factor) => (
                        <li key={factor.criterion} className={factor.passed ? 'ok' : 'ko'}>
                          {factor.passed ? 'OK' : 'NON'} · {factor.criterion} (poids {factor.weight}) :{' '}
                          {factor.detail}
                        </li>
                      ))}
                    </ul>
                    {levelContextOf(detection)?.nearest && (
                      <>
                        <h4>Contexte (non compté dans la confiance)</h4>
                        <ul>
                          <li>
                            {levelContextOf(detection)?.nearest?.kind} à{' '}
                            {levelContextOf(detection)?.nearest?.price} (
                            {levelContextOf(detection)?.nearest?.distance_pips} pip) via{' '}
                            {levelContextOf(detection)?.nearest?.source}
                          </li>
                          {(levelContextOf(detection)?.chartist_active ?? []).map((item) => (
                            <li key={item.id}>
                              {item.pattern} ({item.status}, {item.bars_away} bougies)
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {recent.length > 0 && (
        <div className="detection-block" data-testid="pa-recent-block">
          <h3>RÉCENTES (CONFIRMÉES / INVALIDÉES / EXPIRÉES)</h3>
          <ul className="detection-list">
            {recent.map((detection) => (
              <li key={detection.id} className="detection-row" data-testid="pa-recent-row">
                <div className="detection-line">
                  <span className="badge badge-price-action">PA</span>
                  <strong>{priceActionLabel(detection.pattern)}</strong>
                  <span className="muted">
                    {detection.symbol} {detection.timeframe} · {directionLabel(detection.direction)} ·{' '}
                    {statusLabel(detection.status)}
                  </span>
                  <span className="confidence">{criteriaText(detection)}</span>
                  <button type="button" className="ghost-button small" onClick={() => onSelect(detection)}>
                    VOIR
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {group && (
        <div className="detection-block" data-testid="pa-confluence-block">
          <h3>CONFLUENCE (INFORMATIF)</h3>
          <p className="muted" data-testid="pa-confluence-note">
            {group.groups.chartist.length} élément(s) chartiste(s) · {group.groups.price_action.length} prix
            action · {group.groups.structure.length} état(s) — aucun score, aucun classement, aucun signal.
          </p>
        </div>
      )}

      <div className="detection-block">
        <h3>HISTORIQUE PRICE ACTION</h3>
        {historyError && <p className="muted">{historyError}</p>}
        {!history?.detections?.length ? (
          <p className="muted">AUCUN HISTORIQUE PRICE ACTION</p>
        ) : (
          <div className="table-scroll">
            <table className="detection-table" data-testid="pa-history-table">
              <thead>
                <tr>
                  <th>Barre</th>
                  <th>Paire</th>
                  <th>UT</th>
                  <th>Motif</th>
                  <th>Sens</th>
                  <th>Statut</th>
                  <th>Critères</th>
                </tr>
              </thead>
              <tbody>
                {history.detections.slice(0, 20).map((detection) => (
                  <tr key={`${detection.id}-hist`}>
                    <td>{formatBarTime(detection.detected_at_bar_time)}</td>
                    <td>{detection.symbol}</td>
                    <td>{detection.timeframe}</td>
                    <td>{priceActionLabel(detection.pattern)}</td>
                    <td>{directionLabel(detection.direction)}</td>
                    <td>{statusLabel(detection.status)}</td>
                    <td>{criteriaText(detection)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}

export { STATE_PATTERNS as PRICE_ACTION_STATE_PATTERNS }
