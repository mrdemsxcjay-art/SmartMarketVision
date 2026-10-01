/** Shared types - mirror of the backend JSON contracts (Phase 1). */

export type Timeframe = 'M5' | 'M15' | 'H1' | 'H4' | 'D1'

export const TIMEFRAMES: Timeframe[] = ['M5', 'M15', 'H1', 'H4', 'D1']

export type DataState = 'CONNECTED' | 'CACHED' | 'STALE' | 'DATA_UNAVAILABLE' | 'MARKET_CLOSED'

export type StructuralTrend = 'BULLISH' | 'BEARISH' | 'RANGE' | 'UNDEFINED'

export type StreamStatus = 'LIVE' | 'RECONNECTING' | 'DISCONNECTED'

export interface Candle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number | null
  closed: boolean
  iso: string
}

export interface CandleResponse {
  symbol: string
  timeframe: Timeframe
  provider: string
  data_state: DataState
  stale: boolean
  digits: number
  pip_size: number
  count: number
  fetched_at: string
  quality_warnings: string[]
  candles: Candle[]
}

export interface MarketStatus {
  phase: 'OPEN' | 'CLOSED_WEEKEND' | 'CLOSED_HOLIDAY' | 'UNKNOWN'
  is_open: boolean
  active_sessions: string[]
  reference_time_utc: string
  next_open_utc: string | null
  next_close_utc: string | null
  note: string | null
}

export interface Quote {
  symbol: string
  timeframe: Timeframe
  provider: string
  data_state: DataState
  price: number | null
  prev_close: number | null
  change: number | null
  change_percent: number | null
  digits: number
  candle_time: string | null
  last_update: string | null
  market: MarketStatus | null
  stale: boolean
  error: string | null
}

export interface SwingPoint {
  index: number
  time: number
  iso: string
  price: number
  kind: 'HIGH' | 'LOW'
  label: 'HH' | 'HL' | 'LH' | 'LL' | 'H' | 'L' | '?'
  confirmed_at_index: number
}

export interface StructureResponse {
  symbol: string
  timeframe: Timeframe
  provider: string
  data_state: DataState
  trend: StructuralTrend
  labels: string[]
  recent_labels: string[]
  bars_analyzed: number
  using_closed_candles_only: boolean
  pivot_left: number
  pivot_right: number
  swing_count: number
  last_swing_high: SwingPoint | null
  last_swing_low: SwingPoint | null
  swings: SwingPoint[]
  notes: string[]
  evaluated_at: string
  smc_ict: { implemented: boolean; message: string }
}

export interface SymbolInfo {
  symbol: string
  description: string
  base: string
  quote: string
  digits: number
  pip_size: number
  asset_class: string
  provider_symbol: string
  enabled: boolean
  provider?: string
  cached_at?: string | null
}

export interface SymbolListResponse {
  provider: string
  count: number
  timeframes: Timeframe[]
  default_timeframe: Timeframe
  symbols: SymbolInfo[]
}

/* ------------------------------------------------------------------ Phase 2
 * Chartist detection contract: the exact JSON the backend serves on
 * /api/detections, /api/detections/history and the pattern events.
 * ------------------------------------------------------------------------ */

/**
 * Detection lifecycle. ACTIVE / MITIGATED / FILLED were added by the SMC/ICT
 * engine (Phase 4): they are the states of a zone that is still in play, that
 * was mitigated, or that was completely filled.
 */
export type PatternStatus =
  | 'DETECTED'
  | 'ACTIVE'
  | 'CONFIRMED'
  | 'MITIGATED'
  | 'FILLED'
  | 'INVALIDATED'
  | 'EXPIRED'
