import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { CandleResponse, Quote, StructureResponse, SymbolListResponse, SystemStatus } from '../types/market'

// --------------------------------------------------------------- fixtures
const SYMBOLS: SymbolListResponse = {
  provider: 'yahoo',
  count: 2,
  timeframes: ['M5', 'M15', 'H1', 'H4', 'D1'],
  default_timeframe: 'M15',
  symbols: [
    { symbol: 'EURUSD', description: 'Euro / US Dollar', base: 'EUR', quote: 'USD', digits: 5, pip_size: 0.0001, asset_class: 'FOREX', provider_symbol: 'EURUSD=X', enabled: true },
    { symbol: 'USDJPY', description: 'US Dollar / Japanese Yen', base: 'USD', quote: 'JPY', digits: 3, pip_size: 0.01, asset_class: 'FOREX', provider_symbol: 'USDJPY=X', enabled: true },
  ],
}

function candles(count = 30, startPrice = 1.1) {
  const now = Math.floor(Date.now() / 900000) * 900
  return Array.from({ length: count }, (_, index) => {
    const close = startPrice + index * 0.0002
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

const CANDLES: CandleResponse = {
  symbol: 'EURUSD',
  timeframe: 'M15',
  provider: 'yahoo',
  data_state: 'CONNECTED',
  stale: false,
  digits: 5,
  pip_size: 0.0001,
  count: 30,
  fetched_at: new Date().toISOString(),
  quality_warnings: ['1 partial bar(s) folded into the running M15 bar'],
  candles: candles(),
}

const QUOTE: Quote = {
  symbol: 'EURUSD',
  timeframe: 'M15',
  provider: 'yahoo',
  data_state: 'CONNECTED',
  price: 1.1342,
  prev_close: 1.134,
  change: 0.0002,
  change_percent: 0.0176,
  digits: 5,
  candle_time: new Date().toISOString(),
  last_update: new Date().toISOString(),
  market: {
    phase: 'OPEN',
    is_open: true,
    active_sessions: ['LONDON'],
    reference_time_utc: new Date().toISOString(),
    next_open_utc: null,
    next_close_utc: null,
    note: null,
  },
  stale: false,
  error: null,
}

const STRUCTURE: StructureResponse = {
  symbol: 'EURUSD',
  timeframe: 'M15',
  provider: 'yahoo',
  data_state: 'CONNECTED',
  trend: 'BULLISH',
  labels: ['H', 'L', 'HH', 'HL', 'HH'],
  recent_labels: ['HH', 'HL', 'HH', 'HL'],
  bars_analyzed: 299,
  using_closed_candles_only: true,
  pivot_left: 2,
  pivot_right: 2,
  swing_count: 42,
  last_swing_high: { index: 10, time: 1, iso: '', price: 1.14, kind: 'HIGH', label: 'HH', confirmed_at_index: 12 },
  last_swing_low: { index: 8, time: 1, iso: '', price: 1.12, kind: 'LOW', label: 'HL', confirmed_at_index: 10 },
  swings: [],
  notes: [],
  evaluated_at: new Date().toISOString(),
  smc_ict: { implemented: true, message: 'BOS / CHOCH / MSS / FVG / Order Blocks / liquidité : moteur SMC/ICT de la Phase 4.' },
}

const STATUS: SystemStatus = {
  status: 'ok',
  server_time_utc: new Date().toISOString(),
  app_env: 'test',
  provider: 'yahoo',
  provider_health: { provider: 'yahoo', reachable: true, last_success_utc: new Date().toISOString(), last_error: null, consecutive_failures: 0, requests_total: 12, requests_failed: 0, average_latency_ms: 120 },
  watchlist_size: 10,
  watchlist: ['EURUSD', 'USDJPY'],
  timeframes: ['M5', 'M15', 'H1', 'H4', 'D1'],
  scanner: { running: true, ticks: 5, interval_seconds: 15, last_tick_at: new Date().toISOString(), last_tick_duration_ms: 800, pairs_scanned_last_tick: 10, pairs_failed_last_tick: 0, errors: [], default_timeframe: 'M15' },
  market: { phase: 'OPEN', is_open: true, active_sessions: ['LONDON'], reference_time_utc: new Date().toISOString(), next_open_utc: null, next_close_utc: null, note: null },
  stream: { websocket_endpoint: '/api/stream', sse_endpoint: '/api/events', subscribers: 1, events_published: 42 },
  database: { backend: 'sqlite', candles_stored: 4200, events_stored: 12, detections_stored: 0, retention_days: 120 },
  telegram: { status: 'NOT_CONFIGURED', bot_token_present: false, bot_token_preview: 'NOT_SET', chat_id_present: false, chat_id_preview: 'NOT_SET', capabilities: ['send_message', 'send_image'] },
  capture: { implemented: false, enabled: false, status: 'CAPTURE_NOT_IMPLEMENTED', required_elements: [] },
  // Phase 3: chartist + price-action engines really run, SMC/ICT does not.
  detection_engines: { CHART_PATTERN_ENGINE: 'ENABLED', PRICE_ACTION_ENGINE: 'ENABLED', SMC_ICT_ENGINE: 'ENABLED' },
  safety: { order_execution: false, broker_connection: false, position_management: false, note: 'scanner only' },
  config: {},
  cache: { entries: 3, hits: 9, keys: [] },
}

// ------------------------------------------------------- Phase 3 fixtures
export function priceActionDetection(overrides: Record<string, unknown> = {}) {
  return {
    id: 'pa_bullish_engulfing',
    dedup_key: 'pa_bullish_engulfing',
    symbol: 'EURUSD',
    timeframe: 'M15',
    timestamp: new Date().toISOString(),
    category: 'PRICE_ACTION',
    pattern: 'BULLISH_ENGULFING',
    direction: 'BULLISH',
    status: 'DETECTED',
    confidence: 75,
    source_engine: 'PRICE_ACTION_ENGINE',
    confidence_factors: [
      { criterion: 'Englobement du corps precedent', passed: true, weight: 1, detail: 'couverture 100%' },
      { criterion: 'Corps au moins aussi grand', passed: true, weight: 1, detail: 'x1.33' },
      { criterion: 'Meche opposee contenue', passed: false, weight: 1, detail: '54% du range' },
    ],
    evidence: [
      'Bougie 70 : O 1.1 H 1.1012 L 1.0993 C 1.101',
      'Englobement du corps reel : 100% du corps precedent couvert',
    ],
    evidence_points: {
      pattern: 'BULLISH_ENGULFING',
      pattern_kind: 'CANDLESTICK',
      previous_candle: { time: 1, open: 1.1, high: 1.101, low: 1.0994, close: 1.0994, body_size: 0.0006, range: 0.0016, body_ratio: 0.375, upper_wick: 0.0, lower_wick: 0.0 },
      current_candle: { time: 2, open: 1.0993, high: 1.1012, low: 1.0991, close: 1.101, body_size: 0.0017, range: 0.0021, body_ratio: 0.81, upper_wick: 0.0002, lower_wick: 0.0002 },
      measurements: { coverage_ratio: 1.0, body_multiple: 2.83, body_ratio: 0.81, range_pips: 21, atr: 0.0009 },
      level_context: {
        label: 'BULLISH_ENGULFING_AT_SUPPORT',
        nearest: { kind: 'SUPPORT', price: 1.0993, source: 'SUPPORT ct_ab12 [SUPPORT]', distance_pips: 0.5, tolerance_pips: 6, age_bars: 3, same_side: true },
        relations: [],
        chartist_active: [{ id: 'ct_ab12', pattern: 'CHANNEL', status: 'DETECTED', bars_away: 1 }],
        trading_signal: false,
        note: 'Contexte informatif : aucun signal, aucun ordre.',
      },
      context_criteria: [
        { criterion: 'Motif sur un niveau reel', passed: true, weight: 1, detail: 'SUPPORT a 1.0993', counts_towards_confidence: false },
      ],
      lifecycle: { anchor_candle_time: 2, watch_from_index: 70, max_bars_to_confirm: 12, state_pattern: false },
      parameters_version: 'abc12345',
      candle_measurements_available: ['body_size', 'upper_wick', 'lower_wick', 'range', 'body_ratio', 'wick_ratios'],
    },
    coordinates: [{ time: 2, price: 1.1012, role: 'PATTERN', label: 'MOTIF' }],
    drawing: {
      levels: [
        { price: 1.1012, label: 'TRIGGER', kind: 'LEVEL' },
        { price: 1.0991, label: 'INVALIDATION', kind: 'LEVEL' },
      ],
      lines: [],
      zones: [{ time_start: 1, time_end: 2, price_top: 1.1012, price_bottom: 1.0991, label: 'ENGLOBEMENT', kind: 'PATTERN' }],
      markers: [{ time: 2, price: 1.1012, position: 'aboveBar', shape: 'arrowUp', label: 'MOTIF', kind: 'HIGH' }],
    },
    parameters: { min_coverage: 1.0, parameters_version: 'abc12345', engine: { scan_bars: 12 } },
    confirmation: { confirmed: false, level: 1.1012, level_type: 'PATTERN_HIGH', breakout_time: null, breakout_price: null, breakout_candle_time: null, candles_to_confirm: null, volume: null, note: 'en attente' },
    invalidation: { invalidated: false, level: 1.0991, level_type: 'PATTERN_LOW', reason: 'cloture sous le plus bas', invalidated_at: null },
    breakout: null,
    retest: null,
    watch_levels: [{ level_type: 'PATTERN_HIGH', price: 1.1012, direction: 'BULLISH', role: 'CONFIRMATION' }],
    parent_detection_id: null,
    detected_at_bar_time: 2,
    first_seen_at: new Date().toISOString(),
    last_updated_at: new Date().toISOString(),
    bars_in_window: 71,
    notes: ['CONTEXTE: BULLISH_ENGULFING_AT_SUPPORT'],
    ...overrides,
  }
}

// ------------------------------------------------------------------- mocks
class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static readonly OPEN = 1
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

  emitOpen() {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.()
  }

  emitMessage(payload: unknown) {
    this.readyState = FakeWebSocket.OPEN
    this.onmessage?.({ data: JSON.stringify(payload) })
  }
}

function mockApi(
  overrides: {
    candlesStatus?: number
    detections?: unknown[]
    history?: unknown[]
    priceAction?: unknown[]
    priceActionHistory?: unknown[]
    priceActionStructure?: unknown[]
    confluence?: unknown
    smcIct?: unknown[]
    smcIctHistory?: unknown[]
    smcIctError?: number
  } = {},
) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

    if (url.includes('/api/smc-ict')) {
      if (overrides.smcIctError) {
        return json({ error: 'SMC_ICT_UNAVAILABLE', message: 'engine unreachable' }, overrides.smcIctError)
      }
      if (url.includes('/api/smc-ict/history')) {
        return json({
          count: (overrides.smcIctHistory ?? []).length,
          status_filter: null,
          detections: overrides.smcIctHistory ?? [],
        })
      }
      if (url.includes('/api/smc-ict/confluence')) {
        return json({
          count: 0,
          groups: [],
          trading_signal: false,
          note: 'Confluence informative uniquement',
        })
      }
      if (url.includes('/api/smc-ict/structure')) {
        return json({
          status: 'SMC STRUCTURE',
          detections: (overrides.smcIct ?? []).filter(
            (row) => ((row as { evidence_points?: { family?: string } }).evidence_points?.family) === 'STRUCTURE',
          ),
          counts: {},
          engines: { SMC_ICT_ENGINE: 'ENABLED' },
        })
      }
      return json({
        status: (overrides.smcIct ?? []).length ? 'ACTIVE SMC ICT' : 'NO ACTIVE SMC ICT',
        detections: overrides.smcIct ?? [],
        counts: {},
        engines: { SMC_ICT_ENGINE: 'ENABLED' },
        stats: { tracked: (overrides.smcIct ?? []).length, runs: 1 },
      })
    }
    if (url.includes('/api/symbols')) return json(SYMBOLS)
    if (url.includes('/api/status')) return json(STATUS)
    if (url.includes('/api/price-action/history'))
      return json({
        count: (overrides.priceActionHistory ?? []).length,
        status_filter: null,
        detections: overrides.priceActionHistory ?? [],
      })
    if (url.includes('/api/price-action/structure'))
      return json({
        status: (overrides.priceActionStructure ?? []).length ? 'STRUCTURE STATES' : 'NO STATE MEASURED',
        detections: overrides.priceActionStructure ?? [],
        counts: {},
        engines: { PRICE_ACTION_ENGINE: 'ENABLED', SMC_ICT_ENGINE: 'ENABLED' },
      })
    if (url.includes('/api/price-action/confluence'))
      return json(
        overrides.confluence ?? {
          count: 1,
          groups: [
            {
              symbol: 'EURUSD',
              timeframe: 'M15',
              groups: { chartist: [{ id: 'ct_ab12' }], price_action: (overrides.priceAction ?? []) as unknown[], structure: [] },
              labels: [],
              trading_signal: false,
              note: 'Confluence informative uniquement',
            },
          ],
          trading_signal: false,
          note: 'Confluence informative uniquement',
        },
      )
    if (url.includes('/api/price-action'))
      return json({
        status: (overrides.priceAction ?? []).length ? 'ACTIVE PRICE ACTION' : 'NO ACTIVE PRICE ACTION',
        detections: overrides.priceAction ?? [],
        counts: {},
        engines: { PRICE_ACTION_ENGINE: 'ENABLED', SMC_ICT_ENGINE: 'ENABLED' },
        stats: { runs: 2, bars_analysed: 600 },
      })
    if (url.includes('/api/detections/history'))
      return json({
        count: (overrides.history ?? []).length,
        status_filter: null,
        detections: overrides.history ?? [],
      })
    if (url.includes('/api/detections'))
      return json({
        status: (overrides.detections ?? []).length ? 'ACTIVE DETECTIONS' : 'NO ACTIVE DETECTION',
        detections: overrides.detections ?? [],
        counts: {},
        engines: { CHART_PATTERN_ENGINE: 'ENABLED', PRICE_ACTION_ENGINE: 'ENABLED', SMC_ICT_ENGINE: 'ENABLED' },
        stats: { runs: 3, bars_analysed: 900, persisted: (overrides.history ?? []).length, last_run_ms: 12.5 },
      })
    if (url.includes('/api/structure')) return json(STRUCTURE)
    if (url.includes('/api/market/')) return json(QUOTE)
    if (url.includes('/api/candles')) {
      if (overrides.candlesStatus === 503) {
        return json({ error: 'DATA_UNAVAILABLE', cause: 'PROVIDER_UNAVAILABLE', message: 'provider down' }, 503)
      }
      return json(CANDLES)
    }
    return json({}, 404)
  })
}

