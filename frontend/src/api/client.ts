/**
 * REST client.
 *
 * Every call returns the parsed payload or throws an ApiError that carries the
 * backend error code (e.g. DATA_UNAVAILABLE). The UI renders explicit states
 * instead of inventing values.
 */
import type {
  CandleResponse,
  CapturesResponse,
  ConfluenceReading,
  ConfluenceListResponse,
  ConfluenceResponse,
  DetectionHistoryResponse,
  DetectionsResponse,
  MarketStatus,
  Opportunity,
  OpportunitiesResponse,
  OpportunityOverview,
  PatternDetection,
  PatternParamsResponse,
  Quote,
  StructureResponse,
  SmcConfluenceResponse,
  SymbolListResponse,
  SystemStatus,
  TelegramHistoryResponse,
  TelegramStatus,
  Timeframe,
} from '../types/market'

export const API_BASE = '/api'

export class ApiError extends Error {
  status: number
  code: string
  detail: unknown

  constructor(message: string, status: number, code = 'API_ERROR', detail: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { Accept: 'application/json' },
      ...init,
    })
  } catch (error) {
    throw new ApiError(
      'NETWORK_UNAVAILABLE: the API is unreachable from this device',
      0,
      'NETWORK_UNAVAILABLE',
      error,
    )
  }

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = { raw: text }
    }
  }

  if (!response.ok) {
    const body = (payload ?? {}) as Record<string, unknown>
    const code = String(body.error ?? 'HTTP_ERROR')
    const message = String(body.message ?? body.detail ?? `HTTP ${response.status}`)
    throw new ApiError(message, response.status, code, payload)
  }

  return payload as T
}

