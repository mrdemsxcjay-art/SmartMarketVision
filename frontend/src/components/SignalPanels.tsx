/**
 * Phase 5-8 panels: MARKET OVERVIEW, CONFLUENCE, OPPORTUNITY, ALERT HISTORY
 * and TELEGRAM STATUS.
 *
 * Rules of the house, applied here:
 *   * every value comes from a real payload (REST or stream) - nothing is
 *     recomputed client-side, nothing is invented when a field is missing;
 *   * a confluence score is shown as "x/10" and NEVER as a probability of
 *     success; the components that earned each point are listed;
 *   * BUY / SELL are ANALYTICAL directions: the panel says so, and no order,
 *     no stop, no target appears anywhere;
 *   * a NO_TRADE always shows its reason; a WATCH always shows what is missing;
 *   * the Telegram panel shows the mode (NOT_CONFIGURED / DRY_RUN / REAL) and
 *     never a token.
 */
import { useMemo, useState } from 'react'
import { captureFileUrl } from '../api/client'
import type {
  CaptureRow,
  ConfluenceReading,
  ConfluenceListResponse,
  Opportunity,
  OpportunityOverview,
  OpportunitiesResponse,
  TelegramHistoryResponse,
  TelegramStatus,
} from '../types/market'

const DIRECTION_LABEL: Record<string, string> = {
  BUY: '🟢 BUY',
  SELL: '🔴 SELL',
  WATCH: '👀 WATCH',
  NO_TRADE: '⛔ NO_TRADE',
  BULLISH: 'HAUSSIER',
  BEARISH: 'BAISSIER',
  NEUTRAL: 'NEUTRE',
}

const STATE_LABEL: Record<string, string> = {
  NO_CONFLUENCE: 'AUCUNE CONFLUENCE',
  WATCH: 'SURVEILLANCE',
  CONFLUENCE: 'CONFLUENCE',
  STRONG_CONFLUENCE: 'CONFLUENCE FORTE',
  CONTRADICTED: 'CONTRADICTION',
  EXPIRED: 'EXPIRÉE',
  CREATED: 'CRÉÉE',
  ACTIVE: 'ACTIVE',
  CONFIRMED: 'CONFIRMÉE',
  WEAKENED: 'AFFAIBLIE',
  INVALIDATED: 'INVALIDÉE',
  QUEUED: 'EN FILE',
  SENDING: 'ENVOI',
  SENT: 'ENVOYÉE',
  FAILED: 'ÉCHEC',
  RETRYING: 'NOUVELLE TENTATIVE',
  SKIPPED: 'IGNORÉE',
}

export function directionText(value: string): string {
  return DIRECTION_LABEL[value] ?? value
}

export function stateText(value: string): string {
  return STATE_LABEL[value] ?? value
}

function stateClass(value: string): string {
  if (['BUY', 'BULLISH', 'CONFIRMED', 'STRONG_CONFLUENCE', 'SENT'].includes(value)) return 'badge badge-bullish'
  if (['SELL', 'BEARISH', 'CONTRADICTED', 'INVALIDATED', 'FAILED'].includes(value)) return 'badge badge-bearish'
  if (['NO_TRADE', 'WATCH', 'QUEUED', 'RETRYING'].includes(value)) return 'badge badge-neutral'
  return 'badge badge-detected'
}

function formatPrice(value: number | null, digits = 5): string {
  return value === null || value === undefined ? '—' : value.toFixed(digits)
}

function formatTime(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toISOString().slice(0, 16).replace('T', ' ') + ' UTC'
}

/* ------------------------------------------------------------------ overview */

export interface MarketOverviewProps {
  symbol: string
  timeframe: string
  price: number | null
  digits: number
  marketState: string | null
  confluence: ConfluenceReading | null
  overview: OpportunityOverview | null
  onOpenOpportunity?: (opportunityId: string) => void
}