beforeEach(() => {
  FakeWebSocket.instances = []
  vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)
  vi.stubGlobal('fetch', mockApi())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function renderApp() {
  const user = userEvent.setup()
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('quote-price')).toHaveTextContent('1.13420'))
  return { user }
}

describe('dashboard', () => {
  it('loads and shows the selected pair with real data', async () => {
    await renderApp()
    expect(screen.getByText('SMART MARKET VISION')).toBeInTheDocument()
    expect(screen.getByTestId('quote-price')).toHaveTextContent('1.13420')
    expect(screen.getByTestId('quote-state')).toHaveTextContent('CONNECTED')
    expect(screen.getByTestId('provider-name')).toHaveTextContent('yahoo')
    expect(screen.getByTestId('telegram-status')).toHaveTextContent('NOT_CONFIGURED')
  })

  it('shows the market structure and never claims a detection', async () => {
    await renderApp()
    expect(screen.getByTestId('trend')).toHaveTextContent('BULLISH')
    const labels = screen.getByTestId('structure-labels')
    expect(within(labels).getAllByText('HH').length).toBeGreaterThan(0)
    expect(within(labels).getAllByText('HL').length).toBeGreaterThan(0)
    expect(screen.getByTestId('patterns-empty')).toHaveTextContent('AUCUNE DÉTECTION CHARTISTE')
  })

  it('changes the timeframe and reloads the candles', async () => {
    const { user } = await renderApp()
    const callsBefore = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length
    await user.click(screen.getByRole('tab', { name: 'H1' }))
    await waitFor(() => {
      expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(callsBefore)
    })
    const urls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((call) => String(call[0]))
    expect(urls.some((url) => url.includes('/api/candles/EURUSD/H1'))).toBe(true)
  })

  it('changes the pair and requests the new symbol', async () => {
    const { user } = await renderApp()
    await user.click(screen.getByRole('tab', { name: 'USDJPY' }))
    await waitFor(() => {
      const urls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((call) => String(call[0]))
      expect(urls.some((url) => url.includes('/api/candles/USDJPY/M15'))).toBe(true)
    })
  })

  it('renders the chart surface', async () => {
    await renderApp()
    expect(screen.getByTestId('chart-surface')).toBeInTheDocument()
  })
})