export const api = {
  health: () => request<Record<string, unknown>>('/health'),
  status: () => request<SystemStatus>('/status'),
  symbols: () => request<SymbolListResponse>('/symbols'),
  quote: (symbol: string, timeframe: Timeframe) =>
    request<Quote>(`/market/${symbol}?timeframe=${timeframe}`),
  candles: (symbol: string, timeframe: Timeframe, limit = 300) =>
    request<CandleResponse>(`/candles/${symbol}/${timeframe}?limit=${limit}`),
  structure: (symbol: string, timeframe: Timeframe, limit = 300) =>
    request<StructureResponse>(`/structure/${symbol}/${timeframe}?limit=${limit}`),
  marketStatus: () => request<MarketStatus>('/market-status'),
  detections: (symbol?: string, timeframe?: Timeframe) =>
    request<DetectionsResponse>(
      `/detections${query({ symbol, timeframe })}`,
    ),
  activeDetections: (symbol?: string, timeframe?: Timeframe) =>
    request<DetectionsResponse>(`/detections/active${query({ symbol, timeframe })}`),
  detectionHistory: (params: {
    limit?: number
    symbol?: string
    timeframe?: Timeframe
    pattern?: string
    status?: string
  } = {}) => request<DetectionHistoryResponse>(`/detections/history${query(params)}`),
  detection: (id: string) => request<PatternDetection>(`/detections/${encodeURIComponent(id)}`),
  patternParams: () => request<PatternParamsResponse>('/patterns/params'),
  // Phase 3 - price action (same detection shape, same event bus)
  priceAction: (symbol?: string, timeframe?: Timeframe) =>
    request<DetectionsResponse>(`/price-action${query({ symbol, timeframe })}`),
  priceActionActive: (symbol?: string, timeframe?: Timeframe) =>
    request<DetectionsResponse>(`/price-action/active${query({ symbol, timeframe })}`),
  priceActionStructure: (symbol?: string, timeframe?: Timeframe) =>
    request<DetectionsResponse>(`/price-action/structure${query({ symbol, timeframe })}`),
  priceActionHistory: (params: {
    limit?: number
    symbol?: string
    timeframe?: Timeframe
    pattern?: string
    status?: string
  } = {}) => request<DetectionHistoryResponse>(`/price-action/history${query(params)}`),
  priceActionConfluence: (symbol?: string, timeframe?: Timeframe) =>
    request<ConfluenceResponse>(`/price-action/confluence${query({ symbol, timeframe })}`),
  priceActionParams: () => request<PatternParamsResponse>('/price-action/params'),
  // Phase 4 - SMC / ICT (same detection shape, same event bus)
  smcIct: (symbol?: string, timeframe?: Timeframe) =>
    request<DetectionsResponse>(`/smc-ict${query({ symbol, timeframe })}`),
  smcIctActive: (symbol?: string, timeframe?: Timeframe) =>
    request<DetectionsResponse>(`/smc-ict/active${query({ symbol, timeframe })}`),
  smcIctStructure: (symbol?: string, timeframe?: Timeframe) =>
    request<DetectionsResponse>(`/smc-ict/structure${query({ symbol, timeframe })}`),
  smcIctLiquidity: (symbol?: string, timeframe?: Timeframe) =>
    request<DetectionsResponse>(`/smc-ict/liquidity${query({ symbol, timeframe })}`),
  smcIctGaps: (symbol?: string, timeframe?: Timeframe) =>
    request<DetectionsResponse>(`/smc-ict/gaps${query({ symbol, timeframe })}`),
  smcIctBlocks: (symbol?: string, timeframe?: Timeframe) =>
    request<DetectionsResponse>(`/smc-ict/blocks${query({ symbol, timeframe })}`),
  smcIctRanges: (symbol?: string, timeframe?: Timeframe) =>
    request<DetectionsResponse>(`/smc-ict/ranges${query({ symbol, timeframe })}`),
  smcIctHistory: (params: {
    limit?: number
    symbol?: string
    timeframe?: Timeframe
    pattern?: string
    status?: string
  } = {}) => request<DetectionHistoryResponse>(`/smc-ict/history${query(params)}`),
  /** internal SMC confluence: its own shape (direction, families, items) */
  smcIctConfluence: (symbol?: string, timeframe?: Timeframe) =>
    request<SmcConfluenceResponse>(`/smc-ict/confluence${query({ symbol, timeframe })}`),
  smcIctDetection: (id: string) =>
    request<PatternDetection>(`/smc-ict/${encodeURIComponent(id)}`),
  smcIctParams: () => request<PatternParamsResponse>('/smc-ict/params'),
  // Phase 5 - confluence (multi-engine, multi-timeframe, explicable score)
  confluence: (symbol?: string, timeframe?: Timeframe, state?: string) =>
    request<ConfluenceListResponse>(`/confluence${query({ symbol, timeframe, state })}`),
  confluenceOverview: (symbol?: string, timeframe?: Timeframe) =>
    request<Record<string, unknown>>(`/confluence/overview${query({ symbol, timeframe })}`),
  confluenceDetail: (id: string) => request<ConfluenceReading>(`/confluence/${encodeURIComponent(id)}`),
  confluenceHistory: (params: { limit?: number; symbol?: string; timeframe?: Timeframe } = {}) =>
    request<{ count: number; confluences: ConfluenceReading[] }>(`/confluence/history${query(params)}`),
  confluenceParams: () => request<Record<string, unknown>>('/confluence/params'),
  // Phase 6 - opportunity (analytical direction: never an order)
  opportunities: (symbol?: string, timeframe?: Timeframe, direction?: string, state?: string) =>
    request<OpportunitiesResponse>(
      `/opportunities${query({ symbol, timeframe, direction, state })}`,
    ),
  opportunityOverview: (symbol?: string, timeframe?: Timeframe) =>
    request<OpportunityOverview>(`/opportunities/overview${query({ symbol, timeframe })}`),
  opportunityDetail: (id: string) => request<Opportunity>(`/opportunities/${encodeURIComponent(id)}`),
  opportunityHistory: (params: { limit?: number; symbol?: string; timeframe?: Timeframe } = {}) =>
    request<{ count: number; opportunities: Opportunity[] }>(`/opportunities/history${query(params)}`),
  opportunityParams: () => request<Record<string, unknown>>('/opportunities/params'),
  // Phase 7 - real chart captures (rendered from the real series)
  captures: (params: { limit?: number; symbol?: string; opportunity_id?: string } = {}) =>
    request<CapturesResponse>(`/captures${query(params)}`),
  captureStats: () => request<Record<string, unknown>>('/captures/stats'),
  // Phase 8 - telegram outbox (never a secret in these payloads)
  telegramStatus: () => request<TelegramStatus>('/telegram/status'),
  telegramHistory: (params: { limit?: number; status?: string } = {}) =>
    request<TelegramHistoryResponse>(`/telegram/history${query(params)}`),
  telegramParams: () => request<Record<string, unknown>>('/telegram/params'),
}

/** URL of a real capture file, served by the backend (PNG). */
export function captureFileUrl(captureId: string, tier: 'phone' | 'telegram' = 'telegram'): string {
  return `${API_BASE}/captures/${encodeURIComponent(captureId)}/file?tier=${tier}`
}

/** Build a query string, skipping empty values (never invents a filter). */
function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

/** Build the WebSocket URL for the live stream (same origin as the page). */
export function streamUrl(symbol: string, timeframe: Timeframe): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  return `${protocol}//${host}${API_BASE}/stream?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}`
}