export type PatternDirection = 'BULLISH' | 'BEARISH' | 'NEUTRAL'
export type DetectionCategory = 'CHARTISTE' | 'PRICE_ACTION' | 'SMC_ICT'
export type PatternEventType =
  | 'PATTERN_DETECTED'
  | 'BREAKOUT_DETECTED'
  | 'PATTERN_CONFIRMED'
  | 'PATTERN_INVALIDATED'
  | 'PATTERN_EXPIRED'
  | 'RETEST_DETECTED'

/* ------------------------------------------------------------------ Phase 3
 * Price-action contract: /api/price-action, /api/price-action/history, the
 * PRICE_ACTION_* events and the PRICE_ACTION_SNAPSHOT sent on (re)connection.
 * The payload is exactly the same PatternDetection shape, with
 * category = PRICE_ACTION - there is no parallel detection system.
 * ------------------------------------------------------------------------ */

export type PriceActionEventType =
  | 'PRICE_ACTION_DETECTED'
  | 'PRICE_ACTION_CONFIRMED'
  | 'PRICE_ACTION_INVALIDATED'
  | 'PRICE_ACTION_EXPIRED'
  | 'FAILED_BREAKOUT'

export interface StructureMeasurements {
  [key: string]: number | string | boolean | null
}

export interface LevelRelation {
  kind: string
  price: number
  source: string
  distance_pips: number
  tolerance_pips: number
  age_bars: number | null
  same_side: boolean
}

export interface LevelContext {
  label: string | null
  nearest: LevelRelation | null
  relations: LevelRelation[]
  chartist_active: { id: string; pattern: string; status: string; bars_away: number }[]
  trading_signal: boolean
  note: string
}

export interface ContextCriterion {
  criterion: string
  passed: boolean
  weight: number
  detail: string
  counts_towards_confidence: boolean
}

export interface ConfluenceGroup {
  symbol: string
  timeframe: string
  groups: {
    chartist: Record<string, unknown>[]
    price_action: Record<string, unknown>[]
    structure: Record<string, unknown>[]
  }
  labels: string[]
  trading_signal: boolean
  note: string
}

export interface ConfluenceResponse {
  count: number
  groups: ConfluenceGroup[]
  trading_signal: boolean
  note: string
}

export interface PatternCoordinate {
  time: number
  price: number
  role: string
  label: string
}

export interface DrawingLevel {
  price: number
  label: string
  kind: string
  color?: string | null
  style?: string | null
}

export interface DrawingLine {
  label: string
  kind: string
  points: { time: number; price: number }[]
  color?: string | null
  style?: string | null
}

export interface DrawingZone {
  label: string
  price_top: number
  price_bottom: number
  time_start: number
  time_end: number
  /** family of the concept that produced the zone (BOS, FVG, ORDER_BLOCK, ...) */
  kind?: string
}

export interface DrawingMarker {
  time: number
  price: number
  position: 'aboveBar' | 'belowBar'
  shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown'
  label: string
  kind: string
}

export interface DrawingSpec {
  levels: DrawingLevel[]
  lines: DrawingLine[]
  zones: DrawingZone[]
  markers: DrawingMarker[]
  label_text: string
  label_time: number | null
}

export interface ConfidenceFactor {
  criterion: string
  passed: boolean
  weight: number
  detail: string
}

export interface WatchLevel {
  level_type: string
  price: number
  direction: PatternDirection
}

export interface BreakoutInfo {
  id: string
  level: number
  level_type: string
  direction: PatternDirection
  breakout_price: number
  breakout_time: number
  confirming_candle_time: number
  candles_to_breakout: number
  buffer_pips: number
  volume: number | null
}

export interface RetestInfo {
  breakout_level: number
  breakout_candle_time: number
  retest_candle_time: number
  retest_price: number
  distance_to_level_pips: number
  candles_after_breakout: number
  confirmed: boolean
}

export interface ConfirmationState {
  confirmed: boolean
  level: number | null
  level_type: string | null
  breakout_time: number | null
  breakout_price: number | null
  breakout_candle_time: number | null
  candles_to_confirm: number | null
  volume: number | null
  note: string
}