/** The six values of the header: paire, TF, prix, état de marché, confluence, opportunité. */
export function MarketOverview({
  symbol,
  timeframe,
  price,
  digits,
  marketState,
  confluence,
  overview,
}: MarketOverviewProps) {
  const opportunity = overview?.direction ?? 'NO_TRADE'
  return (
    <section className="panel overview-panel" data-testid="market-overview" aria-label="Market overview">
      <div className="overview-grid">
        <div>
          <span className="muted small">PAIRE</span>
          <strong data-testid="overview-symbol">{symbol}</strong>
        </div>
        <div>
          <span className="muted small">TF</span>
          <strong data-testid="overview-timeframe">{timeframe}</strong>
        </div>
        <div>
          <span className="muted small">PRIX</span>
          <strong data-testid="overview-price">{formatPrice(price, digits)}</strong>
        </div>
        <div>
          <span className="muted small">ÉTAT MARCHÉ</span>
          <strong data-testid="overview-market-state">{marketState ?? '—'}</strong>
        </div>
        <div>
          <span className="muted small">CONFLUENCE</span>
          <strong data-testid="overview-confluence">
            {confluence ? `${confluence.score.toFixed(0)}/${confluence.max_score.toFixed(0)}` : '—'}
          </strong>
          <span className="muted small">{confluence ? stateText(confluence.state) : 'AUCUNE'}</span>
        </div>
        <div>
          <span className="muted small">OPPORTUNITÉ</span>
          <strong data-testid="overview-opportunity">{directionText(opportunity)}</strong>
          <span className="muted small">{overview?.state ? stateText(overview.state) : '—'}</span>
        </div>
      </div>
      {overview?.no_trade_reason && (
        <p className="muted small" data-testid="overview-refusal">
          Refus : {overview.no_trade_reason}
        </p>
      )}
    </section>
  )
}

/* ---------------------------------------------------------------- confluence */

export interface ConfluencePanelProps {
  confluence: ConfluenceListResponse | null
  current: ConfluenceReading | null
  error?: string | null
  onSelect?: (group: ConfluenceReading) => void
}

