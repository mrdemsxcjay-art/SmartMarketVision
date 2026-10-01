/**
 * CHARTISTE DETECTIONS panel (Phase 2).
 *
 * Three blocks, all fed by real detections only:
 *   * DÉTECTIONS CHARTISTES - active + recent formations, with the number of
 *     validated criteria, the confidence and a [VOIR SUR LE GRAPHIQUE] action;
 *   * MOTIFS ACTIFS - the formations still waiting for their breakout;
 *   * HISTORIQUE - what the engine stored (timestamp, paire, UT, motif, sens, statut).
 *
 * Nothing is computed here: the panel displays the backend payload as-is, so the
 * dashboard can never show a pattern the engine did not detect.
 */
import { useMemo, useState } from 'react'
import type { DetectionHistoryResponse, DetectionsResponse, PatternDetection } from '../types/market'

const STATUS_LABEL: Record<string, string> = {
  DETECTED: 'DÉTECTÉ',
  CONFIRMED: 'CONFIRMÉ',
  INVALIDATED: 'INVALIDÉ',
  EXPIRED: 'EXPIRÉ',
}

const DIRECTION_LABEL: Record<string, string> = {
  BULLISH: 'HAUSSIER',
  BEARISH: 'BAISSIER',
  NEUTRAL: 'NEUTRE',
}

const PATTERN_LABEL: Record<string, string> = {
  DOUBLE_TOP: 'Double sommet',
  DOUBLE_BOTTOM: 'Double creux',
  HEAD_SHOULDERS: 'Épaules-tête-épaules',
  INVERSE_HEAD_SHOULDERS: 'ETE inversée',
  ASCENDING_TRIANGLE: 'Triangle ascendant',
  DESCENDING_TRIANGLE: 'Triangle descendant',
  SYMMETRICAL_TRIANGLE: 'Triangle symétrique',
  RISING_WEDGE: 'Biseau ascendant',
  FALLING_WEDGE: 'Biseau descendant',
  RECTANGLE: 'Rectangle',
  BULL_FLAG: 'Drapeau haussier',
  BEAR_FLAG: 'Drapeau baissier',
  BULL_PENNANT: 'Fanion haussier',
  BEAR_PENNANT: 'Fanion baissier',
  SUPPORT: 'Support',
  RESISTANCE: 'Résistance',
  CHANNEL: 'Canal',
}

export function patternLabel(pattern: string): string {
  return PATTERN_LABEL[pattern] ?? pattern
}

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status
}

export function directionLabel(direction: string): string {
  return DIRECTION_LABEL[direction] ?? direction
}

