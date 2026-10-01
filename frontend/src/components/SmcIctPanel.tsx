/**
 * SMC / ICT panel (Phase 4, sections 18, 19, 22).
 *
 * Every block is fed by real detections only, grouped by the family the engine
 * published (evidence_points.family):
 *   * STRUCTURE  - BOS / CHOCH / MSS, with the level that was broken;
 *   * LIQUIDITÉ  - equal highs / lows, liquidity pools (ESTIMATES) and sweeps;
 *   * GAPS       - FVG with their lifecycle state (CREATED -> FILLED);
 *   * BLOCS      - order blocks and breakers, with their zone;
 *   * RANGES     - dealing range, premium / discount.
 *
 * Each row answers "why": direction, status, the price it was measured at, the
 * candle time, the number of validated criteria, and - on demand - the full
 * evidence and the criteria with their weight and detail.
 *
 * Nothing here is a recommendation: no BUY / SELL / ENTRY / SL / TP, no score.
 * Liquidity is ALWAYS presented as an estimate of the engine, never as a
 * knowledge of real orders.
 */
import { useMemo, useState } from 'react'
import type {
  DetectionHistoryResponse,
  DetectionsResponse,
  PatternDetection,
  SmcConfluenceResponse,
  SmcEvidencePoints,
} from '../types/market'
import { directionLabel, statusLabel } from './PatternsPanel'

/** French labels of the SMC/ICT concepts. */
const SMC_LABEL: Record<string, string> = {
  BOS: 'Cassure de structure (BOS)',
  CHOCH: 'Changement de caractère (CHOCH)',
  MSS: 'Décalage de structure (MSS)',
  EQUAL_HIGH: 'Sommets quasi égaux',
  EQUAL_LOW: 'Creux quasi égaux',
  LIQUIDITY_POOL_ESTIMATE: 'Zone de liquidité (estimation)',
  LIQUIDITY_SWEEP: 'Balayage de liquidité',
  BULLISH_FVG: 'FVG haussier',
  BEARISH_FVG: 'FVG baissier',
  BULLISH_ORDER_BLOCK: 'Bloc d’ordres haussier',
  BEARISH_ORDER_BLOCK: 'Bloc d’ordres baissier',
  BREAKER_BLOCK: 'Breaker',
  DISPLACEMENT: 'Déplacement',
  DEALING_RANGE: 'Range de travail',
  PREMIUM: 'Zone premium',
  DISCOUNT: 'Zone discount',
  SWING_HIGH: 'Sommet (swing high)',
  SWING_LOW: 'Creux (swing low)',
}

export function smcLabel(pattern: string): string {
  return SMC_LABEL[pattern] ?? pattern
}

const STATE_LABEL: Record<string, string> = {
  CREATED: 'CRÉÉ',
  ACTIVE: 'ACTIF',
  PARTIALLY_FILLED: 'PARTIELLEMENT COMBLÉ',
  FILLED: 'COMBLÉ',
  MITIGATED: 'MITIGÉ',
  INVALIDATED: 'INVALIDÉ',
  CONFIRMED: 'CONFIRMÉ',
  DETECTED: 'DÉTECTÉ',
}

/** Lifecycle state published by the engine for the concept (section 20). */
function smcState(detection: PatternDetection): string | null {
  const points = (detection.evidence_points ?? {}) as SmcEvidencePoints
  const measurements = (points.measurements ?? {}) as Record<string, unknown>
  const state = points.smc_state ?? measurements.state
  return typeof state === 'string' && state ? state : null
}

function family(detection: PatternDetection): string {
  const points = (detection.evidence_points ?? {}) as SmcEvidencePoints
  return String(points.family ?? 'AUTRE')
}

function measurementsOf(detection: PatternDetection): Record<string, unknown> {
  const points = (detection.evidence_points ?? {}) as SmcEvidencePoints
  return (points.measurements ?? {}) as Record<string, unknown>
}