describe('live status', () => {
  it('starts as RECONNECTING then becomes LIVE on a real event', async () => {
    await renderApp()
    expect(screen.getByTestId('stream-status')).toHaveTextContent('RECONNECTING')

    const socket = FakeWebSocket.instances.at(-1)!
    expect(socket.url).toContain('/api/stream?symbol=EURUSD&timeframe=M15')
    socket.emitOpen()
    socket.emitMessage({
      id: 'evt_1',
      symbol: 'EURUSD',
      timeframe: 'M15',
      timestamp: new Date().toISOString(),
      event_type: 'STREAM_HELLO',
      price: null,
      metadata: {},
      source: 'STREAM',
    })
    await waitFor(() => expect(screen.getByTestId('stream-status')).toHaveTextContent('LIVE'))
    expect(screen.getByTestId('last-event-time')).not.toHaveTextContent('--:--:--')
  })

  it('updates the price from a live MARKET_UPDATE event', async () => {
    await renderApp()
    const socket = FakeWebSocket.instances.at(-1)!
    socket.emitMessage({
      id: 'evt_2',
      symbol: 'EURUSD',
      timeframe: 'M15',
      timestamp: new Date().toISOString(),
      event_type: 'MARKET_UPDATE',
      price: 1.2,
      metadata: { data_state: 'CONNECTED', candle_time: new Date().toISOString() },
      source: 'SCANNER',
    })
    await waitFor(() => expect(screen.getByTestId('quote-price')).toHaveTextContent('1.20000'))
  })

  it('accepts the +00:00 timestamp format used by the API without crashing', async () => {
    await renderApp()
    const socket = FakeWebSocket.instances.at(-1)!
    const errors: unknown[] = []
    const originalError = console.error
    console.error = (...args: unknown[]) => errors.push(args)
    socket.emitMessage({
      id: 'evt_iso',
      symbol: 'EURUSD',
      timeframe: 'M15',
      timestamp: '2026-09-29T23:15:00+00:00',
      event_type: 'MARKET_UPDATE',
      price: 1.19,
      metadata: { data_state: 'CONNECTED', candle_time: '2026-09-29T23:15:00+00:00' },
      source: 'SCANNER',
    })
    await waitFor(() => expect(screen.getByTestId('quote-price')).toHaveTextContent('1.19000'))
    console.error = originalError
    // only real failures matter here: React's "act" hints are a test harness artefact
    const real = errors.map((entry) => JSON.stringify(entry)).filter((text) => !text.includes('not wrapped in act'))
    expect(real.join(' ')).not.toMatch(/RangeError|Invalid time value/)
  })

  it('goes to RECONNECTING when the socket closes', async () => {
    await renderApp()
    const socket = FakeWebSocket.instances.at(-1)!
    socket.emitMessage({ id: 'e', symbol: 'EURUSD', timeframe: 'M15', timestamp: new Date().toISOString(), event_type: 'MARKET_UPDATE', price: 1.15, metadata: {}, source: 'SCANNER' })
    await waitFor(() => expect(screen.getByTestId('stream-status')).toHaveTextContent('LIVE'))
    socket.close()
    await waitFor(() => expect(screen.getByTestId('stream-status')).toHaveTextContent('RECONNECTING'))
  })
})

