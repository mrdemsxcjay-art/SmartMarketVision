import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

/**
 * jsdom has no canvas implementation and no ResizeObserver, and Lightweight
 * Charts needs both. The chart itself is verified in the real browser; here the
 * component contract (mount, data flow, DATA UNAVAILABLE overlay) is tested.
 */
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub
;(window as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub

vi.mock('lightweight-charts', () => {
  const series = {
    setData: vi.fn(),
    setMarkers: vi.fn(),
    createPriceLine: vi.fn(() => ({})),
    applyOptions: vi.fn(),
    // Phase 4: zones (order blocks, FVG, breakers) are canvas primitives.
    // The real v4.2 series exposes attachPrimitive/detachPrimitive; the stub
    // mirrors that API so the component contract stays testable in jsdom.
    attachPrimitive: vi.fn(),
    detachPrimitive: vi.fn(),
  }
  const chart = {
    addCandlestickSeries: vi.fn(() => series),
    addLineSeries: vi.fn(() => series),
    timeScale: vi.fn(() => ({
      fitContent: vi.fn(),
      applyOptions: vi.fn(),
      options: vi.fn(() => ({ barSpacing: 6 })),
      timeToCoordinate: vi.fn(() => null),
    })),
    applyOptions: vi.fn(),
    remove: vi.fn(),
    resize: vi.fn(),
  }
  return {
    createChart: vi.fn(() => chart),
    ColorType: { Solid: 'solid' },
    CrosshairMode: { Normal: 0 },
    LineStyle: { Solid: 0, Dashed: 2 },
    __mockChart: chart,
    __mockSeries: series,
  }
})