export interface InvalidationState {
  invalidated: boolean
  level: number | null
  level_type: string | null
  reason: string
  invalidated_at: number | null
}

export interface PatternDetection {
  id: string
  dedup_key: string
  symbol: string
  timeframe: Timeframe
  timestamp: string
  category: DetectionCategory
  pattern: string
  direction: PatternDirection
  status: PatternStatus
  confidence: number
  source_engine: string
  confidence_factors: ConfidenceFactor[]
  evidence: string[]
  evidence_points: Record<string, unknown>
  coordinates: PatternCoordinate[]
  drawing: DrawingSpec
  parameters: Record<string, unknown>
  confirmation: ConfirmationState
  invalidation: InvalidationState
  breakout: BreakoutInfo | null
  retest: RetestInfo | null
  watch_levels: WatchLevel[]
  parent_detection_id: string | null
  detected_at_bar_time: number | null
  first_seen_at: string | null
  last_updated_at: string | null
  bars_in_window: number
  notes: string[]
}

export interface DetectionsResponse {
  status: string
  detections: PatternDetection[]
  counts: Record<string, number>
  engines: Record<string, string>
  stats?: Record<string, unknown>
  message?: string
}

export interface DetectionHistoryResponse {
  count: number
  status_filter: string | null
  detections: PatternDetection[]
}

export interface PatternParamsResponse {
  params: Record<string, Record<string, unknown>>
  engines: Record<string, string>
  stats: Record<string, unknown>
}

export interface PatternEventMetadata {
  detection: PatternDetection
  previous_status: PatternStatus | null
  pattern: string
  direction: PatternDirection
  status: PatternStatus
  confidence: number
  dedup_key: string
  provider: string
  data_state?: DataState
  breakout?: BreakoutInfo
  retest?: RetestInfo
}

export interface SystemStatus {
  status: string
  server_time_utc: string
  app_env: string
  provider: string
  provider_health: {
    provider: string
    reachable: boolean
    last_success_utc: string | null
    last_error: string | null
    consecutive_failures: number
    requests_total: number
    requests_failed: number
    average_latency_ms: number | null
  }
  watchlist_size: number
  watchlist: string[]
  timeframes: Timeframe[]
  scanner: {
    running: boolean
    ticks: number
    interval_seconds: number
    last_tick_at: string | null
    last_tick_duration_ms: number | null
    pairs_scanned_last_tick: number
    pairs_failed_last_tick: number
    errors: string[]
    default_timeframe: string
  }
  market: MarketStatus
  stream: { websocket_endpoint: string; sse_endpoint: string; subscribers: number; events_published: number }
  database: {
    backend: string
    candles_stored: number
    events_stored: number
    detections_stored: number
    retention_days: number
  }
  telegram: {
    status: string
    bot_token_present: boolean
    bot_token_preview: string
    chat_id_present: boolean
    chat_id_preview: string
    capabilities: string[]
  }
  capture: { implemented: boolean; enabled: boolean; status: string; required_elements: string[] }
  detection_engines: Record<string, string>
  safety: { order_execution: boolean; broker_connection: boolean; position_management: boolean; note: string }
  config: Record<string, unknown>
  cache: { entries: number; hits: number; keys: string[] }
}


/* ------------------------------------------------------------------ Phase 4
 * SMC / ICT contract: /api/smc-ict, /api/smc-ict/history, the SMC_* events and
 * the SMC_ICT_SNAPSHOT sent on (re)connection. The payload is the very same
 * PatternDetection shape, with category = 'SMC_ICT' - one detection system, no
 * parallel one. Two additions are read from the payload:
 *   * evidence_points.family       -> STRUCTURE | LIQUIDITY | GAPS | BLOCKS | RANGE
 *   * evidence_points.smc_state    -> the lifecycle state of the concept
 * Liquidity is ALWAYS an estimate: those payloads carry estimate = true.
 * ------------------------------------------------------------------------ */