describe('data unavailable', () => {
  it('shows DATA UNAVAILABLE instead of a fabricated price', async () => {
    vi.stubGlobal('fetch', mockApi({ candlesStatus: 503 }))
    render(<App />)
    await waitFor(() => expect(screen.getByTestId('chart-unavailable')).toBeInTheDocument())
    expect(screen.getByTestId('chart-unavailable')).toHaveTextContent('DATA UNAVAILABLE')
    expect(screen.getByTestId('api-error')).toHaveTextContent('DATA_UNAVAILABLE')
  })
})


// ------------------------------------------------------------------- Phase 2
function detectionFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: 'ct_test0000000001',
    dedup_key: 'ct_test0000000001',
    symbol: 'EURUSD',
    timeframe: 'M15',
    timestamp: '2026-09-29T18:00:00+00:00',
    category: 'CHARTISTE',
    pattern: 'DOUBLE_TOP',
    direction: 'BEARISH',
    status: 'DETECTED',
    confidence: 83.3,
    source_engine: 'CHART_PATTERN_ENGINE',
    confidence_factors: [
      { criterion: 'Proximite des deux extremes', passed: true, weight: 2, detail: '0.50 pip vs 5.00 pip' },
      { criterion: 'Profondeur suffisante', passed: true, weight: 1.5, detail: '25.0 pips' },
      { criterion: 'Symetrie des deux moities', passed: true, weight: 1, detail: 'rapport 1.00' },
      { criterion: 'Duree de formation dans la bande ideale', passed: true, weight: 0.5, detail: '28 bougies' },
      { criterion: 'Aucun depassement intermediaire', passed: true, weight: 1, detail: '0 pivot' },
      { criterion: 'Neckline exploitable', passed: true, weight: 1, detail: 'neckline 1.10738' },
    ],
    evidence: ['Sommet 1 : 1.11012', 'Sommet 2 : 1.11007', 'Ecrat entre les deux : 0.50 pip'],
    evidence_points: { peak_1: { price: 1.11012 } },
    coordinates: [{ time: 1760000000, price: 1.11012, role: 'PEAK_1', label: 'S1' }],
    drawing: { levels: [{ price: 1.10738, label: 'NECKLINE', kind: 'NECKLINE' }], lines: [], zones: [], markers: [], label_text: 'DOUBLE_TOP', label_time: null },
    parameters: { peak_tolerance_pips: 5 },
    confirmation: { confirmed: false, level: null, level_type: null, breakout_time: null, breakout_price: null, breakout_candle_time: null, candles_to_confirm: null, volume: null, note: 'en attente' },
    invalidation: { invalidated: false, level: 1.11032, level_type: 'PEAK_BROKEN', reason: 'cloture au-dessus', invalidated_at: null },
    breakout: null,
    retest: null,
    watch_levels: [{ level_type: 'NECKLINE', price: 1.10738, direction: 'BEARISH' }],
    parent_detection_id: null,
    detected_at_bar_time: 1760000000,
    first_seen_at: '2026-09-29T18:00:00+00:00',
    last_updated_at: '2026-09-29T18:00:00+00:00',
    bars_in_window: 300,
    notes: [],
    ...overrides,
  }
}