export function ConfluencePanel({ confluence, current, error, onSelect }: ConfluencePanelProps) {
  const rows = confluence?.confluences ?? []
  const group = current ?? rows[0] ?? null

  const timeframes = useMemo(() => {
    const set = new Set<string>()
    group?.components.forEach((component) => component.timeframes.forEach((tf) => set.add(tf)))
    return Array.from(set).sort()
  }, [group])

  return (
    <section className="panel" data-testid="confluence-panel">
      <header className="panel-head">
        <h2>CONFLUENCE</h2>
        <span className="muted small">
          {rows.length} confluence(s) · score explicable, jamais une probabilité
        </span>
      </header>

      {error && (
        <p className="banner banner-warn" data-testid="confluence-error">
          {error}
        </p>
      )}

      {!group && !error && (
        <p className="muted" data-testid="confluence-empty">
          Aucune confluence observée pour cette paire et ce timeframe.
        </p>
      )}

      {group && (
        <div className="confluence-detail" data-testid="confluence-detail">
          <div className="row-between">
            <span className={stateClass(group.direction)}>{directionText(group.direction)}</span>
            <span className={stateClass(group.state)}>{stateText(group.state)}</span>
            <strong data-testid="confluence-score">
              {group.score.toFixed(1)}/{group.max_score.toFixed(0)}
            </strong>
          </div>

          <p className="muted small" data-testid="confluence-id">
            {group.id} · fenêtre {group.window_start} → {group.window_end} · TF {group.timeframe}
            {timeframes.length ? ` · contexte ${timeframes.join(', ')}` : ''}
          </p>

          <ul className="component-list" data-testid="confluence-components">
            {group.components.map((component) => (
              <li key={component.dimension}>
                <span className="badge badge-detected">+{component.points}</span>{' '}
                <strong>{component.label}</strong>{' '}
                <span className="muted small">
                  {component.reason} · {component.timeframes.join(', ')}
                </span>
              </li>
            ))}
            {group.contradictions.map((component) => (
              <li key={`contra-${component.dimension}`}>
                <span className="badge badge-bearish">{component.points}</span>{' '}
                <strong>Contradiction · {component.label}</strong>{' '}
                <span className="muted small">{component.reason}</span>
              </li>
            ))}
          </ul>

          {group.why.length > 0 && (
            <details>
              <summary>POURQUOI ✓ ({group.why.length})</summary>
              <ul>
                {group.why.map((line) => (
                  <li key={line} className="muted small">
                    {line}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {group.against.length > 0 && (
            <details>
              <summary>CONTRE ✗ ({group.against.length})</summary>
              <ul>
                {group.against.map((line) => (
                  <li key={line} className="muted small">
                    {line}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {rows.length > 1 && (
        <ul className="signal-list" data-testid="confluence-list">
          {rows.map((row) => (
            <li key={row.id}>
              <button
                type="button"
                className={`signal-row ${row.id === group?.id ? 'signal-row-active' : ''}`}
                onClick={() => onSelect?.(row)}
              >
                <span className={stateClass(row.state)}>{stateText(row.state)}</span>
                <span>{directionText(row.direction)}</span>
                <span className="muted small">
                  {row.score.toFixed(1)}/{row.max_score.toFixed(0)} · {row.timeframe}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/* --------------------------------------------------------------- opportunity */

export interface OpportunityPanelProps {
  opportunities: OpportunitiesResponse | null
  overview: OpportunityOverview | null
  error?: string | null
  onSelect?: (opportunity: Opportunity) => void
}

export function OpportunityPanel({ opportunities, overview, error, onSelect }: OpportunityPanelProps) {
  const rows = opportunities?.opportunities ?? []
  const primary =
    rows.find((row) => row.id === overview?.opportunity_id) ?? rows[0] ?? null

  return (
    <section className="panel" data-testid="opportunity-panel">
      <header className="panel-head">
        <h2>OPPORTUNITÉ</h2>
        <span className="muted small">
          Direction analytique observée · aucun ordre, aucun broker
        </span>
      </header>

      {error && (
        <p className="banner banner-warn" data-testid="opportunity-error">
          {error}
        </p>
      )}

      {!primary && !error && (
        <p className="muted" data-testid="opportunity-empty">
          Aucune opportunité observée : c'est un résultat en soi, pas un manque de données.
        </p>
      )}

      {primary && (
        <div data-testid="opportunity-detail">
          <div className="row-between">
            <span className={stateClass(primary.direction)} data-testid="opportunity-direction">
              {directionText(primary.direction)}
            </span>
            <span className={stateClass(primary.state)}>{stateText(primary.state)}</span>
            <strong data-testid="opportunity-score">
              {primary.score.toFixed(1)}/{primary.max_score.toFixed(0)}
            </strong>
          </div>

          <dl className="kv">
            <div>
              <dt>Prix de référence</dt>
              <dd>{formatPrice(primary.reference_price)}</dd>
            </div>
            <div>
              <dt>Validité</dt>
              <dd>{formatTime(primary.expires_at)}</dd>
            </div>
            <div>
              <dt>Confluence</dt>
              <dd>{primary.confluence_id ?? '—'}</dd>
            </div>
            <div>
              <dt>Observation</dt>
              <dd>{primary.id}</dd>
            </div>
          </dl>

          {primary.no_trade_reason && (
            <p className="banner banner-warn small" data-testid="opportunity-reason">
              NO_TRADE motivé : {primary.no_trade_reason}
            </p>
          )}
          {!primary.no_trade_reason && primary.blocked_by && (
            <p className="muted small" data-testid="opportunity-blocked">
              Direction non nommée : {primary.blocked_by}
            </p>
          )}

          <ul className="condition-list" data-testid="opportunity-conditions">
            {primary.conditions.map((condition) => (
              <li key={condition.label} className={condition.passed ? 'condition-ok' : 'condition-ko'}>
                <span aria-hidden="true">{condition.passed ? '✓' : '✗'}</span>{' '}
                <strong>{condition.label}</strong>
                {condition.gate ? <span className="muted small"> (critère bloquant)</span> : null}
                {!condition.gate && condition.passed ? (
                  <span className="muted small"> +{condition.points}</span>
                ) : null}
                <div className="muted small">{condition.detail}</div>
              </li>
            ))}
          </ul>

          {primary.watch_levels.length > 0 && (
            <details>
              <summary>NIVEAUX OBSERVÉS ({primary.watch_levels.length})</summary>
              <ul>
                {primary.watch_levels.map((level) => (
                  <li key={`${level.label}-${level.price}`} className="muted small">
                    {level.label} · {formatPrice(level.price)} · {level.kind}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {rows.length > 1 && (
        <ul className="signal-list" data-testid="opportunity-list">
          {rows.map((row) => (
            <li key={row.id}>
              <button
                type="button"
                className={`signal-row ${row.id === primary?.id ? 'signal-row-active' : ''}`}
                onClick={() => onSelect?.(row)}
              >
                <span className={stateClass(row.direction)}>{directionText(row.direction)}</span>
                <span className={stateClass(row.state)}>{stateText(row.state)}</span>
                <span className="muted small">
                  {row.score.toFixed(1)}/{row.max_score.toFixed(0)} · {row.timeframe}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/* ------------------------------------------------------------------- alerts */

export interface AlertsPanelProps {
  telegram: TelegramStatus | null
  history: TelegramHistoryResponse | null
  captures: CaptureRow[]
  /** Pair shown by the dashboard: its captures come first, the others follow. */
  symbol?: string
  error?: string | null
}

export function AlertsPanel({ telegram, history, captures, symbol, error }: AlertsPanelProps) {
  const [openCapture, setOpenCapture] = useState<string | null>(null)
  const alerts = history?.alerts ?? []
  // The gallery is evidence of the whole chain, not a filter: the captures of the
  // displayed pair come first, the recent ones of the other pairs stay visible
  // (each row carries its own symbol, so nothing can be mistaken for the current one).
  const gallery = useMemo(
    () =>
      [...captures].sort((left, right) => {
        const leftCurrent = left.symbol === symbol ? 0 : 1
        const rightCurrent = right.symbol === symbol ? 0 : 1
        if (leftCurrent !== rightCurrent) return leftCurrent - rightCurrent
        return (right.timestamp ?? '').localeCompare(left.timestamp ?? '')
      }),
    [captures, symbol],
  )

  return (
    <section className="panel" data-testid="alerts-panel">
      <header className="panel-head">
        <h2>ALERTES & TELEGRAM</h2>
        <span className={telegram ? stateClass(telegram.mode) : 'badge badge-neutral'} data-testid="telegram-mode">
          {telegram?.mode ?? '—'}
        </span>
      </header>

      {error && (
        <p className="banner banner-warn" data-testid="alerts-error">
          {error}
        </p>
      )}

      {telegram && (
        <div className="telegram-status" data-testid="telegram-status">
          <dl className="kv">
            <div>
              <dt>File</dt>
              <dd data-testid="telegram-queue">
                {Object.entries(telegram.queue ?? {})
                  .map(([key, value]) => `${key} ${value}`)
                  .join(' · ')}
              </dd>
            </div>
            <div>
              <dt>Dispatcher</dt>
              <dd>{telegram.dispatcher.running ? 'ACTIF' : 'ARRÊTÉ'}</dd>
            </div>
            <div>
              <dt>Jeton</dt>
              <dd>{telegram.notifier.bot_token_present ? telegram.notifier.bot_token_preview : 'NON CONFIGURÉ'}</dd>
            </div>
            <div>
              <dt>Dernier envoi</dt>
              <dd>{formatTime(telegram.dispatcher.last_sent_at)}</dd>
            </div>
          </dl>
          <p className="muted small" data-testid="telegram-note">
            {telegram.note}
          </p>
        </div>
      )}

      {alerts.length === 0 ? (
        <p className="muted" data-testid="alerts-empty">
          Aucune alerte enregistrée. Nothing is invented to fill this list.
        </p>
      ) : (
        <ul className="alert-list" data-testid="alert-history">
          {alerts.map((alert) => (
            <li key={alert.id} data-testid="alert-row">
              <div className="row-between">
                <span className={stateClass(alert.status)}>{stateText(alert.status)}</span>
                <span className="muted small">
                  {alert.symbol ?? '—'} {alert.timeframe ?? ''} · {alert.event_type ?? ''}
                </span>
                <span className="muted small">{formatTime(alert.created_at)}</span>
              </div>
              <div className="muted small">
                opportunité {alert.opportunity_id ?? '—'} · tentatives {alert.attempts}/{alert.max_attempts}
                {alert.mode ? ` · mode ${alert.mode}` : ''}
                {alert.capture_id ? ` · capture ${alert.capture_id}` : ''}
              </div>
              {alert.last_error && (
                <div className="muted small" data-testid="alert-error">
                  {alert.last_error}
                </div>
              )}
              {alert.capture_id && (
                <button
                  type="button"
                  className="ghost-button small"
                  onClick={() => setOpenCapture(openCapture === alert.capture_id ? null : alert.capture_id)}
                >
                  {openCapture === alert.capture_id ? 'MASQUER LA CAPTURE' : 'VOIR LA CAPTURE'}
                </button>
              )}
              {alert.capture_id && openCapture === alert.capture_id && (
                <a
                  className="capture-link"
                  href={captureFileUrl(alert.capture_id, 'phone')}
                  target="_blank"
                  rel="noreferrer"
                >
                  <img
                    className="capture-thumb"
                    src={captureFileUrl(alert.capture_id, 'telegram')}
                    alt={`Capture ${alert.capture_id}`}
                    loading="lazy"
                  />
                </a>
              )}
            </li>
          ))}
        </ul>
      )}

      {gallery.length > 0 && (
        <div data-testid="capture-gallery">
          <p className="muted small" data-testid="capture-count">
            {gallery.length} capture(s) réelle(s) : PNG rendu depuis les chandeliers réellement
            reçus (aucune image de substitution).
          </p>
          <ul className="capture-grid">
            {gallery.slice(0, 6).map((row) => (
              <li key={row.id}>
                <a
                  className="capture-link"
                  href={captureFileUrl(row.id, 'phone')}
                  target="_blank"
                  rel="noreferrer"
                >
                  <img
                    className="capture-thumb"
                    src={captureFileUrl(row.id, 'telegram')}
                    alt={`Capture ${row.symbol} ${row.timeframe} ${row.id}`}
                    loading="lazy"
                  />
                </a>
                <span className="muted small capture-caption">
                  {row.symbol} {row.timeframe} · {row.width}×{row.height} ·{' '}
                  {row.overlays?.items?.length ?? 0} overlay(s)
                  <br />
                  {row.id}
                  {row.opportunity_id ? ` · ${row.opportunity_id}` : ''}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

/** Small helper used by the tests to assert the direction vocabulary. */
export function isActionableDirection(direction: string): boolean {
  return direction === 'BUY' || direction === 'SELL'
}
