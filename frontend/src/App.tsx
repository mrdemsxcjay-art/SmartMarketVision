import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from './api/client'
import { useMarketStream } from './hooks/useMarketStream'
import { Header } from './components/Header'
import { SymbolSelector, TimeframeSelector } from './components/Selectors'
import { ChartPanel, MAX_OVERLAYS } from './components/ChartPanel'
import { DataStatusPanel, Footer, MarketSummary, StructurePanel } from './components/Panels'
import { PatternsPanel } from './components/PatternsPanel'
import { PriceActionPanel } from './components/PriceActionPanel'
import { SmcIctPanel } from './components/SmcIctPanel'
import { AlertsPanel, ConfluencePanel, MarketOverview, OpportunityPanel } from './components/SignalPanels'
import type {
  CandleResponse,
  CaptureRow,
  ConfluenceReading,
  ConfluenceListResponse,
  ConfluenceResponse,
  SmcConfluenceResponse,
  DetectionHistoryResponse,
  DetectionsResponse,
  PatternDetection,
  OpportunitiesResponse,
  Opportunity,
  OpportunityOverview,
  PatternEventMetadata,
  Quote,
  StructureResponse,
  SymbolInfo,
  SystemStatus,
  TelegramHistoryResponse,
  TelegramStatus,
  Timeframe,
} from './types/market'