describe('chartist detections panel (Phase 2)', () => {
  it('shows an explicit empty state instead of a fabricated detection', async () => {
    await renderApp()
    expect(screen.getByTestId('patterns-empty')).toBeInTheDocument()
    expect(screen.getByTestId('active-empty')).toBeInTheDocument()
    expect(screen.getByTestId('history-empty')).toBeInTheDocument()
  })

  it('lists a real detection with its validated criteria and confidence', async () => {
    vi.stubGlobal('fetch', mockApi({ detections: [detectionFixture()], history: [detectionFixture()] }))
    await renderApp()
    const row = await screen.findByTestId('pattern-DOUBLE_TOP')
    expect(within(row).getByText('Double sommet')).toBeInTheDocument()
    expect(within(row).getByText('BAISSIER')).toBeInTheDocument()
    expect(within(row).getByText('DÉTECTÉ')).toBeInTheDocument()
    expect(within(row).getByText(/Confiance 83%/)).toBeInTheDocument()
    expect(within(row).getByText('6/6 critères validés')).toBeInTheDocument()
    expect(screen.queryByTestId('patterns-empty')).not.toBeInTheDocument()
  })

  it('shows the stored history with date, pair, timeframe, pattern, direction and status', async () => {
    vi.stubGlobal('fetch', mockApi({ detections: [detectionFixture()], history: [detectionFixture()] }))
    await renderApp()
    const table = await screen.findByTestId('history-table')
    const cells = within(table).getAllByRole('cell')
    const text = cells.map((cell) => cell.textContent ?? '')
    expect(text).toContain('EURUSD')
    expect(text).toContain('M15')
    expect(text).toContain('Double sommet')
    expect(text).toContain('BAISSIER')
    expect(text).toContain('DÉTECTÉ')
  })

  it('draws the selected detection on the chart from its real coordinates', async () => {
    vi.stubGlobal('fetch', mockApi({ detections: [detectionFixture()], history: [detectionFixture()] }))
    const { user } = await renderApp()
    await user.click(await screen.findByTestId('view-DOUBLE_TOP'))
    const banner = await screen.findByTestId('chart-detection-banner')
    expect(banner).toHaveTextContent('DOUBLE_TOP')
    expect(banner).toHaveTextContent('BEARISH')
    await user.click(within(banner).getByRole('button', { name: 'MASQUER' }))
    await waitFor(() => expect(screen.queryByTestId('chart-detection-banner')).not.toBeInTheDocument())
  })

  it('adds a detection pushed by the WebSocket without any reload', async () => {
    await renderApp()
    expect(screen.getByTestId('patterns-empty')).toBeInTheDocument()
    const socket = FakeWebSocket.instances.at(-1)!
    const callsBefore = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length
    socket.emitMessage({
      id: 'evt_pattern',
      symbol: 'EURUSD',
      timeframe: 'M15',
      timestamp: new Date().toISOString(),
      event_type: 'PATTERN_DETECTED',
      price: null,
      metadata: { detection: detectionFixture(), pattern: 'DOUBLE_TOP', status: 'DETECTED' },
      source: 'CHART_PATTERN_ENGINE',
    })
    const row = await screen.findByTestId('pattern-DOUBLE_TOP')
    expect(row).toBeInTheDocument()
    expect(screen.getByTestId('pattern-flash')).toHaveTextContent('PATTERN_DETECTED')
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsBefore)
  })

  it('moves an existing detection to CONFIRMED when the breakout event arrives', async () => {
    vi.stubGlobal('fetch', mockApi({ detections: [detectionFixture()], history: [detectionFixture()] }))
    await renderApp()
    const socket = FakeWebSocket.instances.at(-1)!
    socket.emitMessage({
      id: 'evt_confirm',
      symbol: 'EURUSD',
      timeframe: 'M15',
      timestamp: new Date().toISOString(),
      event_type: 'PATTERN_CONFIRMED',
      price: 1.10707,
      metadata: {
        detection: detectionFixture({
          status: 'CONFIRMED',
          confirmation: { confirmed: true, level: 1.10738, level_type: 'NECKLINE', breakout_time: 1760079200, breakout_price: 1.10707, breakout_candle_time: 1760079200, candles_to_confirm: 17, volume: null, note: 'cloture bearish' },
        }),
        pattern: 'DOUBLE_TOP',
        status: 'CONFIRMED',
      },
      source: 'CHART_PATTERN_ENGINE',
    })
    await waitFor(() => expect(screen.getByTestId('pattern-DOUBLE_TOP')).toHaveTextContent('CONFIRMÉ'))
    expect(screen.getAllByTestId('pattern-DOUBLE_TOP')).toHaveLength(1)
  })
})