export type SmcIctEventType =
  | 'SMC_DETECTED'
  | 'SMC_CONFIRMED'
  | 'SMC_INVALIDATED'
  | 'SMC_MITIGATED'
  | 'SMC_FILLED'
  | 'SMC_EXPIRED'

export type SmcFamily = 'STRUCTURE' | 'LIQUIDITY' | 'GAPS' | 'BLOCKS' | 'RANGE'

export type SmcState =
  | 'CREATED'
  | 'ACTIVE'
  | 'PARTIALLY_FILLED'
  | 'FILLED'
  | 'MITIGATED'
  | 'INVALIDATED'
  | 'CONFIRMED'

export interface SmcConfluenceItem {
  pattern: string
  index: number
  family: string
  levels: Record<string, number | null>
}

/**
 * Internal SMC confluence (section 16). It is NOT the price-action confluence
 * shape: it groups the SMC objects that describe the SAME move, with the
 * families they come from. Descriptive only - there is no score and no signal.
 */
export interface SmcConfluenceGroup {
  direction: string
  from_index: number
  to_index: number
  span_bars: number
  families: string[]
  count: number
  items: SmcConfluenceItem[]
}

export interface SmcConfluenceResponse {
  count: number
  groups: SmcConfluenceGroup[]
  trading_signal: boolean
  note: string
}

export interface SmcEvidencePoints {
  family?: SmcFamily
  smc_state?: SmcState | string
  criteria?: { criterion: string; passed: boolean; detail: string }[]
  measurements?: Record<string, number | string | boolean | null>
  levels?: Record<string, number | null>
  estimate?: boolean
  swings?: unknown
  source_index?: number
  atr?: number
  atr_pips?: number
  pip_size?: number
  object?: Record<string, unknown>
  [key: string]: unknown
}

export interface MarketEvent {
  id: string
  symbol: string | null
  timeframe: Timeframe | null
  timestamp: string
  event_type: string
  price: number | null
  metadata: Record<string, unknown>
  source: string
}

/* ------------------------------------------------------------------ Phase 5+
 * Contracts of the confluence / opportunity / capture / telegram payloads.
 * They mirror the backend JSON exactly: no field is invented here, and every
 * score shown by the dashboard comes from one of these objects.
 */

export type ConfluenceDirection = 'BULLISH' | 'BEARISH' | 'NEUTRAL'
export type ConfluenceState =
  | 'NO_CONFLUENCE'
  | 'WATCH'
  | 'CONFLUENCE'
  | 'STRONG_CONFLUENCE'
  | 'CONTRADICTED'
  | 'EXPIRED'

export interface ConfluenceComponent {
  dimension: string
  label: string
  points: number
  reason: string
  events: string[]
  timeframes: string[]
}

export interface ConfluenceEvent {
  id: string
  symbol: string
  timeframe: string
  source: string
  type: string
  direction: string
  dimension: string | null
  timestamp: number
  price: number | null
  status: string
  confidence: number | null
}

export interface ConfluenceReading {
  id: string
  dedup_key: string
  signature: string
  symbol: string
  timeframe: string
  direction: ConfluenceDirection
  state: ConfluenceState
  score: number
  max_score: number
  dimensions: string[]
  components: ConfluenceComponent[]
  contradictions: ConfluenceComponent[]
  events: ConfluenceEvent[]
  why: string[]
  against: string[]
  reference_price: number | null
  window_start: number
  window_end: number
  first_seen_at?: string | null
  last_seen_at?: string | null
  expires_at?: string | null
  generation?: number
  previous_state?: string | null
}

export interface ConfluenceListResponse {
  count: number
  symbol?: string | null
  timeframe?: string | null
  confluences: ConfluenceReading[]
  counts: Record<string, number>
  by_direction: Record<string, number>
  engines: Record<string, string>
  stats: Record<string, unknown>
  trading_signal: boolean
}

