import { TIMEFRAMES, type SymbolInfo, type Timeframe } from '../types/market'

interface SymbolProps {
  symbols: SymbolInfo[]
  selected: string
  onSelect: (symbol: string) => void
}

export function SymbolSelector({ symbols, selected, onSelect }: SymbolProps) {
  return (
    <section className="card selector-card" aria-label="Market selector">
      <header className="card-head">
        <h2>Marchés surveillés</h2>
        <span className="card-head-note">{symbols.length} instruments</span>
      </header>
      <div className="chip-row" role="tablist" data-testid="symbol-selector">
        {symbols.map((info) => (
          <button
            key={info.symbol}
            type="button"
            role="tab"
            aria-selected={info.symbol === selected}
            className={`chip ${info.symbol === selected ? 'chip-active' : ''}`}
            onClick={() => onSelect(info.symbol)}
            title={info.description}
          >
            {info.symbol}
          </button>
        ))}
      </div>
    </section>
  )
}

interface TimeframeProps {
  selected: Timeframe
  onSelect: (timeframe: Timeframe) => void
}

export function TimeframeSelector({ selected, onSelect }: TimeframeProps) {
  return (
    <section className="card selector-card" aria-label="Timeframe selector">
      <header className="card-head">
        <h2>Timeframe</h2>
      </header>
      <div className="segmented" role="tablist" data-testid="timeframe-selector">
        {TIMEFRAMES.map((timeframe) => (
          <button
            key={timeframe}
            type="button"
            role="tab"
            aria-selected={timeframe === selected}
            className={`segment ${timeframe === selected ? 'segment-active' : ''}`}
            onClick={() => onSelect(timeframe)}
          >
            {timeframe}
          </button>
        ))}
      </div>
    </section>
  )
}