// ------------------------------------------------- subscription lifecycle
describe('stream subscription lifecycle', () => {
  it('closes the previous subscription on a pair change and never reopens it', async () => {
    const { user } = await renderApp()
    const first = FakeWebSocket.instances.at(-1)!
    expect(first.url).toContain('symbol=EURUSD')

    await user.click(screen.getByRole('tab', { name: 'USDJPY' }))
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(2))
    const second = FakeWebSocket.instances.at(-1)!
    expect(second.url).toContain('symbol=USDJPY')
    expect(first.readyState).toBe(3) // the hook really closed the old subscription

    // The reconnect delay is 1000 ms: a late onclose from the old socket would
    // open a ghost subscription to the previous symbol. It must not happen.
    await new Promise((resolve) => setTimeout(resolve, 1400))
    expect(FakeWebSocket.instances.length).toBe(2)
  })

  it('ignores events pushed by a subscription that is no longer the current one', async () => {
    const { user } = await renderApp()
    const first = FakeWebSocket.instances.at(-1)!
    await user.click(screen.getByRole('tab', { name: 'USDJPY' }))
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(2))
    expect(await screen.findByTestId('pa-no-active')).toBeInTheDocument()

    // a stale frame from the closed EURUSD socket (and from a stale DETECTIONS_SNAPSHOT)
    first.emitMessage({
      id: 'evt_stale_pa',
      symbol: 'EURUSD',
      timeframe: 'M15',
      timestamp: new Date().toISOString(),
      event_type: 'PRICE_ACTION_SNAPSHOT',
      price: null,
      metadata: {
        status: 'ACTIVE PRICE ACTION',
        detections: [priceActionDetection({ symbol: 'EURUSD', id: 'pa_stale' })],
        structure: [],
        counts: {},
        engines: { PRICE_ACTION_ENGINE: 'ENABLED' },
      },
      source: 'STREAM',
    })
    first.emitMessage({
      id: 'evt_stale_det',
      symbol: 'EURUSD',
      timeframe: 'M15',
      timestamp: new Date().toISOString(),
      event_type: 'PATTERN_DETECTED',
      price: null,
      metadata: { detection: detectionFixture(), pattern: 'DOUBLE_TOP', status: 'DETECTED' },
      source: 'CHART_PATTERN_ENGINE',
    })

    await new Promise((resolve) => setTimeout(resolve, 300))
    expect(screen.queryByTestId('pa-row')).not.toBeInTheDocument()
    expect(screen.queryByTestId('pattern-DOUBLE_TOP')).not.toBeInTheDocument()
  })
})