function passedCriteria(detection: PatternDetection): number {
  return detection.confidence_factors.filter((factor) => factor.passed).length
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

interface Props {
  detections: DetectionsResponse | null
  history: DetectionHistoryResponse | null
  selectedId: string | null
  onSelect: (detection: PatternDetection | null) => void
  historyError?: string | null
}

export function PatternsPanel({ detections, history, selectedId, onSelect, historyError }: Props) {
  const [historyLimit, setHistoryLimit] = useState(20)
  const rows = detections?.detections ?? []
  const active = useMemo(() => rows.filter((item) => item.status === 'DETECTED'), [rows])
  const historyRows = (history?.detections ?? []).slice(0, historyLimit)

  return (
    <section className="card patterns-card" aria-label="Détections chartistes">
      <header className="card-head">
        <h2>Détections chartistes</h2>
        <span className="card-head-note" data-testid="patterns-count">
          {rows.length} détection{rows.length > 1 ? 's' : ''} · {active.length} active
          {active.length > 1 ? 's' : ''}
        </span>
      </header>

      {rows.length === 0 && (
        <div className="detection-empty" data-testid="patterns-empty">
          AUCUNE DÉTECTION CHARTISTE
        </div>
      )}

      {rows.length === 0 && (
        <p className="muted small">
          Le moteur chartiste analyse les bougies clôturées réelles. Aucune figure n’a encore
          satisfait l’ensemble des critères mesurables — rien n’est simulé pour remplir ce panneau.
        </p>
      )}

      <ul className="pattern-list" data-testid="patterns-list">
        {rows.map((detection) => (
          <li
            key={detection.id}
            className={`pattern-row${selectedId === detection.id ? ' selected' : ''}`}
            data-testid={`pattern-${detection.pattern}`}
          >
            <div className="pattern-row-main">
              <strong>{patternLabel(detection.pattern)}</strong>
              <span className={`badge badge-${detection.direction.toLowerCase()}`}>
                {directionLabel(detection.direction)}
              </span>
              <span className={`badge badge-${detection.status.toLowerCase()}`}>
                {statusLabel(detection.status)}
              </span>
            </div>
            <div className="pattern-row-meta">
              <span title="Confiance calculée à partir des critères validés">
                Confiance {Math.round(detection.confidence)}%
              </span>
              <span>
                {passedCriteria(detection)}/{detection.confidence_factors.length} critères validés
              </span>
              <span className="muted">
                {detection.symbol} {detection.timeframe}
              </span>
            </div>
            <div className="confidence-bar" aria-hidden="true">
              <span style={{ width: `${Math.max(2, Math.min(100, detection.confidence))}%` }} />
            </div>
            <button
              type="button"
              className="ghost-button"
              onClick={() => onSelect(selectedId === detection.id ? null : detection)}
              data-testid={`view-${detection.pattern}`}
            >
              {selectedId === detection.id ? 'MASQUER DU GRAPHIQUE' : 'VOIR SUR LE GRAPHIQUE'}
            </button>
          </li>
        ))}
      </ul>

      <h3 className="section-title">Motifs actifs ({active.length})</h3>
      {active.length === 0 ? (
        <p className="muted small" data-testid="active-empty">
          Aucun motif en attente de cassure.
        </p>
      ) : (
        <ul className="active-list" data-testid="active-list">
          {active.map((detection) => (
            <li key={`active-${detection.id}`}>
              <span>{patternLabel(detection.pattern)}</span>
              <span className="muted">
                niveau {detection.watch_levels[0]?.level_type ?? '—'} @{' '}
                {detection.watch_levels[0]?.price?.toFixed(5) ?? '—'}
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3 className="section-title">
        Historique ({history?.count ?? 0})
        <button
          type="button"
          className="ghost-button small"
          onClick={() => setHistoryLimit((value) => (value >= 100 ? 20 : value + 20))}
        >
          {historyLimit >= 100 ? 'RÉDUIRE' : 'VOIR PLUS'}
        </button>
      </h3>
      {historyError && (
        <p className="warning-line small" data-testid="history-error">
          {historyError}
        </p>
      )}
      {(history?.detections ?? []).length === 0 ? (
        <p className="muted small" data-testid="history-empty">
          Aucune détection enregistrée pour le moment.
        </p>
      ) : (
        <div className="table-scroll">
          <table className="history-table" data-testid="history-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Paire</th>
                <th>UT</th>
                <th>Motif</th>
                <th>Sens</th>
                <th>Statut</th>
              </tr>
            </thead>
            <tbody>
              {historyRows.map((row) => (
                <tr key={`hist-${row.id}`}>
                  <td>{formatTime(row.first_seen_at ?? row.timestamp)}</td>
                  <td>{row.symbol}</td>
                  <td>{row.timeframe}</td>
                  <td>{patternLabel(row.pattern)}</td>
                  <td>{directionLabel(row.direction)}</td>
                  <td>{statusLabel(row.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <EngineState engines={detections?.engines ?? {}} stats={detections?.stats} />
    </section>
  )
}

function EngineState({ engines, stats }: { engines: Record<string, string>; stats?: Record<string, unknown> }) {
  return (
    <>
      <ul className="engine-list">
        {Object.entries(engines).map(([engine, state]) => (
          <li key={engine}>
            <span>{engine}</span>
            <span className="muted">{state}</span>
          </li>
        ))}
      </ul>
      {stats && (
        <p className="muted small" data-testid="patterns-stats">
          {String(stats.runs ?? 0)} analyses · {String(stats.bars_analysed ?? 0)} bougies ·{' '}
          {String(stats.persisted ?? 0)} enregistrées
          {stats.last_run_ms ? ` · ${String(stats.last_run_ms)} ms` : ''}
        </p>
      )}
    </>
  )
}
