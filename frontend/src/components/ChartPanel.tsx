/**
 * Candlestick chart (Lightweight Charts v4).
 *
 * Draws only what really exists: real candles, plus - since Phase 2 - the
 * geometry of the detections the user explicitly selected (chartist, price
 * action) and - since Phase 4 - the SMC/ICT geometry: broken swing levels,
 * liquidity levels (estimates), dealing range high / equilibrium / low, order
 * block / FVG / breaker rectangles, sweep markers. Every point comes from the
 * detection payload; nothing is interpolated or invented here.
 */
import { useEffect, useRef, useState } from 'react'
import {
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { Candle, DataState, PatternDetection } from '../types/market'
import { ZonePrimitive, type ZoneRect } from './zonePrimitive'

export interface ChartReadyApi {
  chart: IChartApi
  candleSeries: ISeriesApi<'Candlestick'>
  /** horizontal level (support, resistance, swing, order block edge...) */
  addPriceLine: (price: number, title: string, color?: string) => void
  /** trendline / ray between two points */
  addLine: (points: { time: number; value: number }[], color?: string) => void
  /** detection markers (triangle/arrow flags) */
  setMarkers: (markers: { time: UTCTimestamp; position: 'aboveBar' | 'belowBar'; color: string; shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown'; text?: string }[]) => void
  /**
   * Attach a real rectangle (order block, FVG, breaker, premium/discount band).
   * Implemented in Phase 4 with a canvas primitive: every corner comes from the
   * payload, nothing is interpolated.
   */
  addZone: (zone: ZoneRect) => void
}

/**
 * How many overlays are drawn at once. Each detection brings several price
 * levels, so drawing five of them stacked ~30 dashed lines on the same price
 * area with overlapping axis labels: unreadable. Three keep the context while
 * staying legible; any detection remains drawable by selecting it in the panel.
 */
export const MAX_OVERLAYS = 3

interface Props {
  candles: Candle[]
  digits: number
  dataState: DataState
  symbol: string
  timeframe: string
  loading: boolean
  onReady?: (api: ChartReadyApi) => void
  /** detections drawn on the chart (chartist and/or price action) */
  overlays?: PatternDetection[]
  /** the detection described under the chart (the one the user selected) */
  banner?: PatternDetection | null
  onClearDetection?: () => void
}

export function ChartPanel({
  candles,
  digits,
  dataState,
  symbol,
  timeframe,
  loading,
  onReady,
  overlays = [],
  banner = null,
  onClearDetection,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const readyRef = useRef(false)
  const [chartReady, setChartReady] = useState(0)
  // everything the overlay created, so it can be removed on selection change
  const overlayRef = useRef<{
    priceLines: unknown[]
    series: ISeriesApi<'Line'>[]
    primitives: ZonePrimitive[]
  }>({
    priceLines: [],
    series: [],
    primitives: [],
  })

  // ---------------------------------------------------------------- create
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: '#0b1220' },
        textColor: '#9fb0c9',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(120,140,180,0.08)' },
        horzLines: { color: 'rgba(120,140,180,0.08)' },
      },
      rightPriceScale: { borderColor: 'rgba(120,140,180,0.25)', scaleMargins: { top: 0.12, bottom: 0.12 } },
      timeScale: { borderColor: 'rgba(120,140,180,0.25)', timeVisible: true, secondsVisible: false, rightOffset: 3 },
      crosshair: { mode: CrosshairMode.Normal },
      handleScale: { axisPressedMouseMove: { time: true, price: false } },
      autoSize: true,
    })

    const series = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
      priceFormat: { type: 'price', precision: digits, minMove: 1 / 10 ** digits },
    })

    chartRef.current = chart
    seriesRef.current = series

    const markers: Parameters<ChartReadyApi['setMarkers']>[0] = []

    onReady?.({
      chart,
      candleSeries: series,
      addPriceLine: (price, title, color = '#f59e0b') =>
        series.createPriceLine({ price, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title }),
      addLine: (points, color = '#38bdf8') => {
        const line = chart.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false })
        line.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })))
      },
      setMarkers: (next) => {
        markers.length = 0
        markers.push(...next)
        series.setMarkers(markers)
      },
      addZone: (zone) => {
        const primitive = new ZonePrimitive([zone])
        series.attachPrimitive(primitive)
        overlayRef.current.primitives.push(primitive)
      },
    })
    readyRef.current = true
    setChartReady((value) => value + 1)

    // Recompute on rotation / resize even where ResizeObserver is unavailable.
    const onResize = () => chart.timeScale().applyOptions({})
    window.addEventListener('orientationchange', onResize)

    return () => {
      window.removeEventListener('orientationchange', onResize)
      overlayRef.current = { priceLines: [], series: [], primitives: [] }
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      readyRef.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [digits])

  // ----------------------------------------------------------------- data
  useEffect(() => {
    const series = seriesRef.current
    const chart = chartRef.current
    if (!series || !chart || !readyRef.current) return
    if (!candles.length) {
      series.setData([])
      return
    }
    series.setData(
      candles.map((candle) => ({
        time: candle.time as UTCTimestamp,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    )
    chart.timeScale().fitContent()
  }, [candles, symbol, timeframe])

  // -------------------------------------------------- detections overlay(s)
  useEffect(() => {
    const series = seriesRef.current
    const chart = chartRef.current

    // always clear the previous overlay first
    for (const line of overlayRef.current.priceLines) {
      try {
        series?.removePriceLine(line as never)
      } catch {
        /* the chart may already be gone */
      }
    }
    for (const lineSeries of overlayRef.current.series) {
      try {
        chart?.removeSeries(lineSeries as never)
      } catch {
        /* idem */
      }
    }
    for (const primitive of overlayRef.current.primitives) {
      try {
        series?.detachPrimitive(primitive)
      } catch {
        /* idem */
      }
    }
    const hadOverlay = overlayRef.current.priceLines.length > 0
    overlayRef.current = { priceLines: [], series: [], primitives: [] }
    // Removing a price line leaves its axis label region unpainted until the next
    // interaction: the label fragment stays visible while the layer is gone.
    // Asking the price scale for a repaint makes the removal real.
    if (hadOverlay && chart) {
      try {
        chart.priceScale('right').applyOptions({})
      } catch {
        /* the chart may already be gone */
      }
    }

    if (!series || !chart || overlays.length === 0) {
      series?.setMarkers([])
      ;(window as unknown as { __smvChart?: unknown }).__smvChart = {
        overlays: 0,
        priceLines: 0,
        lineSeries: 0,
        zones: 0,
        markers: 0,
        selected: null,
      }
      return
    }

    const drawn = overlays.slice(0, MAX_OVERLAYS)
    const markers: Parameters<ChartReadyApi['setMarkers']>[0] = []
    // The detection the user selected (or the first drawn one) is the reference:
    // only it carries axis labels, and two detections never draw the same price
    // twice (TRIGGER and PATTERN_HIGH are often the same level).
    const primaryId = banner?.id && drawn.some((item) => item.id === banner.id) ? banner.id : drawn[0]?.id
    const drawnLevels = new Set<string>()

    for (const detection of drawn) {
      const priceAction = detection.category === 'PRICE_ACTION'
      const smcIct = detection.category === 'SMC_ICT'
      const isPrimary = detection.id === primaryId
      const levelColor = (kind: string, label: string) =>
        smcIct
          ? colorForSmc(kind, label)
          : priceAction
            ? colorForPriceAction(label)
            : colorForLevel(kind, label)
      const prefix = smcIct ? 'SMC ' : priceAction ? 'PA ' : ''

      // ---- horizontal levels (neckline, support, resistance, trigger...)
      for (const level of detection.drawing?.levels ?? []) {
        const priceKey = level.price.toFixed(digits)
        if (drawnLevels.has(priceKey)) continue
        drawnLevels.add(priceKey)
        const line = series.createPriceLine({
          price: level.price,
          color: levelColor(level.kind, level.label),
          lineWidth: isPrimary ? 2 : 1,
          lineStyle: level.kind === 'NECKLINE' || level.kind === 'BREAKOUT' ? 0 : 2,
          axisLabelVisible: isPrimary,
          title: isPrimary ? `${prefix}${level.label}` : '',
        })
        overlayRef.current.priceLines.push(line)
      }

      // ---- trendlines / neckline segments, drawn from their two real points
      for (const line of detection.drawing?.lines ?? []) {
        if (!line.points || line.points.length < 2) continue
        const lineSeries = chart.addLineSeries({
          color: levelColor(line.kind, line.label),
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
        lineSeries.setData(
          line.points.map((point) => ({ time: point.time as UTCTimestamp, value: point.price })),
        )
        overlayRef.current.series.push(lineSeries)
      }

      // ---- SMC/ICT zones: real rectangles (order block, FVG, breaker, range)
      const zones: ZoneRect[] = []
      if (smcIct) {
        for (const zone of detection.drawing?.zones ?? []) {
          // the SMC payload carries the family in `kind`; the shared DrawingZone
          // type does not declare it, so it is read defensively (never invented)
          const kind = (zone as { kind?: string }).kind ?? detection.pattern
          const stroke = colorForSmc(kind, zone.label)
          zones.push({
            label: `${zone.label}`,
            price_top: zone.price_top,
            price_bottom: zone.price_bottom,
            time_start: zone.time_start,
            time_end: zone.time_end,
            stroke,
            fill: fillForSmc(kind, zone.label, stroke),
          })
        }
      }

      if (zones.length) {
        const primitive = new ZonePrimitive(zones)
        series.attachPrimitive(primitive)
        overlayRef.current.primitives.push(primitive)
      }

      // ---- zones (pattern body, consolidation box, breakout window)
      for (const zone of !smcIct && isPrimary ? (detection.drawing?.zones ?? []) : []) {
        for (const [price, label] of [
          [zone.price_top, `${zone.label} HAUT`],
          [zone.price_bottom, `${zone.label} BAS`],
        ] as [number, string][]) {
          const line = series.createPriceLine({
            price,
            color: priceAction ? '#c084fc' : '#a855f7',
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
            title: label,
          })
          overlayRef.current.priceLines.push(line)
        }
      }

      // ---- pattern points (candles of the pattern, box extrema, breakout bars)
      for (const marker of detection.drawing?.markers ?? []) {
        markers.push({
          time: marker.time as UTCTimestamp,
          position: marker.position,
          color: smcIct ? '#facc15' : priceAction ? '#c084fc' : marker.kind === 'LOW' ? '#22c55e' : '#ef4444',
          shape: (marker.shape === 'arrowUp' || marker.shape === 'arrowDown'
            ? marker.shape
            : priceAction
              ? detection.direction === 'BEARISH'
                ? ('arrowDown' as const)
                : detection.direction === 'BULLISH'
                  ? ('arrowUp' as const)
                  : ('square' as const)
              : marker.shape === 'square'
                ? ('square' as const)
                : ('circle' as const)) as 'circle' | 'square' | 'arrowUp' | 'arrowDown',
          text: smcIct
            ? `SMC ${marker.label ?? detection.pattern}`
            : priceAction
              ? `PA ${marker.label ?? detection.pattern}`
              : marker.label,
        })
      }
    }

    markers.sort((a, b) => Number(a.time) - Number(b.time))
    series.setMarkers(markers)

    // Observability of what the chart REALLY drew (used by the browser
    // verification scripts). It is a read-only counter, never a signal: it
    // reports the price lines / markers / zones the overlay created for the
    // current selection, so a check never has to guess a colour.
    ;(window as unknown as { __smvChart?: unknown }).__smvChart = {
      overlays: drawn.length,
      priceLines: overlayRef.current.priceLines.length,
      lineSeries: overlayRef.current.series.length,
      zones: overlayRef.current.primitives.length,
      markers: markers.length,
      selected: banner?.id ?? null,
    }
  }, [overlays, banner, chartReady, digits])

  const unavailable = dataState === 'DATA_UNAVAILABLE' || (candles.length === 0 && !loading)

  return (
    <section className="card chart-card" aria-label="Candlestick chart">
      <header className="card-head">
        <h2>
          {symbol} <span className="muted">{timeframe}</span>
        </h2>
        <span className="card-head-note">Glisser pour déplacer · pincer pour zoomer</span>
      </header>

      {banner && (
        <div className="chart-detection-banner" data-testid="chart-detection-banner">
          <span className={`badge ${badgeClassFor(banner.category)}`}>
            {banner.category === 'PRICE_ACTION'
              ? 'PRICE ACTION'
              : banner.category === 'SMC_ICT'
                ? 'SMC / ICT'
                : 'CHARTISTE'}
          </span>
          <strong>{banner.pattern}</strong>
          <span className="muted">
            {banner.symbol} {banner.timeframe} · {banner.direction} · {banner.status} ·{' '}
            {Math.round(banner.confidence)}% ·{' '}
            {overlays.length > MAX_OVERLAYS
              ? `${MAX_OVERLAYS} / ${overlays.length} calques (lisibilité)`
              : `${overlays.length} calque(s)`}
          </span>
          <button type="button" className="ghost-button small" onClick={onClearDetection}>
            MASQUER
          </button>
        </div>
      )}

      <div className="chart-wrapper">
        <div ref={containerRef} className="chart-surface" data-testid="chart-surface" />
        {loading && <div className="chart-overlay">CHARGEMENT DES DONNÉES RÉELLES…</div>}
        {unavailable && (
          <div className="chart-overlay unavailable" data-testid="chart-unavailable">
            <strong>DATA UNAVAILABLE</strong>
            <span>Le provider n'a renvoyé aucune bougie. Aucune donnée fictive n'est affichée.</span>
          </div>
        )}
      </div>
    </section>
  )
}


/**
 * Overlay colours of the SMC/ICT geometry: one family, one colour, so the eye
 * separates structure (blue), liquidity (yellow, always an estimate), gaps
 * (green/red), blocks (violet) and ranges (grey) at a glance.
 */
export function colorForSmc(kind: string, label: string): string {
  const key = `${kind} ${label}`.toUpperCase()
  if (key.includes('LIQUID') || key.includes('EQUAL') || key.includes('POOL')) return '#facc15'
  if (key.includes('FVG')) return key.includes('BEARISH') ? '#ef4444' : '#22c55e'
  if (key.includes('BREAKER')) return '#f97316'
  if (key.includes('ORDER_BLOCK') || key.includes('OB_')) return '#a855f7'
  if (key.includes('DISCOUNT')) return '#22c55e'
  if (key.includes('PREMIUM')) return '#ef4444'
  if (key.includes('DEALING_RANGE') || key.includes('EQUILIBRIUM') || key === 'EQ') return '#94a3b8'
  if (key.includes('BOS') || key.includes('CHOCH') || key.includes('MSS')) return '#38bdf8'
  return '#e2e8f0'
}

/** Translucent fill of a zone: same colour family, low alpha, never a signal. */
function fillForSmc(kind: string, label: string, stroke: string): string {
  const key = `${kind} ${label}`.toUpperCase()
  const alpha = key.includes('PREMIUM') || key.includes('DISCOUNT') ? 0.07 : 0.14
  const rgb: Record<string, string> = {
    '#facc15': '250,204,21',
    '#ef4444': '239,68,68',
    '#22c55e': '34,197,94',
    '#f97316': '249,115,22',
    '#a855f7': '168,85,247',
    '#94a3b8': '148,163,184',
    '#38bdf8': '56,189,248',
    '#e2e8f0': '226,232,240',
  }
  return `rgba(${rgb[stroke] ?? '148,163,184'},${alpha})`
}

function badgeClassFor(category: string): string {
  if (category === 'PRICE_ACTION') return 'badge-price-action'
  if (category === 'SMC_ICT') return 'badge-smc'
  return 'badge-chartiste'
}

/** Overlay colours of the price-action levels: distinct from the chartist ones. */
function colorForPriceAction(label: string): string {
  const key = label.toUpperCase()
  if (key.includes('TRIGGER')) return '#38bdf8'
  if (key.includes('INVALIDATION')) return '#f97316'
  if (key.includes('MOTHER') || key.includes('BOX')) return '#c084fc'
  if (key.includes('IMPULSE')) return '#22d3ee'
  return '#e2e8f0'
}


/** Overlay colours: one per chartist concept, so a drawing is readable. */
function colorForLevel(kind: string, label: string): string {
  const key = `${kind} ${label}`.toUpperCase()
  if (key.includes('NECKLINE')) return '#f59e0b'
  if (key.includes('BREAKOUT') || key.includes('CONSOLIDATION')) return '#38bdf8'
  if (key.includes('RESISTANCE') || key.includes('UPPER') || key.includes('PEAK')) return '#ef4444'
  if (key.includes('SUPPORT') || key.includes('LOWER') || key.includes('TROUGH')) return '#22c55e'
  if (key.includes('ZONE')) return '#a855f7'
  return '#94a3b8'
}