// --------------------------------------------------------- Phase 3 dashboard
describe('price action (Phase 3)', () => {
  it('loads the price-action panel from the API and shows the criteria count', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({ priceAction: [priceActionDetection()], priceActionHistory: [priceActionDetection()] }),
    )
    await renderApp()
    const panel = await screen.findByTestId('price-action-panel')
    expect(panel).toBeInTheDocument()
    const row = within(panel).getByTestId('pa-row')
    expect(row).toHaveTextContent('Englobante haussière')
    expect(row).toHaveTextContent('EURUSD')
    expect(row).toHaveTextContent('M15')
    expect(row).toHaveTextContent('HAUSSIER')
    expect(row).toHaveTextContent('DÉTECTÉ')
    expect(within(panel).getByTestId('pa-criteria')).toHaveTextContent('2 / 3 critères')
    expect(within(panel).getByTestId('pa-context')).toHaveTextContent('BULLISH_ENGULFING_AT_SUPPORT')
  })

  it('shows an explicit empty state and never invents a detection', async () => {
    await renderApp()
    expect(await screen.findByTestId('pa-no-active')).toHaveTextContent('AUCUNE DÉTECTION PRICE ACTION ACTIVE')
    expect(screen.queryByTestId('pa-row')).not.toBeInTheDocument()
  })

  it('filters the dashboard: Chartiste / Price Action / Tous', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({
        detections: [detectionFixture()],
        history: [detectionFixture()],
        priceAction: [priceActionDetection()],
        priceActionHistory: [priceActionDetection()],
      }),
    )
    const { user } = await renderApp()
    // TOUS: both families are present
    expect(await screen.findByTestId('price-action-panel')).toBeInTheDocument()
    expect(screen.getByTestId('pattern-DOUBLE_TOP')).toBeInTheDocument()

    await user.click(screen.getByTestId('filter-PRICE_ACTION'))
    await waitFor(() => expect(screen.queryByTestId('pattern-DOUBLE_TOP')).not.toBeInTheDocument())
    expect(screen.getByTestId('price-action-panel')).toBeInTheDocument()
    expect(screen.queryByTestId('structure-labels')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('filter-CHARTISTE'))
    await waitFor(() => expect(screen.queryByTestId('price-action-panel')).not.toBeInTheDocument())
    expect(screen.getByTestId('pattern-DOUBLE_TOP')).toBeInTheDocument()

    await user.click(screen.getByTestId('filter-TOUS'))
    await waitFor(() => expect(screen.getByTestId('price-action-panel')).toBeInTheDocument())
  })

  it('draws the selected price-action detection on the chart and can hide it', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({ priceAction: [priceActionDetection()], priceActionHistory: [priceActionDetection()] }),
    )
    const { user } = await renderApp()
    const panel = await screen.findByTestId('price-action-panel')
    await user.click(within(panel).getByTestId('pa-show-chart'))
    const banner = await screen.findByTestId('chart-detection-banner')
    expect(banner).toHaveTextContent('PRICE ACTION')
    expect(banner).toHaveTextContent('BULLISH_ENGULFING')
    await user.click(within(banner).getByRole('button', { name: 'MASQUER' }))
    await waitFor(() => expect(screen.queryByTestId('chart-detection-banner')).not.toBeInTheDocument())
  })

  it('shows the measurements, the evidence and the criteria breakdown on demand', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({ priceAction: [priceActionDetection()], priceActionHistory: [priceActionDetection()] }),
    )
    const { user } = await renderApp()
    const panel = await screen.findByTestId('price-action-panel')
    expect(within(panel).getByText(/coverage ratio : 1/)).toBeInTheDocument()
    await user.click(within(panel).getByTestId('pa-toggle-evidence'))
    const evidence = await within(panel).findByTestId('pa-evidence')
    expect(evidence).toHaveTextContent('couverture 100%')
    expect(evidence).toHaveTextContent('NON · Meche opposee contenue')
    expect(evidence).toHaveTextContent('SUPPORT à 1.0993')
  })

  it('renders the measured market states (impulsion / consolidation)', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({
        priceAction: [priceActionDetection()],
        priceActionHistory: [priceActionDetection()],
        priceActionStructure: [
          priceActionDetection({
            id: 'pa_impulsion',
            pattern: 'IMPULSION',
            direction: 'BULLISH',
            evidence_points: {
              pattern: 'IMPULSION',
              pattern_kind: 'STRUCTURE',
              measurements: { net_move_pips: 42, efficiency: 0.86, atr: 0.0009, bars: 8 },
            },
          }),
        ],
      }),
    )
    await renderApp()
    const block = await screen.findByTestId('pa-structure-block')
    expect(block).toHaveTextContent('Impulsion')
    expect(within(block).getByText(/net move pips : 42/)).toBeInTheDocument()
  })

  it('never shows a trading recommendation', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({
        priceAction: [priceActionDetection()],
        priceActionHistory: [priceActionDetection()],
        detections: [detectionFixture()],
      }),
    )
    await renderApp()
    const text = document.body.textContent ?? ''
    for (const forbidden of ['BUY', 'SELL', 'ENTRY', 'STOP LOSS', 'TAKE PROFIT', 'SIGNAL D\'ACHAT']) {
      expect(text).not.toContain(forbidden)
    }
  })

  it('adds a price-action detection pushed by the WebSocket without any reload', async () => {
    await renderApp()
    expect(await screen.findByTestId('pa-no-active')).toBeInTheDocument()
    const socket = FakeWebSocket.instances.at(-1)!
    const callsBefore = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length
    socket.emitMessage({
      id: 'evt_pa',
      symbol: 'EURUSD',
      timeframe: 'M15',
      timestamp: new Date().toISOString(),
      event_type: 'PRICE_ACTION_DETECTED',
      price: null,
      metadata: { detection: priceActionDetection(), pattern: 'BULLISH_ENGULFING', status: 'DETECTED' },
      source: 'PRICE_ACTION_ENGINE',
    })
    const panel = await screen.findByTestId('price-action-panel')
    expect(await within(panel).findByTestId('pa-row')).toHaveTextContent('Englobante haussière')
    expect(screen.getByTestId('pattern-flash')).toHaveTextContent('PRICE_ACTION_DETECTED')
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsBefore)
  })

  it('applies the PRICE_ACTION_SNAPSHOT sent on reconnection', async () => {
    await renderApp()
    const socket = FakeWebSocket.instances.at(-1)!
    socket.emitMessage({
      id: 'evt_pa_snapshot',
      symbol: 'EURUSD',
      timeframe: 'M15',
      timestamp: new Date().toISOString(),
      event_type: 'PRICE_ACTION_SNAPSHOT',
      price: null,
      metadata: {
        status: 'ACTIVE PRICE ACTION',
        detections: [priceActionDetection()],
        structure: [priceActionDetection({ id: 'pa_consolidation', pattern: 'CONSOLIDATION', direction: 'NEUTRAL' })],
        counts: { BULLISH_ENGULFING: 1 },
        engines: { PRICE_ACTION_ENGINE: 'ENABLED', SMC_ICT_ENGINE: 'ENABLED' },
      },
      source: 'STREAM',
    })
    const panel = await screen.findByTestId('price-action-panel')
    expect(await within(panel).findByTestId('pa-row')).toHaveTextContent('Englobante haussière')
    expect(await within(panel).findByTestId('pa-structure-row')).toHaveTextContent('Consolidation')
  })

  it('moves a price-action detection to CONFIRMED then INVALIDATED on real events', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({ priceAction: [priceActionDetection()], priceActionHistory: [priceActionDetection()] }),
    )
    await renderApp()
    const socket = FakeWebSocket.instances.at(-1)!
    socket.emitMessage({
      id: 'evt_pa_confirm',
      symbol: 'EURUSD',
      timeframe: 'M15',
      timestamp: new Date().toISOString(),
      event_type: 'PRICE_ACTION_CONFIRMED',
      price: 1.1015,
      metadata: {
        detection: priceActionDetection({ status: 'CONFIRMED' }),
        pattern: 'BULLISH_ENGULFING',
        status: 'CONFIRMED',
      },
      source: 'PRICE_ACTION_ENGINE',
    })
    const panel = await screen.findByTestId('price-action-panel')
    await waitFor(() => expect(within(panel).getByTestId('pa-row')).toHaveTextContent('CONFIRMÉ'))

    socket.emitMessage({
      id: 'evt_pa_invalidated',
      symbol: 'EURUSD',
      timeframe: 'M15',
      timestamp: new Date().toISOString(),
      event_type: 'PRICE_ACTION_INVALIDATED',
      price: 1.0988,
      metadata: {
        detection: priceActionDetection({ status: 'INVALIDATED' }),
        pattern: 'BULLISH_ENGULFING',
        status: 'INVALIDATED',
      },
      source: 'PRICE_ACTION_ENGINE',
    })
    await waitFor(() => {
      expect(within(panel).getByTestId('pa-recent-row')).toHaveTextContent('Englobante haussière')
      expect(within(panel).getByTestId('pa-recent-row')).toHaveTextContent('INVALIDÉ')
    })
  })

  it('shows the informative confluence without any score', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({ priceAction: [priceActionDetection()], priceActionHistory: [priceActionDetection()] }),
    )
    await renderApp()
    const block = await screen.findByTestId('pa-confluence-block')
    expect(block).toHaveTextContent('INFORMATIF')
    expect(within(block).getByTestId('pa-confluence-note')).toHaveTextContent('aucun score')
  })
})
