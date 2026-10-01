/**
 * Phase 4 - SMC / ICT frontend tests (sections 18, 19, 23, 28).
 *
 * Two levels:
 *   * the panel alone, fed with payloads shaped exactly like the ones the real
 *     engine serves (same keys as /api/smc-ict);
 *   * the whole dashboard, to prove the panel appears without a reload when the
 *     engine publishes SMC_* events, and that a selected object is drawn on the
 *     chart.
 *
 * The fixtures below are payload copies of the live API response, never a made
 * up "pretty" example: the heavy geometry (levels, zones, criteria) is the one
 * the engine really produced on EURUSD M15.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { SmcIctPanel } from '../components/SmcIctPanel'
import type {
  DetectionHistoryResponse,
  DetectionsResponse,
  PatternDetection,
} from '../types/market'

// --------------------------------------------------------------- fixtures
function bosDetection(overrides: Record<string, unknown> = {}): PatternDetection {
  return {
    id: 'smc_1a2b3c4d5e6f7081',
    dedup_key: 'smc_1a2b3c4d5e6f7081',
    symbol: 'EURUSD',
    timeframe: 'M15',
    timestamp: '2026-09-30T10:00:00+00:00',
    category: 'SMC_ICT',
    pattern: 'BOS',
    direction: 'BULLISH',
    status: 'CONFIRMED',
    confidence: 81.2,
    source_engine: 'SMC_ICT_ENGINE',
    confidence_factors: [
      { criterion: 'Cassure confirmée par une clôture', passed: true, weight: 3, detail: 'clôture 11.64 pip au-delà du niveau' },
      { criterion: 'Force du pivot cassé', passed: true, weight: 2, detail: 'force 8' },
      { criterion: 'Fraîcheur de la cassure', passed: true, weight: 2, detail: '10 bougie(s) depuis le pivot' },
      { criterion: 'Déplacement mesuré après la cassure', passed: false, weight: 1, detail: 'pas de déplacement qualifié' },
    ],
    evidence: [
      'SWING_HIGH #288 à 1.13662 (force 8, confirmé en bougie 290)',
      'Bougie 298 : O 1.13649 H 1.13817 L 1.13649 C 1.13779',
      'Clôture 1.13779 vs niveau 1.13662 (11.64 pip), cassure retenue : CLOSE',
    ],
    evidence_points: {
      family: 'STRUCTURE',
      criteria: [{ criterion: 'Cassure confirmée par une clôture', passed: true, detail: 'clôture au-delà du niveau' }],
      measurements: {
        swing_index: 288,
        swing_price: 1.13662,
        swing_strength: 8,
        close_excess_pips: 11.64,
        close_excess_atr: 2.511,
        threshold_pips: 1.0,
      },
      levels: { BROKEN_SWING: 1.13662, BREAK_CLOSE: 1.13779 },
      estimate: false,
      source_index: 298,
      parameters_version: 'abc12345',
    },
    coordinates: [{ time: 1790771400, price: 1.1377859116, role: 'BREAK', label: 'BOS close' }],
    drawing: {
      levels: [
        { price: 1.13662, label: 'BROKEN_SWING', kind: 'BOS' },
        { price: 1.13779, label: 'BREAK_CLOSE', kind: 'BOS' },
      ],
      lines: [],
      zones: [{ time_start: 1790762400, time_end: 1790771400, price_top: 1.13779, price_bottom: 1.13662, label: 'BOS', kind: 'BOS' }],
      markers: [{ time: 1790771400, price: 1.13779, position: 'aboveBar', shape: 'arrowUp', label: 'BOS', kind: 'HIGH' }],
      label_text: 'BOS',
      label_time: 1790771400,
    },
    parameters: { family: 'STRUCTURE', state: 'CONFIRMED', engine: { scan_bars: 12 } },
    confirmation: { confirmed: true, level: 1.13662, level_type: 'SWING_HIGH', breakout_time: 1790771400, breakout_price: 1.13779, breakout_candle_time: 1790771400, candles_to_confirm: 0, volume: null, note: 'cassure par clôture' },
    invalidation: { invalidated: false, level: 1.13662, level_type: 'SWING_HIGH', reason: 'aucune invalidation', invalidated_at: null },
    breakout: null,
    retest: null,
    watch_levels: [{ level_type: 'SWING_HIGH', price: 1.13662, direction: 'BULLISH' }],
    parent_detection_id: null,
    detected_at_bar_time: 1790771400,
    first_seen_at: '2026-09-30T10:00:00+00:00',
    last_updated_at: '2026-09-30T10:00:00+00:00',
    bars_in_window: 299,
    notes: ['Famille STRUCTURE - état CONFIRMED', 'SMC/ICT : objet descriptif, jamais une instruction de trading'],
    ...overrides,
  } as PatternDetection
}

const POOL = {
  id: 'smc_2b3c4d5e6f708192',
  dedup_key: 'smc_2b3c4d5e6f708192',
  symbol: 'EURUSD',
  timeframe: 'M15',
  timestamp: '2026-09-30T10:00:00+00:00',
  category: 'SMC_ICT',
  pattern: 'LIQUIDITY_POOL_ESTIMATE',
  direction: 'NEUTRAL',
  status: 'ACTIVE',
  confidence: 100,
  source_engine: 'SMC_ICT_ENGINE',
  confidence_factors: [
    { criterion: 'Niveau non consommé par le marché', passed: true, weight: 2, detail: 'aucune clôture au-delà' },
    { criterion: 'Nombre de contacts mesurés', passed: true, weight: 1, detail: '2 contact(s)' },
  ],
  evidence: [
    'Zone de liquidité estimée autour de 1.13462 (EQUAL_LOW, côté BELOW)',
    "ESTIMATION : le moteur déduit une zone probable, il n'observe aucun ordre réel",
  ],
  evidence_points: {
    family: 'LIQUIDITY',
    measurements: { estimate: true, method: 'EQUAL_LOW', touch_count: 2, age_bars: 20, score: 4.0 },
    levels: { POOL_LEVEL: 1.13462 },
    estimate: true,
  },
  coordinates: [{ time: 1790754300, price: 1.1345586777, role: 'POOL', label: 'liquidity pool estimate' }],
  drawing: {
    levels: [{ price: 1.13462, label: 'POOL_LEVEL', kind: 'LIQUIDITY_POOL_ESTIMATE' }],
    lines: [],
    zones: [{ time_start: 1790667000, time_end: 1790772300, price_top: 1.13492, price_bottom: 1.13432, label: 'LIQUIDITY_POOL_ESTIMATE', kind: 'LIQUIDITY_POOL_ESTIMATE' }],
    markers: [{ time: 1790754300, price: 1.13462, position: 'belowBar', shape: 'circle', label: 'POOL', kind: 'LOW' }],
    label_text: 'POOL',
    label_time: 1790754300,
  },
  parameters: { family: 'LIQUIDITY', state: 'ACTIVE' },
  confirmation: { confirmed: false, level: null, level_type: null, breakout_time: null, breakout_price: null, breakout_candle_time: null, candles_to_confirm: null, volume: null, note: '' },
  invalidation: { invalidated: false, level: null, level_type: null, reason: '', invalidated_at: null },
  breakout: null,
  retest: null,
  watch_levels: [],
  parent_detection_id: null,
  detected_at_bar_time: 1790754300,
  first_seen_at: '2026-09-30T10:00:00+00:00',
  last_updated_at: '2026-09-30T10:00:00+00:00',
  bars_in_window: 299,
  notes: ['Famille LIQUIDITY - état ACTIVE'],
} as unknown as PatternDetection

const FVG = {
  ...POOL,
  id: 'smc_3c4d5e6f708192a3',
  dedup_key: 'smc_3c4d5e6f708192a3',
  pattern: 'BULLISH_FVG',
  direction: 'BULLISH',
  status: 'DETECTED',
  confidence: 100,
  evidence: [
    'FVG BULLISH formé en bougie 299 : bande 1.13649 - 1.13662 (1.29 pip)',
    'Mitigation : CREATED - couverture 0.0%, traversée complète : False',
  ],
  evidence_points: {
    family: 'GAPS',
    measurements: { size_pips: 1.29, size_atr: 0.2785, state: 'CREATED', coverage_share: 0.0 },
    levels: { UPPER_PRICE: 1.13662, LOWER_PRICE: 1.13649, SIZE: 0.0001291 },
    estimate: false,
  },
  coordinates: [{ time: 1790772300, price: 1.1365574002, role: 'CANDLE_2', label: 'fvg candle 2' }],
  drawing: {
    levels: [
      { price: 1.13662, label: 'UPPER_PRICE', kind: 'BULLISH_FVG' },
      { price: 1.13649, label: 'LOWER_PRICE', kind: 'BULLISH_FVG' },
    ],
    lines: [],
    zones: [{ time_start: 1790770500, time_end: 1790772300, price_top: 1.13662, price_bottom: 1.13649, label: 'BULLISH_FVG', kind: 'BULLISH_FVG' }],
    markers: [{ time: 1790772300, price: 1.13656, position: 'belowBar', shape: 'square', label: 'FVG', kind: 'LOW' }],
    label_text: 'FVG',
    label_time: 1790772300,
  },
  parameters: { family: 'GAPS', state: 'CREATED' },
} as unknown as PatternDetection

const DISCOUNT = {
  ...POOL,
  id: 'smc_4d5e6f708192a3b4',
  dedup_key: 'smc_4d5e6f708192a3b4',
  pattern: 'DISCOUNT',
  direction: 'NEUTRAL',
  status: 'ACTIVE',
  evidence: ['Prix en zone DISCOUNT du range de travail : position 19.2%'],
  evidence_points: {
    family: 'RANGE',
    measurements: { position: 0.192, zone: 'DISCOUNT', premium_zone: 0.75, discount_zone: 0.25 },
    levels: { RANGE_HIGH: 1.13662, RANGE_LOW: 1.13314, EQUILIBRIUM: 1.13488, POSITION: 0.192 },
    estimate: false,
  },
  coordinates: [{ time: 1790772300, price: 1.13403, role: 'DISCOUNT', label: 'DISCOUNT position' }],
} as unknown as PatternDetection

function detectionsResponse(rows: PatternDetection[]): DetectionsResponse {
  return {
    status: rows.length ? 'ACTIVE SMC ICT' : 'NO ACTIVE SMC ICT',
    detections: rows,
    counts: {},
    engines: { SMC_ICT_ENGINE: 'ENABLED' },
    stats: {
      tracked: rows.length,
      by_status: { ACTIVE: rows.filter((r) => r.status === 'ACTIVE').length, CONFIRMED: 1, DETECTED: 1 },
      by_pattern: { BOS: 1, LIQUIDITY_POOL_ESTIMATE: 1, BULLISH_FVG: 1 },
      last_run_ms: 148.4,
      bars_analysed: 299,
    },
  }
}

const HISTORY: DetectionHistoryResponse = {
  count: 2,
  status_filter: null,
  detections: [bosDetection(), POOL],
}

function renderPanel(rows: PatternDetection[] = [bosDetection(), POOL, FVG, DISCOUNT]) {
  const onSelect = vi.fn()
  render(
    <SmcIctPanel
      detections={detectionsResponse(rows)}
      structure={detectionsResponse(rows.filter((row) => row.evidence_points?.family === 'STRUCTURE'))}
      history={HISTORY}
      confluence={null}
      selectedId={null}
      onSelect={onSelect}
      historyError={null}
      maxOverlays={3}
    />,
  )
  return { onSelect }
}

// ---------------------------------------------------------------- the panel
describe('SMC / ICT panel', () => {
  it('shows the engine state and the estimate disclaimer', () => {
    renderPanel()
    expect(screen.getByTestId('smc-engine-state')).toHaveTextContent('SMC_ICT_ENGINE : ENABLED')
    const disclaimer = screen.getByTestId('smc-disclaimer')
    expect(disclaimer).toHaveTextContent('estimation géométrique')
    expect(disclaimer).toHaveTextContent("ne voit aucun carnet d’ordres")
  })

  it('groups the objects by family', () => {
    renderPanel()
    for (const family of ['STRUCTURE', 'LIQUIDITY', 'GAPS', 'RANGE']) {
      expect(screen.getByTestId(`smc-block-${family}`)).toBeInTheDocument()
    }
  })

  it('renders element, direction, status, price, bar time and criteria for each row', () => {
    renderPanel()
    const rows = screen.getAllByTestId('smc-row')
    expect(rows).toHaveLength(4)
    const bos = screen.getByTestId('smc-block-STRUCTURE')
    expect(within(bos).getByText('Cassure de structure (BOS)')).toBeInTheDocument()
    expect(within(bos).getByText(/HAUSSIER/)).toBeInTheDocument()
    expect(within(bos).getByTestId('smc-criteria')).toHaveTextContent('3 / 4 critères · 81%')
    // the price comes from a real coordinate of the payload
    expect(within(bos).getByText(/1,13779/)).toBeInTheDocument()
    expect(within(bos).getByTestId('smc-status')).toHaveTextContent('CONFIRMÉ')
  })

  it('marks liquidity objects as estimates and never as facts', () => {
    renderPanel()
    const liquidity = screen.getByTestId('smc-block-LIQUIDITY')
    expect(within(liquidity).getByTestId('smc-estimate')).toHaveTextContent('ESTIMATION')
    expect(within(liquidity).getByText(/Zone de liquidité \(estimation\)/)).toBeInTheDocument()
    // the other families are not marked as estimates
    expect(within(screen.getByTestId('smc-block-STRUCTURE')).queryByTestId('smc-estimate')).toBeNull()
  })

  it('explains WHY a detection exists: evidence and weighted criteria', async () => {
    const user = userEvent.setup()
    renderPanel()
    const bos = screen.getByTestId('smc-block-STRUCTURE')
    await user.click(within(bos).getByTestId('smc-toggle-evidence'))
    const evidence = within(bos).getByTestId('smc-evidence')
    expect(evidence).toHaveTextContent('SWING_HIGH #288 à 1.13662')
    expect(evidence).toHaveTextContent('OK · Cassure confirmée par une clôture (poids 3)')
    expect(evidence).toHaveTextContent('NON · Déplacement mesuré après la cassure (poids 1)')
  })

  it('exposes the FVG lifecycle state and the measured band', () => {
    renderPanel()
    const gaps = screen.getByTestId('smc-block-GAPS')
    expect(within(gaps).getByTestId('smc-status')).toHaveTextContent('CRÉÉ')
    expect(within(gaps).getByText(/size pips : 1.29/)).toBeInTheDocument()
    expect(within(gaps).getByText(/coverage share : 0/)).toBeInTheDocument()
  })

  it('draws the selected object on the chart when asked', async () => {
    const user = userEvent.setup()
    const { onSelect } = renderPanel()
    const gaps = screen.getByTestId('smc-block-GAPS')
    await user.click(within(gaps).getByTestId('smc-show-chart'))
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0][0].pattern).toBe('BULLISH_FVG')
  })

  it('says "no object" only when the engine really returned nothing', () => {
    renderPanel([])
    expect(screen.getByTestId('smc-no-active')).toHaveTextContent('AUCUN OBJET SMC / ICT SUIVI')
    expect(screen.queryByTestId('smc-row')).toBeNull()
  })

  it('distinguishes an unreachable engine from an empty result', () => {
    render(
      <SmcIctPanel
        detections={null}
        structure={null}
        history={null}
        confluence={null}
        selectedId={null}
        onSelect={vi.fn()}
        historyError={null}
        error="SMC_ICT_UNAVAILABLE: engine unreachable"
        maxOverlays={3}
      />,
    )
    expect(screen.getByTestId('smc-error')).toHaveTextContent('SMC_ICT_UNAVAILABLE')
  })

  it('filters the history by element without inventing rows', async () => {
    const user = userEvent.setup()
    renderPanel()
    const table = screen.getByTestId('smc-history-table')
    expect(within(table).getAllByRole('row')).toHaveLength(3) // header + 2 rows
    await user.selectOptions(screen.getByTestId('smc-history-filter'), 'LIQUIDITY_POOL_ESTIMATE')
    const filtered = screen.getByTestId('smc-history-table')
    expect(within(filtered).getAllByRole('row')).toHaveLength(2)
    expect(within(filtered).getByText('Zone de liquidité (estimation)')).toBeInTheDocument()
  })

  it('renders the internal confluence with its real shape (regression)', () => {
    // the SMC confluence is NOT the price-action one: groups carry a direction,
    // families and items - rendering it with the price-action shape crashed the
    // dashboard (read of `groups` of undefined). This locks the real contract.
    render(
      <SmcIctPanel
        detections={detectionsResponse([bosDetection(), POOL, FVG])}
        structure={detectionsResponse([bosDetection()])}
        history={HISTORY}
        confluence={{
          count: 1,
          groups: [
            {
              direction: 'BULLISH',
              from_index: 271,
              to_index: 298,
              span_bars: 27,
              families: ['BLOCKS', 'GAPS', 'RANGE', 'STRUCTURE'],
              count: 9,
              items: [
                { pattern: 'BULLISH_FVG', index: 271, family: 'GAPS', levels: {} },
                { pattern: 'BOS', index: 298, family: 'STRUCTURE', levels: {} },
              ],
            },
          ],
          trading_signal: false,
          note: 'Confluence descriptive',
        }}
        selectedId={null}
        onSelect={vi.fn()}
        historyError={null}
        maxOverlays={3}
      />,
    )
    const block = screen.getByTestId('smc-confluence-block')
    expect(block).toHaveTextContent('9 objet(s)')
    expect(block).toHaveTextContent('BLOCKS + GAPS + RANGE + STRUCTURE')
    expect(block).toHaveTextContent('27 bougie(s)')
    expect(block).toHaveTextContent('FVG haussier @271')
    expect(screen.getByTestId('smc-confluence-note')).toHaveTextContent('aucune pondération')
  })

  it('never displays a trading instruction', () => {
    renderPanel()
    const text = screen.getByTestId('smc-ict-panel').textContent ?? ''
    expect(text).not.toMatch(/\bBUY\b|\bSELL\b|\bACHAT\b|\bVENTE\b|\bSTOP\b|\bENTRY\b|\bTP\b/)
  })
})

// ------------------------------------------------------- dashboard wiring
const SYMBOLS = {
  provider: 'yahoo',
  count: 1,
  timeframes: ['M15', 'H1'],
  default_timeframe: 'M15',
  symbols: [
    { symbol: 'EURUSD', description: 'Euro / US Dollar', base: 'EUR', quote: 'USD', digits: 5, pip_size: 0.0001, asset_class: 'FOREX', provider_symbol: 'EURUSD=X', enabled: true },
  ],
}

function candles(count = 20) {
  const now = Math.floor(Date.now() / 900000) * 900
  return Array.from({ length: count }, (_, index) => {
    const close = 1.1 + index * 0.0002
    return {
      time: now - (count - index) * 900,
      open: close - 0.0001,
      high: close + 0.0002,
      low: close - 0.0002,
      close,
      volume: 100,
      closed: index < count - 1,
      iso: new Date((now - (count - index) * 900) * 1000).toISOString(),
    }
  })
}

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  url: string
  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }
  close() {
    this.readyState = 3
    this.onclose?.()
  }
  emitMessage(payload: unknown) {
    this.readyState = 1
    this.onmessage?.({ data: JSON.stringify(payload) })
  }
}

function mockFetch(rows: PatternDetection[]) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
    if (url.includes('/api/smc-ict/history'))
      return json({ count: rows.length, status_filter: null, detections: rows })
    if (url.includes('/api/smc-ict/confluence'))
      return json({ count: 0, groups: [], trading_signal: false, note: 'informatif' })
    if (url.includes('/api/smc-ict/structure'))
      return json({
        status: 'SMC STRUCTURE',
        detections: rows.filter((row) => row.evidence_points?.family === 'STRUCTURE'),
        counts: {},
        engines: { SMC_ICT_ENGINE: 'ENABLED' },
      })
    if (url.includes('/api/smc-ict')) return json(detectionsResponse(rows))
    if (url.includes('/api/price-action/history')) return json({ count: 0, status_filter: null, detections: [] })
    if (url.includes('/api/price-action/confluence'))
      return json({ count: 0, groups: [], trading_signal: false, note: 'informatif' })
    if (url.includes('/api/price-action'))
      return json({ status: 'NO ACTIVE PRICE ACTION', detections: [], counts: {}, engines: { PRICE_ACTION_ENGINE: 'ENABLED' } })
    if (url.includes('/api/detections/history')) return json({ count: 0, status_filter: null, detections: [] })
    if (url.includes('/api/detections'))
      return json({ status: 'NO ACTIVE DETECTION', detections: [], counts: {}, engines: { CHART_PATTERN_ENGINE: 'ENABLED' } })
    if (url.includes('/api/symbols')) return json(SYMBOLS)
    if (url.includes('/api/status'))
      return json({
        status: 'ok',
        server_time_utc: new Date().toISOString(),
        app_env: 'test',
        provider: 'yahoo',
        provider_health: { provider: 'yahoo', reachable: true, consecutive_failures: 0 },
        watchlist_size: 1,
        watchlist: ['EURUSD'],
        timeframes: ['M15', 'H1'],
        scanner: { running: true, ticks: 1, interval_seconds: 15, last_tick_at: null, last_tick_duration_ms: 1, pairs_scanned_last_tick: 1, pairs_failed_last_tick: 0, errors: [], default_timeframe: 'M15' },
        market: { phase: 'OPEN', is_open: true, active_sessions: ['LONDON'], reference_time_utc: new Date().toISOString(), next_open_utc: null, next_close_utc: null, note: null },
        stream: { websocket_endpoint: '/api/stream', sse_endpoint: '/api/events', subscribers: 1, events_published: 1 },
        database: { backend: 'sqlite', candles_stored: 1, events_stored: 1, detections_stored: 1, retention_days: 120 },
        telegram: { status: 'NOT_CONFIGURED', bot_token_present: false, bot_token_preview: 'NOT_SET', chat_id_present: false, chat_id_preview: 'NOT_SET', capabilities: [] },
        capture: { implemented: false, enabled: false, status: 'CAPTURE_NOT_IMPLEMENTED', required_elements: [] },
        detection_engines: { CHART_PATTERN_ENGINE: 'ENABLED', PRICE_ACTION_ENGINE: 'ENABLED', SMC_ICT_ENGINE: 'ENABLED' },
        safety: { order_execution: false, broker_connection: false, position_management: false, note: 'scanner only' },
        config: {},
        cache: { entries: 0, hits: 0, keys: [] },
      })
    if (url.includes('/api/structure'))
      return json({
        symbol: 'EURUSD', timeframe: 'M15', provider: 'yahoo', data_state: 'CONNECTED', trend: 'BULLISH',
        labels: [], recent_labels: [], bars_analyzed: 299, using_closed_candles_only: true, pivot_left: 2,
        pivot_right: 2, swing_count: 10, last_swing_high: null, last_swing_low: null, swings: [], notes: [],
        evaluated_at: new Date().toISOString(),
        smc_ict: { implemented: true, message: 'moteur SMC/ICT Phase 4' },
      })
    if (url.includes('/api/market/'))
      return json({
        symbol: 'EURUSD', timeframe: 'M15', provider: 'yahoo', data_state: 'CONNECTED', price: 1.1342,
        prev_close: 1.134, change: 0.0002, change_percent: 0.02, digits: 5,
        candle_time: new Date().toISOString(), last_update: new Date().toISOString(),
        market: { phase: 'OPEN', is_open: true, active_sessions: ['LONDON'], reference_time_utc: new Date().toISOString(), next_open_utc: null, next_close_utc: null, note: null },
        stale: false, error: null,
      })
    if (url.includes('/api/candles'))
      return json({
        symbol: 'EURUSD', timeframe: 'M15', provider: 'yahoo', data_state: 'CONNECTED', stale: false,
        digits: 5, pip_size: 0.0001, count: 20, fetched_at: new Date().toISOString(),
        quality_warnings: [], candles: candles(),
      })
    return json({}, 404)
  })
}

describe('SMC / ICT on the dashboard', () => {
  beforeEach(() => {
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)
    vi.stubGlobal('fetch', mockFetch([bosDetection(), POOL, FVG]))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders the SMC / ICT panel with the real engine state', async () => {
    render(<App />)
    await waitFor(() => expect(screen.getByTestId('quote-price')).toHaveTextContent('1.13420'))
    const panel = await screen.findByTestId('smc-ict-panel')
    expect(within(panel).getByTestId('smc-engine-state')).toHaveTextContent('ENABLED')
    expect(within(panel).getAllByTestId('smc-row').length).toBe(3)
  })

  it('filters to SMC / ICT only', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitFor(() => expect(screen.getByTestId('quote-price')).toHaveTextContent('1.13420'))
    await user.click(screen.getByTestId('filter-SMC_ICT'))
    expect(screen.getByTestId('smc-ict-panel')).toBeInTheDocument()
    expect(screen.queryByTestId('price-action-panel')).toBeNull()
    expect(screen.queryByText('STRUCTURE DU MARCHÉ')).toBeNull()
  })

  it('fills the panel from an SMC_ICT_SNAPSHOT without reloading', async () => {
    render(<App />)
    await waitFor(() => expect(screen.getByTestId('quote-price')).toHaveTextContent('1.13420'))
    const socket = FakeWebSocket.instances[0]
    socket.emitMessage({
      event_type: 'SMC_ICT_SNAPSHOT',
      symbol: 'EURUSD',
      timeframe: 'M15',
      timestamp: new Date().toISOString(),
      price: 1.1342,
      source: 'SMC_ICT_ENGINE',
      metadata: {
        status: 'ACTIVE SMC ICT',
        detections: [DISCOUNT],
        counts: {},
        engines: { SMC_ICT_ENGINE: 'ENABLED' },
        stats: { tracked: 1 },
        trading_signal: false,
      },
    })
    const panel = await screen.findByTestId('smc-ict-panel')
    await waitFor(() => expect(within(panel).getByText('Zone discount')).toBeInTheDocument())
  })

  it('adds a new object from an SMC_DETECTED event (real time, section 23)', async () => {
    render(<App />)
    await waitFor(() => expect(screen.getByTestId('quote-price')).toHaveTextContent('1.13420'))
    const socket = FakeWebSocket.instances[0]
    socket.emitMessage({
      event_type: 'SMC_DETECTED',
      symbol: 'EURUSD',
      timeframe: 'M15',
      timestamp: new Date().toISOString(),
      price: 1.1342,
      source: 'SMC_ICT_ENGINE',
      metadata: { detection: FVG, trading_signal: false },
    })
    const flash = await screen.findByTestId('pattern-flash')
    expect(flash).toHaveTextContent('SMC_DETECTED · BULLISH_FVG')
    const panel = screen.getByTestId('smc-ict-panel')
    const gaps = within(panel).getByTestId('smc-block-GAPS')
    expect(within(gaps).getByText('FVG haussier')).toBeInTheDocument()
  })

  it('shows the SMC object on the chart when it is selected', async () => {
    const user = userEvent.setup()
    render(<App />)
    await waitFor(() => expect(screen.getByTestId('quote-price')).toHaveTextContent('1.13420'))
    const panel = await screen.findByTestId('smc-ict-panel')
    const structure = within(panel).getByTestId('smc-block-STRUCTURE')
    await user.click(within(structure).getByTestId('smc-show-chart'))
    const banner = await screen.findByTestId('chart-detection-banner')
    expect(banner).toHaveTextContent('SMC / ICT')
    expect(banner).toHaveTextContent('BOS')
    expect(banner).toHaveTextContent(/calque/)
  })
})