/** MARKET OVERVIEW block: one row, the six values the header must show. */
export interface OpportunityOverview {
  symbol: string | null
  timeframe: string | null
  direction: string
  state: string | null
  score: number
  max_score: number
  opportunity_id: string | null
  confluence_id: string | null
  reference_price: number | null
  no_trade_reason: string | null
  tracked: number
  named: number
}

export interface OpportunityCondition {
  label: string
  passed: boolean
  detail: string
  points: number
  dimension: string | null
  gate: boolean
}

export interface OpportunityLevel {
  label: string
  price: number
  kind: string
  note: string
}

export type OpportunityDirection = 'BUY' | 'SELL' | 'WATCH' | 'NO_TRADE'
export type OpportunityState =
  | 'CREATED'
  | 'ACTIVE'
  | 'CONFIRMED'
  | 'WEAKENED'
  | 'INVALIDATED'
  | 'EXPIRED'

export interface Opportunity {
  id: string
  symbol: string
  timeframe: string
  direction: OpportunityDirection
  state: OpportunityState
  score: number
  max_score: number
  confluence_id: string | null
  confluence_state: string | null
  reference_price: number | null
  conditions: OpportunityCondition[]
  evidence: string[]
  no_trade_reason: string | null
  blocked_by: string | null
  watch_levels: OpportunityLevel[]
  created_at: string | null
  updated_at: string | null
  observed_bar_time: number | null
  confirmation_bar_time: number | null
  expires_at: string | null
  generation: number
  alert_key: string | null
  note: string
}

export interface OpportunitiesResponse {
  count: number
  symbol?: string | null
  timeframe?: string | null
  opportunities: Opportunity[]
  counts: Record<string, number>
  directions: Record<string, number>
  engines: Record<string, string>
  stats: Record<string, unknown>
  trading_signal: boolean
  order_execution: boolean
}

export interface CaptureOverlayItem {
  kind: string
  label: string
  priority: number
  source: string
  source_id: string | null
}

export interface CaptureRow {
  id: string
  opportunity_id: string | null
  symbol: string
  timeframe: string
  timestamp: string | null
  bar_time: number | null
  path: string
  telegram_path: string | null
  digest: string
  width: number | null
  height: number | null
  size_bytes: number | null
  candles_drawn: number | null
  overlays: { items?: CaptureOverlayItem[]; dropped?: string[] }
  state: string
}

export interface CapturesResponse {
  count: number
  captures: CaptureRow[]
  stats: Record<string, unknown>
  trading_signal: boolean
  note: string
}

export interface TelegramAlert {
  id: string
  alert_id: string | null
  opportunity_id: string | null
  capture_id: string | null
  symbol: string | null
  timeframe: string | null
  event_type: string | null
  message: string | null
  caption: string | null
  status: string
  mode: string | null
  attempts: number
  max_attempts: number
  last_error: string | null
  next_attempt_at: string | null
  created_at: string | null
  updated_at: string | null
  sent_at: string | null
  provider_message_id: number | null
}

export interface TelegramStatus {
  mode: 'NOT_CONFIGURED' | 'DRY_RUN' | 'REAL'
  enabled: boolean
  configured: boolean
  notifier: {
    status: string
    bot_token_present: boolean
    bot_token_preview: string
    chat_id_present: boolean
    chat_id_preview: string
    capabilities: string[]
  }
  queue: Record<string, number>
  dispatcher: {
    running: boolean
    enqueued: number
    duplicates_ignored: number
    skipped: number
    sent: number
    failed: number
    last_sent_at: string | null
    last_error: string | null
  }
  note: string
  trading_signal?: boolean
}

export interface TelegramHistoryResponse {
  count: number
  alerts: TelegramAlert[]
  counts: Record<string, number>
  trading_signal: boolean
  note: string
}