/** The price the object was measured at: always a real candle coordinate. */
function measuredPrice(detection: PatternDetection): string {
  const coordinate = detection.coordinates?.[0]
  if (!coordinate) return '—'
  return coordinate.price.toLocaleString('fr-FR', {
    minimumFractionDigits: 5,
    maximumFractionDigits: 5,
  })
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

function passedCriteria(detection: PatternDetection): number {
  return detection.confidence_factors.filter((factor) => factor.passed).length
}

/**
 * Readable measurements, in the order that explains the concept. The values
 * come from the engine, they are never recomputed here.
 */
const MEASUREMENT_ORDER = [
  'close_excess_pips',
  'close_excess_atr',
  'threshold_pips',
  'swing_price',
  'swing_strength',
  'bars_since_swing',
  'previous_structure',
  'bars_after_choch',
  'shift_extension_pips',
  'touch_count',
  'tolerance_pips',
  'spread_pips',
  'age_bars',
  'score',
  'reentry_pips',
  'reentry_to_extreme_pips',
  'size_pips',
  'size_atr',
  'coverage_share',
  'state',
  'span_pips',
  'span_atr',
  'position',
  'range_pips',
  'range_atr',
  'net_move_pips',
  'net_move_atr',
  'body_ratio',
  'efficiency',
  'same_direction_bars',
]

function keyMeasurements(detection: PatternDetection, limit = 6): string[] {
  const measurements = measurementsOf(detection)
  const rows: string[] = []
  for (const key of MEASUREMENT_ORDER) {
    const value = measurements[key]
    if (value === undefined || value === null || typeof value === 'object') continue
    rows.push(`${key.replace(/_/g, ' ')} : ${String(value)}`)
  }
  if (rows.length === 0) {
    for (const [key, value] of Object.entries(measurements)) {
      if (value === null || typeof value === 'object') continue
      rows.push(`${key.replace(/_/g, ' ')} : ${String(value)}`)
    }
  }
  return rows.slice(0, limit)
}

const FAMILIES: { key: string; title: string; note: string }[] = [
  { key: 'STRUCTURE', title: 'STRUCTURE DE MARCHÉ', note: 'BOS / CHOCH / MSS sur pivots réels' },
  {
    key: 'LIQUIDITY',
    title: 'LIQUIDITÉ (ESTIMATION)',
    note: 'niveaux mesurés et zones probables : aucun ordre réel n’est observé',
  },
  { key: 'GAPS', title: 'DÉSÉQUILIBRES (FVG)', note: 'bandes de 3 bougies et leur mitigation' },
  { key: 'BLOCKS', title: 'BLOCS D’ORDRES / BREAKERS', note: 'zones d’origine mesurées' },
  { key: 'RANGE', title: 'RANGES / PREMIUM · DISCOUNT', note: 'lecture proportionnelle, jamais un signal' },
]

interface Props {
  detections: DetectionsResponse | null
  structure: DetectionsResponse | null
  history: DetectionHistoryResponse | null
  confluence: SmcConfluenceResponse | null
  selectedId: string | null
  onSelect: (detection: PatternDetection | null) => void
  historyError?: string | null
  /** the engine could not be read: never displayed as "nothing detected" */
  error?: string | null
  /** how many layers the chart draws at the same time (section 28) */
  maxOverlays: number
}

export function SmcIctPanel({
  detections,
  structure,
  history,
  confluence,
  selectedId,
  onSelect,
  historyError,
  error,
  maxOverlays,
}: Props) {
  const [openId, setOpenId] = useState<string | null>(null)
  const [historyPattern, setHistoryPattern] = useState<string>('TOUS')

  const rows = detections?.detections ?? []
  const engines = detections?.engines ?? {}
  const stats = (detections?.stats ?? {}) as Record<string, unknown>
  const byStatus = (stats.by_status ?? {}) as Record<string, number>
  const byPattern = (stats.by_pattern ?? {}) as Record<string, number>

  const grouped = useMemo(() => {
    const map: Record<string, PatternDetection[]> = {}
    for (const row of rows) {
      const key = family(row)
      map[key] = map[key] ? [...map[key], row] : [row]
    }
    return map
  }, [rows])

  const historyRows = useMemo(() => {
    const all = history?.detections ?? []
    return historyPattern === 'TOUS' ? all : all.filter((row) => row.pattern === historyPattern)
  }, [history, historyPattern])

  const historyPatterns = useMemo(
    () => Array.from(new Set((history?.detections ?? []).map((row) => row.pattern))).sort(),
    [history],
  )

  const confluenceGroups = confluence?.groups ?? []

  return (
    <section className="card" aria-label="SMC ICT" data-testid="smc-ict-panel">
      <header className="card-head">
        <h2>
          SMC / ICT <span className="muted">Phase 4</span>
        </h2>
        <span className="card-head-note">
          {rows.length} objet(s) suivi(s) · moteur{' '}
          {engines.SMC_ICT_ENGINE ?? structure?.engines?.SMC_ICT_ENGINE ?? '—'}
        </span>
      </header>

      <p className="panel-note" data-testid="smc-disclaimer">
        Structure, déséquilibres, blocs d’ordres et liquidité sont mesurés sur bougies clôturées.
        La liquidité est une <strong>estimation géométrique</strong> : le moteur ne voit aucun carnet
        d’ordres et ne prétend pas le connaître. Aucun signal, aucune instruction de trading.
      </p>

      <div className="detection-block" data-testid="smc-engine-block">
        <h3>MOTEUR</h3>
        <div className="detection-meta">
          <span className="measurement" data-testid="smc-engine-state">
            SMC_ICT_ENGINE : {engines.SMC_ICT_ENGINE ?? 'INCONNU'}
          </span>
          {typeof stats.tracked === 'number' && (
            <span className="measurement">objets suivis : {stats.tracked}</span>
          )}
          {typeof stats.last_run_ms === 'number' && (
            <span className="measurement">dernier run : {stats.last_run_ms} ms</span>
          )}
          {typeof stats.bars_analysed === 'number' && (
            <span className="measurement">bougies analysées : {stats.bars_analysed}</span>
          )}
          {Object.entries(byStatus).map(([state, count]) => (
            <span key={state} className="measurement">
              {STATE_LABEL[state] ?? state} : {count}
            </span>
          ))}
        </div>
        {Object.keys(byPattern).length > 0 && (
          <div className="detection-meta" data-testid="smc-pattern-counts">
            {Object.entries(byPattern).map(([pattern, count]) => (
              <span key={pattern} className="measurement">
                {smcLabel(pattern)} : {count}
              </span>
            ))}
          </div>
        )}
      </div>

      {error && (
        <p className="muted" data-testid="smc-error">
          {error}
        </p>
      )}

      {rows.length === 0 ? (
        <p className="muted" data-testid="smc-no-active">
          AUCUN OBJET SMC / ICT SUIVI SUR CE MARCHÉ
        </p>
      ) : (
        FAMILIES.map((block) => {
          const blockRows = grouped[block.key] ?? []
          if (blockRows.length === 0) return null
          return (
            <div className="detection-block" key={block.key} data-testid={`smc-block-${block.key}`}>
              <h3>
                {block.title} <span className="muted">— {block.note}</span>
              </h3>
              <ul className="detection-list">
                {blockRows.map((detection) => {
                  const state = smcState(detection)
                  const estimate = family(detection) === 'LIQUIDITY'
                  return (
                    <li
                      key={detection.id}
                      className={`detection-row ${selectedId === detection.id ? 'selected' : ''}`}
                      data-testid="smc-row"
                    >
                      <div className="detection-line">
                        <span className="badge badge-smc">SMC</span>
                        <strong>{smcLabel(detection.pattern)}</strong>
                        <span className="muted">
                          {detection.symbol} {detection.timeframe} · {directionLabel(detection.direction)} ·{' '}
                          {formatBarTime(detection.detected_at_bar_time)} · {measuredPrice(detection)}
                        </span>
                        <span className="confidence" data-testid="smc-criteria">
                          {passedCriteria(detection)} / {detection.confidence_factors.length} critères ·{' '}
                          {Math.round(detection.confidence)}%
                        </span>
                        <span className="badge badge-smc-state" data-testid="smc-status">
                          {STATE_LABEL[state ?? detection.status] ?? statusLabel(detection.status)}
                        </span>
                        {estimate && (
                          <span className="badge badge-estimate" data-testid="smc-estimate">
                            ESTIMATION
                          </span>
                        )}
                        <button
                          type="button"
                          className="ghost-button small"
                          onClick={() => onSelect(detection)}
                          data-testid="smc-show-chart"
                        >
                          VOIR SUR LE GRAPHIQUE
                        </button>
                        <button
                          type="button"
                          className="ghost-button small"
                          onClick={() => setOpenId(openId === detection.id ? null : detection.id)}
                          data-testid="smc-toggle-evidence"
                        >
                          {openId === detection.id ? 'MASQUER' : 'POURQUOI'}
                        </button>
                      </div>

                      <div className="detection-meta">
                        {keyMeasurements(detection).map((row) => (
                          <span key={row} className="measurement">
                            {row}
                          </span>
                        ))}
                      </div>

                      {openId === detection.id && (
                        <div className="evidence" data-testid="smc-evidence">
                          <ul>
                            {detection.evidence.map((line) => (
                              <li key={line}>{line}</li>
                            ))}
                          </ul>
                          <h4>Critères (poids et détail)</h4>
                          <ul>
                            {detection.confidence_factors.map((factor) => (
                              <li key={factor.criterion} className={factor.passed ? 'ok' : 'ko'}>
                                {factor.passed ? 'OK' : 'NON'} · {factor.criterion} (poids{' '}
                                {factor.weight}) : {factor.detail}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          )
        })
      )}

      {confluenceGroups.length > 0 && (
        <div className="detection-block" data-testid="smc-confluence-block">
          <h3>
            CONFLUENCE INTERNE (INFORMATIF){' '}
            <span className="muted">— groupes d’objets qui décrivent le même mouvement</span>
          </h3>
          <p className="muted" data-testid="smc-confluence-note">
            Descriptif uniquement : aucune pondération, aucun classement, aucun déclenchement.
          </p>
          <ul className="detection-list">
            {confluenceGroups.slice(0, 3).map((group) => (
              <li
                key={`${group.direction}-${group.from_index}-${group.to_index}`}
                className="detection-row"
                data-testid="smc-confluence-group"
              >
                <div className="detection-line">
                  <span className="badge badge-smc">CONFLUENCE</span>
                  <strong>{directionLabel(group.direction)}</strong>
                  <span className="muted">
                    {group.count} objet(s) · familles {group.families.join(' + ')} ·{' '}
                    {group.span_bars} bougie(s) (barres {group.from_index} → {group.to_index})
                  </span>
                </div>
                <div className="detection-meta">
                  {group.items.slice(0, 6).map((item) => (
                    <span key={`${item.pattern}-${item.index}`} className="measurement">
                      {smcLabel(item.pattern)} @{item.index}
                    </span>
                  ))}
                  {group.items.length > 6 && (
                    <span className="measurement">+{group.items.length - 6} autre(s)</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="detection-block">
        <h3>
          HISTORIQUE SMC / ICT{' '}
          <span className="muted">
            — {historyRows.length} ligne(s) sur {maxOverlays} calque(s) affichables au maximum
          </span>
        </h3>
        {historyError && <p className="muted">{historyError}</p>}
        {!history?.detections?.length ? (
          <p className="muted" data-testid="smc-no-history">
            AUCUN HISTORIQUE SMC / ICT
          </p>
        ) : (
          <>
            <label className="smc-filter">
              Élément
              <select
                value={historyPattern}
                onChange={(event) => setHistoryPattern(event.target.value)}
                data-testid="smc-history-filter"
              >
                <option value="TOUS">TOUS</option>
                {historyPatterns.map((pattern) => (
                  <option key={pattern} value={pattern}>
                    {smcLabel(pattern)}
                  </option>
                ))}
              </select>
            </label>
            <div className="table-scroll">
              <table className="detection-table" data-testid="smc-history-table">
                <thead>
                  <tr>
                    <th>Barre</th>
                    <th>Paire</th>
                    <th>UT</th>
                    <th>Élément</th>
                    <th>Sens</th>
                    <th>Statut</th>
                    <th>Prix</th>
                    <th>Critères</th>
                  </tr>
                </thead>
                <tbody>
                  {historyRows.slice(0, 20).map((detection) => (
                    <tr key={`${detection.id}-hist`}>
                      <td>{formatBarTime(detection.detected_at_bar_time)}</td>
                      <td>{detection.symbol}</td>
                      <td>{detection.timeframe}</td>
                      <td>{smcLabel(detection.pattern)}</td>
                      <td>{directionLabel(detection.direction)}</td>
                      <td>{STATE_LABEL[smcState(detection) ?? detection.status] ?? statusLabel(detection.status)}</td>
                      <td>{measuredPrice(detection)}</td>
                      <td>
                        {passedCriteria(detection)} / {detection.confidence_factors.length}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </section>
  )
}
