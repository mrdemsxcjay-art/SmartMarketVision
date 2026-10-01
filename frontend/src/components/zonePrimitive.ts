/**
 * Zone primitive (Phase 4, section 17).
 *
 * Draws the rectangles a detection really carries: order blocks, FVG, breakers
 * and the premium / discount bands of a dealing range. Each rectangle comes
 * from the payload (price_top, price_bottom, time_start, time_end); this file
 * only converts real prices and real times into canvas pixels - it never
 * extends, mirrors or invents a zone.
 *
 * Zones whose time_start equals time_end are one-bar realities (an order block
 * origin candle, a displacement candle): they are drawn exactly one bar wide,
 * never widened to look nicer.
 */
import type { CanvasRenderingTarget2D } from 'fancy-canvas'
import type {
  IChartApi,
  ISeriesPrimitivePaneRenderer,
  ISeriesPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
  UTCTimestamp,
} from 'lightweight-charts'

export interface ZoneRect {
  label: string
  price_top: number
  price_bottom: number
  time_start: number
  time_end: number
  /** solid colour of the border (e.g. '#22c55e') */
  stroke: string
  /** translucent fill colour (e.g. 'rgba(34,197,94,0.12)') */
  fill: string
}

export class ZonePrimitive implements ISeriesPrimitive<Time> {
  private readonly zones: ZoneRect[]
  private chart: IChartApi | null = null
  private series: ISeriesApi<'Candlestick'> | null = null
  private readonly view: ISeriesPrimitivePaneView

  constructor(zones: ZoneRect[]) {
    this.zones = zones
    const renderer: ISeriesPrimitivePaneRenderer = {
      draw: (target: CanvasRenderingTarget2D) => this.draw(target),
    }
    this.view = {
      // behind the candles: a zone is context, not a signal
      zOrder: () => 'bottom',
      renderer: () => renderer,
    }
  }

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart as IChartApi
    this.series = param.series as ISeriesApi<'Candlestick'>
  }

  detached(): void {
    this.chart = null
    this.series = null
  }

  updateAllViews(): void {
    /* nothing is cached: every frame reads the live price/time scales */
  }

  paneViews(): readonly ISeriesPrimitivePaneView[] {
    return [this.view]
  }

  private draw(target: CanvasRenderingTarget2D): void {
    const chart = this.chart
    const series = this.series
    if (!chart || !series || this.zones.length === 0) return

    target.useBitmapCoordinateSpace((scope) => {
      const context = scope.context
      const horizontalRatio = scope.horizontalPixelRatio
      const verticalRatio = scope.verticalPixelRatio
      // a single-bar zone is a real single bar: minimum width = one bar slot
      const minWidth = Math.max(2, chart.timeScale().options().barSpacing) * horizontalRatio
      const fontSize = Math.round(10 * verticalRatio)

      for (const zone of this.zones) {
        const x1 = chart.timeScale().timeToCoordinate(zone.time_start as UTCTimestamp)
        const x2 = chart.timeScale().timeToCoordinate(zone.time_end as UTCTimestamp)
        const y1 = series.priceToCoordinate(zone.price_top)
        const y2 = series.priceToCoordinate(zone.price_bottom)
        if (x1 === null || x2 === null || y1 === null || y2 === null) continue

        const left = Math.min(x1, x2) * horizontalRatio
        const right = Math.max(x1, x2) * horizontalRatio
        const top = Math.min(y1, y2) * verticalRatio
        const bottom = Math.max(y1, y2) * verticalRatio
        const width = Math.max(right - left, minWidth)
        const height = Math.max(bottom - top, 1)

        context.fillStyle = zone.fill
        context.fillRect(left, top, width, height)
        context.strokeStyle = zone.stroke
        context.lineWidth = 1
        context.strokeRect(left + 0.5, top + 0.5, width - 1, height - 1)

        // label only when the rectangle is wide enough to hold it: a clipped
        // label would be less readable than no label at all (mobile, section 28)
        context.font = `${fontSize}px sans-serif`
        context.fillStyle = zone.stroke
        const text = zone.label.toUpperCase()
        if (context.measureText(text).width + 8 <= width && height >= fontSize) {
          context.fillText(text, left + 4, top + fontSize)
        }
      }
    })
  }
}