/** Parse any ISO timestamp sent by the API (it may use +00:00 or Z). */
function parseTimestamp(value: unknown): string | null {
  if (typeof value !== 'string' || !value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

const DEFAULT_SYMBOL = 'EURUSD'
const DEFAULT_TIMEFRAME: Timeframe = 'M15'
const CANDLE_LIMIT = 300

/** Which detections the dashboard shows and draws (Phase 3 filter). */
export type DetectionFilter = 'TOUS' | 'CHARTISTE' | 'PRICE_ACTION' | 'SMC_ICT'

export default function App() {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([])
  const [symbol, setSymbol] = useState<string>(DEFAULT_SYMBOL)
  const [timeframe, setTimeframe] = useState<Timeframe>(DEFAULT_TIMEFRAME)

  const [candleResponse, setCandleResponse] = useState<CandleResponse | null>(null)
  const [structure, setStructure] = useState<StructureResponse | null>(null)
  const [quote, setQuote] = useState<Quote | null>(null)
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [detections, setDetections] = useState<DetectionsResponse | null>(null)
  const [history, setHistory] = useState<DetectionHistoryResponse | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [selectedDetection, setSelectedDetection] = useState<PatternDetection | null>(null)
  // Phase 3 - price action (same detection shape, same stream, separate state)
  const [priceAction, setPriceAction] = useState<DetectionsResponse | null>(null)
  const [priceActionStructure, setPriceActionStructure] = useState<DetectionsResponse | null>(null)
  const [priceActionHistory, setPriceActionHistory] = useState<DetectionHistoryResponse | null>(null)
  const [priceActionHistoryError, setPriceActionHistoryError] = useState<string | null>(null)
  const [confluence, setConfluence] = useState<ConfluenceResponse | null>(null)
  // Phase 4 - SMC / ICT (same detection shape, same stream, separate state)
  const [smcIct, setSmcIct] = useState<DetectionsResponse | null>(null)
  const [smcIctStructure, setSmcIctStructure] = useState<DetectionsResponse | null>(null)
  const [smcIctHistory, setSmcIctHistory] = useState<DetectionHistoryResponse | null>(null)
  const [smcIctHistoryError, setSmcIctHistoryError] = useState<string | null>(null)
  const [smcIctConfluence, setSmcIctConfluence] = useState<SmcConfluenceResponse | null>(null)
  const [smcIctError, setSmcIctError] = useState<string | null>(null)
  // Phase 5-8 - confluence, opportunity, capture, telegram
  const [phase5, setPhase5] = useState<ConfluenceListResponse | null>(null)
  const [phase5Current, setPhase5Current] = useState<ConfluenceReading | null>(null)
  const [phase5Error, setPhase5Error] = useState<string | null>(null)
  const [opportunities, setOpportunities] = useState<OpportunitiesResponse | null>(null)
  const [opportunityOverview, setOpportunityOverview] = useState<OpportunityOverview | null>(null)
  const [opportunityError, setOpportunityError] = useState<string | null>(null)
  const [captures, setCaptures] = useState<CaptureRow[]>([])
  const [telegram, setTelegram] = useState<TelegramStatus | null>(null)
  const [alerts, setAlerts] = useState<TelegramHistoryResponse | null>(null)
  const [alertsError, setAlertsError] = useState<string | null>(null)
  const [filter, setFilter] = useState<DetectionFilter>('TOUS')
  const [patternFlash, setPatternFlash] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [apiError, setApiError] = useState<string | null>(null)

  const stream = useMarketStream(symbol, timeframe)
  const lastRefreshedRef = useRef<string>('')

  const digits = useMemo(() => {
    const info = symbols.find((item) => item.symbol === symbol)
    return info?.digits ?? quote?.digits ?? (symbol.endsWith('JPY') ? 3 : 5)
  }, [symbols, symbol, quote])

  // --------------------------------------------------------------- loading
  const loadSymbols = useCallback(async () => {
    try {
      const payload = await api.symbols()
      setSymbols(payload.symbols)
      if (payload.symbols.length && !payload.symbols.some((item) => item.symbol === symbol)) {
        setSymbol(payload.symbols[0].symbol)
      }
    } catch (error) {
      setApiError(error instanceof ApiError ? error.message : String(error))
    }
  }, [symbol])

  const loadMarketData = useCallback(async () => {
    setLoading(true)
    const [candlesResult, structureResult, quoteResult] = await Promise.allSettled([
      api.candles(symbol, timeframe, CANDLE_LIMIT),
      api.structure(symbol, timeframe, CANDLE_LIMIT),
      api.quote(symbol, timeframe),
    ])

    if (candlesResult.status === 'fulfilled') {
      setCandleResponse(candlesResult.value)
      setApiError(null)
    } else {
      // DATA UNAVAILABLE (503) or network failure: no chart data, explicit state.
      setCandleResponse(null)
      setApiError(
        candlesResult.reason instanceof ApiError
          ? `${candlesResult.reason.code}: ${candlesResult.reason.message}`
          : String(candlesResult.reason),
      )
    }

    setStructure(structureResult.status === 'fulfilled' ? structureResult.value : null)
    setQuote(quoteResult.status === 'fulfilled' ? quoteResult.value : null)
    setLoading(false)
  }, [symbol, timeframe])

  const loadSystemStatus = useCallback(async () => {
    try {
      const payload = await api.status()
      setStatus(payload)
    } catch {
      setStatus(null)
    }
  }, [])

  const loadDetections = useCallback(async () => {
    try {
      setDetections(await api.detections(symbol, timeframe))
    } catch {
      setDetections(null)
    }
  }, [symbol, timeframe])

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await api.detectionHistory({ limit: 40, symbol, timeframe }))
      setHistoryError(null)
    } catch (error) {
      setHistory(null)
      setHistoryError(
        error instanceof ApiError ? `${error.code}: ${error.message}` : 'HISTORIQUE INDISPONIBLE',
      )
    }
  }, [symbol, timeframe])

  const loadPriceAction = useCallback(async () => {
    const [detectionsResult, structureResult, historyResult, confluenceResult] = await Promise.allSettled([
      api.priceAction(symbol, timeframe),
      api.priceActionStructure(symbol, timeframe),
      api.priceActionHistory({ limit: 40, symbol, timeframe }),
      api.priceActionConfluence(symbol, timeframe),
    ])
    setPriceAction(detectionsResult.status === 'fulfilled' ? detectionsResult.value : null)
    setPriceActionStructure(structureResult.status === 'fulfilled' ? structureResult.value : null)
    if (historyResult.status === 'fulfilled') {
      setPriceActionHistory(historyResult.value)
      setPriceActionHistoryError(null)
    } else {
      setPriceActionHistory(null)
      setPriceActionHistoryError(
        historyResult.reason instanceof ApiError
          ? `${historyResult.reason.code}: ${historyResult.reason.message}`
          : 'HISTORIQUE PRICE ACTION INDISPONIBLE',
      )
    }
    setConfluence(confluenceResult.status === 'fulfilled' ? confluenceResult.value : null)
  }, [symbol, timeframe])

  const loadSmcIct = useCallback(async () => {
    const [detectionsResult, structureResult, historyResult, confluenceResult] =
      await Promise.allSettled([
        api.smcIct(symbol, timeframe),
        api.smcIctStructure(symbol, timeframe),
        api.smcIctHistory({ limit: 40, symbol, timeframe }),
        api.smcIctConfluence(symbol, timeframe),
      ])
    if (detectionsResult.status === 'fulfilled') {
      setSmcIct(detectionsResult.value)
      setSmcIctError(null)
    } else {
      // an unreachable or failing engine must say so: "no object" is not the
      // same statement as "the engine could not be read"
      setSmcIct(null)
      setSmcIctError(
        detectionsResult.reason instanceof ApiError
          ? `${detectionsResult.reason.code}: ${detectionsResult.reason.message}`
          : 'SMC / ICT INDISPONIBLE',
      )
    }
    setSmcIctStructure(structureResult.status === 'fulfilled' ? structureResult.value : null)
    if (historyResult.status === 'fulfilled') {
      setSmcIctHistory(historyResult.value)
      setSmcIctHistoryError(null)
    } else {
      setSmcIctHistory(null)
      setSmcIctHistoryError(
        historyResult.reason instanceof ApiError
          ? `${historyResult.reason.code}: ${historyResult.reason.message}`
          : 'HISTORIQUE SMC / ICT INDISPONIBLE',
      )
    }
    setSmcIctConfluence(confluenceResult.status === 'fulfilled' ? confluenceResult.value : null)
  }, [symbol, timeframe])

  const loadSignalChain = useCallback(async () => {
    const [confluenceResult, opportunityResult, overviewResult, captureResult, statusResult, historyResult] =
      await Promise.allSettled([
        api.confluence(symbol, timeframe),
        api.opportunities(symbol, timeframe),
        api.opportunityOverview(symbol, timeframe),
        api.captures({ limit: 20 }),
        api.telegramStatus(),
        api.telegramHistory({ limit: 25 }),
      ])

    if (confluenceResult.status === 'fulfilled') {
      setPhase5(confluenceResult.value)
      setPhase5Error(null)
      setPhase5Current((previous) =>
        previous && confluenceResult.value.confluences.some((row) => row.id === previous.id)
          ? previous
          : confluenceResult.value.confluences[0] ?? null,
      )
    } else {
      setPhase5(null)
      setPhase5Error(
        confluenceResult.reason instanceof ApiError
          ? `${confluenceResult.reason.code}: ${confluenceResult.reason.message}`
          : 'CONFLUENCE INDISPONIBLE',
      )
    }

    if (opportunityResult.status === 'fulfilled') {
      setOpportunities(opportunityResult.value)
      setOpportunityError(null)
    } else {
      setOpportunities(null)
      setOpportunityError(
        opportunityResult.reason instanceof ApiError
          ? `${opportunityResult.reason.code}: ${opportunityResult.reason.message}`
          : 'OPPORTUNITÉS INDISPONIBLES',
      )
    }

    setOpportunityOverview(overviewResult.status === 'fulfilled' ? overviewResult.value : null)
    setCaptures(captureResult.status === 'fulfilled' ? captureResult.value.captures : [])
    setTelegram(statusResult.status === 'fulfilled' ? statusResult.value : null)
    if (historyResult.status === 'fulfilled') {
      setAlerts(historyResult.value)
      setAlertsError(null)
    } else {
      setAlerts(null)
      setAlertsError('HISTORIQUE DES ALERTES INDISPONIBLE')
    }
  }, [symbol, timeframe])

  useEffect(() => {
    void loadSymbols()
  }, [loadSymbols])

  useEffect(() => {
    void loadMarketData()
    void loadSystemStatus()
    void loadDetections()
    void loadHistory()
    void loadPriceAction()
    void loadSmcIct()
    void loadSignalChain()
  }, [
    loadMarketData,
    loadSystemStatus,
    loadDetections,
    loadHistory,
    loadPriceAction,
    loadSmcIct,
    loadSignalChain,
  ])

  // Poll the REST snapshots (safety net) and the system card periodically.
  useEffect(() => {
    const marketTimer = window.setInterval(() => void loadMarketData(), 30000)
    const statusTimer = window.setInterval(() => void loadSystemStatus(), 20000)
    // the signal chain is polled too: an alert queued while the tab was asleep
    // must appear without a reload, even if the socket missed the event.
    const signalTimer = window.setInterval(() => void loadSignalChain(), 25000)
    return () => {
      window.clearInterval(marketTimer)
      window.clearInterval(statusTimer)
      window.clearInterval(signalTimer)
    }
  }, [loadMarketData, loadSystemStatus, loadSignalChain])

  // A live candle update refreshes the quote header; a closed candle refreshes the structure.
  useEffect(() => {
    const event = stream.lastEvent
    if (!event) return
    if (event.event_type === 'MARKET_UPDATE' && event.symbol === symbol && event.metadata) {
      const metadata = event.metadata as Record<string, unknown>
      const candleTime = parseTimestamp(metadata.candle_time)
      setQuote((previous) => {
        if (!previous) return previous
        const price = event.price ?? previous.price
        const prevClose = previous.prev_close
        const change = price !== null && prevClose !== null ? price - prevClose : previous.change
        const changePercent =
          change !== null && prevClose ? (change / prevClose) * 100 : previous.change_percent
        return {
          ...previous,
          price,
          change,
          change_percent: changePercent,
          data_state: (metadata.data_state as Quote['data_state']) ?? previous.data_state,
          candle_time: candleTime ?? previous.candle_time,
          last_update: event.timestamp,
        }
      })
    }
    if (event.event_type === 'CANDLE_CLOSED' && event.symbol === symbol) {
      void loadMarketData()
    }
    if (event.event_type === 'STRUCTURE_UPDATE' && event.symbol === symbol) {
      const metadata = event.metadata as Record<string, unknown>
      const labels = (metadata.labels as string[]) ?? []
      setStructure((previous) =>
        previous
          ? {
              ...previous,
              trend: (metadata.trend as StructureResponse['trend']) ?? previous.trend,
              recent_labels: labels.length ? labels : previous.recent_labels,
              evaluated_at: event.timestamp,
            }
          : previous,
      )
    }
    if (event.event_type === 'DETECTIONS_SNAPSHOT') {
      // sent by the backend right after a (re)connection: the dashboard shows
      // the current state immediately instead of waiting for the next detection
      const metadata = event.metadata as Record<string, unknown>
      const rows = (metadata.detections as PatternDetection[]) ?? []
      setDetections((previous) => ({
        status: String(metadata.status ?? 'NO ACTIVE DETECTION'),
        detections: rows,
        counts: (metadata.counts as Record<string, number>) ?? previous?.counts ?? {},
        engines: (metadata.engines as Record<string, string>) ?? previous?.engines ?? {},
        stats: metadata.stats as Record<string, unknown> | undefined,
      }))
      setHistory((previous) =>
        previous
          ? { ...previous, detections: rows.length ? rows : previous.detections, count: Math.max(previous.count, rows.length) }
          : previous,
      )
    }
    if (event.event_type.startsWith('PATTERN_') || event.event_type === 'BREAKOUT_DETECTED' || event.event_type === 'RETEST_DETECTED') {
      const metadata = event.metadata as unknown as PatternEventMetadata
      const detection = metadata?.detection
      if (detection) {
        // realtime: the detection appears without any page reload
        setDetections((previous) => {
          const rows = previous?.detections ?? []
          const others = rows.filter((item) => item.id !== detection.id)
          return {
            status: 'ACTIVE DETECTIONS',
            detections: [detection, ...others],
            counts: previous?.counts ?? {},
            engines: previous?.engines ?? { CHART_PATTERN_ENGINE: 'ENABLED' },
            stats: previous?.stats,
          }
        })
        setHistory((previous) => {
          if (!previous) return previous
          const rows = previous.detections.filter((item) => item.id !== detection.id)
          return { ...previous, count: rows.length + 1, detections: [detection, ...rows] }
        })
        setSelectedDetection((previous) => (previous && previous.id === detection.id ? detection : previous))
        setPatternFlash(
          `${event.event_type} · ${detection.pattern} ${detection.symbol} ${detection.timeframe}`,
        )
      }
    }
    if (event.event_type === 'PRICE_ACTION_SNAPSHOT') {
      // same mechanism as DETECTIONS_SNAPSHOT, for the Phase 3 engine
      const metadata = event.metadata as Record<string, unknown>
      const rows = (metadata.detections as PatternDetection[]) ?? []
      const states = (metadata.structure as PatternDetection[]) ?? []
      setPriceAction({
        status: String(metadata.status ?? 'NO ACTIVE PRICE ACTION'),
        detections: rows,
        counts: (metadata.counts as Record<string, number>) ?? {},
        engines: (metadata.engines as Record<string, string>) ?? {},
        stats: metadata.stats as Record<string, unknown> | undefined,
      })
      setPriceActionStructure((previous) => ({
        status: previous?.status ?? 'STRUCTURE STATES',
        detections: states,
        counts: previous?.counts ?? {},
        engines: previous?.engines ?? {},
      }))
    }
    if (
      event.event_type === 'PRICE_ACTION_DETECTED' ||
      event.event_type === 'PRICE_ACTION_CONFIRMED' ||
      event.event_type === 'PRICE_ACTION_INVALIDATED' ||
      event.event_type === 'PRICE_ACTION_EXPIRED' ||
      event.event_type === 'FAILED_BREAKOUT'
    ) {
      const metadata = event.metadata as unknown as PatternEventMetadata
      const detection = metadata?.detection
      if (detection) {
        setPriceAction((previous) => {
          const rows = previous?.detections ?? []
          const others = rows.filter((item) => item.id !== detection.id)
          const next = [detection, ...others]
          return {
            status: 'ACTIVE PRICE ACTION',
            detections: next,
            counts: previous?.counts ?? {},
            engines: previous?.engines ?? { PRICE_ACTION_ENGINE: 'ENABLED' },
            stats: previous?.stats,
          }
        })
        setPriceActionStructure((previous) => {
          const isState = detection.pattern === 'IMPULSION' || detection.pattern === 'CONSOLIDATION'
          const rows = (previous?.detections ?? []).filter((item) => item.id !== detection.id)
          return {
            status: previous?.status ?? 'STRUCTURE STATES',
            detections: isState ? [detection, ...rows] : rows,
            counts: previous?.counts ?? {},
            engines: previous?.engines ?? {},
          }
        })
        setPriceActionHistory((previous) => {
          if (!previous) return previous
          const rows = previous.detections.filter((item) => item.id !== detection.id)
          return { ...previous, count: rows.length + 1, detections: [detection, ...rows] }
        })
        if (selectedDetection && selectedDetection.id === detection.id) setSelectedDetection(detection)
        setPatternFlash(
          `${event.event_type} · ${detection.pattern} ${detection.symbol} ${detection.timeframe}`,
        )
      }
    }
    if (event.event_type === 'SMC_ICT_SNAPSHOT') {
      // same mechanism as the other snapshots: no reload needed after a reconnect
      const metadata = event.metadata as Record<string, unknown>
      const rows = (metadata.detections as PatternDetection[]) ?? []
      setSmcIct({
        status: String(metadata.status ?? 'NO ACTIVE SMC ICT'),
        detections: rows,
        counts: (metadata.counts as Record<string, number>) ?? {},
        engines: (metadata.engines as Record<string, string>) ?? {},
        stats: metadata.stats as Record<string, unknown> | undefined,
      })
      setSmcIctStructure((previous) => ({
        status: previous?.status ?? 'SMC STRUCTURE',
        detections: rows.filter(
          (row) => (row.evidence_points as { family?: string })?.family === 'STRUCTURE',
        ),
        counts: previous?.counts ?? {},
        engines: previous?.engines ?? {},
      }))
      if (metadata.confluence) {
        // internal SMC confluence: its own shape (direction, families, items)
        setSmcIctConfluence(metadata.confluence as SmcConfluenceResponse)
      }
    }
    if (event.event_type.startsWith('SMC_')) {
      const metadata = event.metadata as unknown as PatternEventMetadata
      const detection = metadata?.detection
      if (detection) {
        setSmcIct((previous) => {
          const rows = previous?.detections ?? []
          const others = rows.filter((item) => item.id !== detection.id)
          return {
            status: 'ACTIVE SMC ICT',
            detections: [detection, ...others],
            counts: previous?.counts ?? {},
            engines: previous?.engines ?? { SMC_ICT_ENGINE: 'ENABLED' },
            stats: previous?.stats,
          }
        })
        setSmcIctStructure((previous) => {
          const isStructure =
            (detection.evidence_points as { family?: string })?.family === 'STRUCTURE'
          const rows = (previous?.detections ?? []).filter((item) => item.id !== detection.id)
          return {
            status: previous?.status ?? 'SMC STRUCTURE',
            detections: isStructure ? [detection, ...rows] : rows,
            counts: previous?.counts ?? {},
            engines: previous?.engines ?? {},
          }
        })
        setSmcIctHistory((previous) => {
          if (!previous) return previous
          const rows = previous.detections.filter((item) => item.id !== detection.id)
          return { ...previous, count: rows.length + 1, detections: [detection, ...rows] }
        })
        if (selectedDetection && selectedDetection.id === detection.id) {
          setSelectedDetection(detection)
        }
        setPatternFlash(
          `${event.event_type} · ${detection.pattern} ${detection.symbol} ${detection.timeframe}`,
        )
      }
    }
    if (event.event_type === 'CONFLUENCE_SNAPSHOT') {
      // reconnection: the dashboard shows the confluences already known by the engine
      const metadata = event.metadata as Record<string, unknown>
      const rows = (metadata.confluences as ConfluenceReading[]) ?? []
      setPhase5((previous) => ({
        count: rows.length,
        symbol,
        timeframe,
        confluences: rows,
        counts: (metadata.counts as Record<string, number>) ?? previous?.counts ?? {},
        by_direction: (metadata.by_direction as Record<string, number>) ?? previous?.by_direction ?? {},
        engines: previous?.engines ?? {},
        stats: (metadata.stats as Record<string, unknown>) ?? previous?.stats ?? {},
        trading_signal: false,
      }))
      setPhase5Current((previous) =>
        previous && rows.some((row) => row.id === previous.id) ? previous : rows[0] ?? null,
      )
      setPhase5Error(null)
    }
    if (
      event.event_type === 'CONFLUENCE_DETECTED' ||
      event.event_type === 'CONFLUENCE_UPDATED' ||
      event.event_type === 'CONFLUENCE_CONTRADICTED' ||
      event.event_type === 'CONFLUENCE_EXPIRED'
    ) {
      const metadata = event.metadata as Record<string, unknown>
      const group = metadata.confluence as ConfluenceReading | undefined
      if (group) {
        setPhase5((previous) => {
          const rows = previous?.confluences ?? []
          const others = rows.filter((row) => row.id !== group.id)
          return {
            count: others.length + 1,
            symbol: group.symbol,
            timeframe: group.timeframe,
            confluences: [group, ...others],
            counts: previous?.counts ?? {},
            by_direction: previous?.by_direction ?? {},
            engines: previous?.engines ?? {},
            stats: previous?.stats ?? {},
            trading_signal: false,
          }
        })
        setPhase5Current((previous) => (previous && previous.id === group.id ? group : previous ?? group))
      }
    }
    if (event.event_type === 'OPPORTUNITY_SNAPSHOT') {
      const metadata = event.metadata as Record<string, unknown>
      const rows = (metadata.opportunities as Opportunity[]) ?? []
      setOpportunities((previous) => ({
        count: rows.length,
        symbol,
        timeframe,
        opportunities: rows,
        counts: (metadata.counts as Record<string, number>) ?? previous?.counts ?? {},
        directions: (metadata.by_direction as Record<string, number>) ?? previous?.directions ?? {},
        engines: previous?.engines ?? {},
        stats: (metadata.stats as Record<string, unknown>) ?? previous?.stats ?? {},
        trading_signal: false,
        order_execution: false,
      }))
      setOpportunityOverview((metadata.overview as OpportunityOverview) ?? null)
      setOpportunityError(null)
    }
    if (
      event.event_type === 'OPPORTUNITY_CREATED' ||
      event.event_type === 'OPPORTUNITY_CONFIRMED' ||
      event.event_type === 'OPPORTUNITY_WEAKENED' ||
      event.event_type === 'OPPORTUNITY_INVALIDATED' ||
      event.event_type === 'OPPORTUNITY_EXPIRED'
    ) {
      const metadata = event.metadata as Record<string, unknown>
      const opportunity = metadata.opportunity as Opportunity | undefined
      if (opportunity) {
        setOpportunities((previous) => {
          const rows = previous?.opportunities ?? []
          const others = rows.filter((row) => row.id !== opportunity.id)
          return {
            count: others.length + 1,
            symbol: opportunity.symbol,
            timeframe: opportunity.timeframe,
            opportunities: [opportunity, ...others],
            counts: previous?.counts ?? {},
            directions: previous?.directions ?? {},
            engines: previous?.engines ?? {},
            stats: previous?.stats ?? {},
            trading_signal: false,
            order_execution: false,
          }
        })
        setOpportunityOverview((previous) => ({
          symbol: opportunity.symbol,
          timeframe: opportunity.timeframe,
          direction: opportunity.direction,
          state: opportunity.state,
          score: opportunity.score,
          max_score: opportunity.max_score,
          opportunity_id: opportunity.id,
          confluence_id: opportunity.confluence_id,
          reference_price: opportunity.reference_price,
          no_trade_reason: opportunity.no_trade_reason,
          tracked: previous?.tracked ?? 1,
          named: (previous?.named ?? 0) + (opportunity.direction === 'BUY' || opportunity.direction === 'SELL' ? 1 : 0),
        }))
      }
    }
    if (event.event_type === 'CAPTURE_READY') {
      const metadata = event.metadata as Record<string, unknown>
      const row = metadata as unknown as CaptureRow
      if (row && row.id) {
        setCaptures((previous) => {
          const others = previous.filter((item) => item.id !== row.id)
          return [row, ...others].slice(0, 20)
        })
      }
      // the alert history gains the capture link as soon as it exists
      void loadSignalChain()
    }
    if (event.event_type === 'ALERT_QUEUED' || event.event_type === 'ALERT_SENT' || event.event_type === 'ALERT_FAILED') {
      void loadSignalChain()
    }
    if (event.event_type === 'SYSTEM_STATUS') {
      const metadata = event.metadata as Record<string, unknown>
      if (metadata.scanner) {
        setStatus((previous) =>
          previous
            ? {
                ...previous,
                scanner: {
                  ...previous.scanner,
                  running: String(metadata.scanner) === 'RUNNING',
                  pairs_scanned_last_tick: Number(metadata.pairs_scanned ?? previous.scanner.pairs_scanned_last_tick),
                  pairs_failed_last_tick: Number(metadata.pairs_failed ?? previous.scanner.pairs_failed_last_tick),
                },
              }
            : previous,
        )
      }
    }
    lastRefreshedRef.current = event.timestamp
  }, [stream.lastEvent, symbol, loadMarketData, loadSignalChain, selectedDetection])

  const showChartiste = filter === 'TOUS' || filter === 'CHARTISTE'
  const showPriceAction = filter === 'TOUS' || filter === 'PRICE_ACTION'
  const showSmcIct = filter === 'TOUS' || filter === 'SMC_ICT'

  const categoryVisible = (category: string) =>
    (category === 'CHARTISTE' && showChartiste) ||
    (category === 'PRICE_ACTION' && showPriceAction) ||
    (category === 'SMC_ICT' && showSmcIct)

  /**
   * Everything drawn on the chart. The selection always comes first so the
   * ChartPanel keeps it as the reference overlay; the SMC/ICT objects come
   * before the price-action ones because they are the Phase 4 subject. The
   * chart itself caps the number of layers (readability, section 28).
   */
  const chartOverlays = [
    ...(selectedDetection && categoryVisible(selectedDetection.category) ? [selectedDetection] : []),
    ...(showSmcIct ? (smcIct?.detections ?? []).slice(0, 2) : []),
    ...(showPriceAction ? (priceAction?.detections ?? []).slice(0, 2) : []),
  ]

  const handleSymbolChange = (next: string) => {
    if (next === symbol) return
    setSymbol(next)
    setCandleResponse(null)
    setStructure(null)
  }

  const handleTimeframeChange = (next: Timeframe) => {
    if (next === timeframe) return
    setTimeframe(next)
    setCandleResponse(null)
    setStructure(null)
  }

  return (
    <div className="app-shell">
      <Header
        streamStatus={stream.status}
        lastMessageAt={stream.lastMessageAt}
        provider={status?.provider ?? quote?.provider ?? '…'}
        serverTime={status?.server_time_utc ?? null}
        scannerRunning={status?.scanner.running ?? false}
      />

      {apiError && (
        <div className="banner banner-warn" role="status" data-testid="api-error">
          {apiError}
        </div>
      )}

      {patternFlash && (
        <div className="banner banner-pattern" role="status" data-testid="pattern-flash">
          <span>{patternFlash}</span>
          <button type="button" className="ghost-button small" onClick={() => setPatternFlash(null)}>
            FERMER
          </button>
        </div>
      )}

      <main className="app-main">
        <MarketSummary quote={quote} digits={digits} />

        <SymbolSelector symbols={symbols} selected={symbol} onSelect={handleSymbolChange} />
        <TimeframeSelector selected={timeframe} onSelect={handleTimeframeChange} />

        <div className="filter-bar" data-testid="detection-filter" role="group" aria-label="Filtre des détections">
          {(['TOUS', 'CHARTISTE', 'PRICE_ACTION', 'SMC_ICT'] as DetectionFilter[]).map((value) => (
            <button
              key={value}
              type="button"
              className={`filter-button ${filter === value ? 'active' : ''}`}
              onClick={() => setFilter(value)}
              aria-pressed={filter === value}
              data-testid={`filter-${value}`}
            >
              {value === 'TOUS'
                ? 'TOUS'
                : value === 'CHARTISTE'
                  ? 'CHARTISTE'
                  : value === 'PRICE_ACTION'
                    ? 'PRICE ACTION'
                    : 'SMC / ICT'}
            </button>
          ))}
          <span className="muted filter-note" data-testid="filter-counts">
            {[
              showChartiste ? `${detections?.detections.length ?? 0} chartiste(s)` : '',
              showPriceAction ? `${priceAction?.detections.length ?? 0} price action` : '',
              showSmcIct ? `${smcIct?.detections.length ?? 0} smc/ict` : '',
            ]
              .filter(Boolean)
              .join(' · ')}
          </span>
        </div>

        <ChartPanel
          candles={candleResponse?.candles ?? []}
          digits={digits}
          dataState={candleResponse?.data_state ?? (apiError ? 'DATA_UNAVAILABLE' : 'CONNECTED')}
          symbol={symbol}
          timeframe={timeframe}
          loading={loading}
          overlays={chartOverlays}
          banner={selectedDetection}
          onClearDetection={() => setSelectedDetection(null)}
        />

        {showChartiste && (
          <div className="grid-2">
            <StructurePanel structure={structure} />
            <PatternsPanel
              detections={detections}
              history={history}
              selectedId={selectedDetection?.id ?? null}
              onSelect={setSelectedDetection}
              historyError={historyError}
            />
          </div>
        )}

        {showPriceAction && (
          <PriceActionPanel
            detections={priceAction}
            structure={priceActionStructure}
            history={priceActionHistory}
            confluence={confluence}
            selectedId={selectedDetection?.id ?? null}
            onSelect={setSelectedDetection}
            historyError={priceActionHistoryError}
          />
        )}

        {showSmcIct && (
          <SmcIctPanel
            detections={smcIct}
            structure={smcIctStructure}
            history={smcIctHistory}
            confluence={smcIctConfluence}
            error={smcIctError}
            selectedId={selectedDetection?.id ?? null}
            onSelect={setSelectedDetection}
            historyError={smcIctHistoryError}
            maxOverlays={MAX_OVERLAYS}
          />
        )}

        <MarketOverview
          symbol={symbol}
          timeframe={timeframe}
          price={quote?.price ?? candleResponse?.candles.at(-1)?.close ?? null}
          digits={digits}
          marketState={candleResponse?.data_state ?? null}
          confluence={phase5Current}
          overview={opportunityOverview}
        />

        <ConfluencePanel
          confluence={phase5}
          current={phase5Current}
          error={phase5Error}
          onSelect={setPhase5Current}
        />

        <OpportunityPanel
          opportunities={opportunities}
          overview={opportunityOverview}
          error={opportunityError}
        />

        <AlertsPanel
          telegram={telegram}
          history={alerts}
          captures={captures}
          symbol={symbol}
          error={alertsError}
        />

        <DataStatusPanel status={status} candleResponse={candleResponse} />
      </main>

      <Footer status={status} />
    </div>
  )
}
