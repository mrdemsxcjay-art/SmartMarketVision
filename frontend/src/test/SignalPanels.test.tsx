/**
 * Phase 5-8 panels: the values shown must be the values received.
 *
 * The fixtures below are the REAL payload shapes captured from the backend
 * (confluence group, opportunity, telegram status, alert row). Nothing is
 * recomputed here: a score of 5/10 renders as "5.0/10", a refusal renders its
 * reason, and a field the backend did not send stays "—" instead of being
 * invented.
 */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import {
  AlertsPanel,
  ConfluencePanel,
  MarketOverview,
  OpportunityPanel,
  directionText,
  stateText,
} from '../components/SignalPanels'
import type {
  CaptureRow,
  ConfluenceReading as ConfluenceReadingType,
  ConfluenceListResponse,
  Opportunity,
  OpportunityOverview,
  OpportunitiesResponse,
  TelegramHistoryResponse,
  TelegramStatus,
} from '../types/market'

const confluenceGroup: ConfluenceReadingType = {
  id: 'cf_7297e4c819ca19ec',
  dedup_key: 'cf_7297e4c819ca19ec',
  signature: '138c171117ae01ec',
  symbol: 'USDCAD',
  timeframe: 'M15',
  direction: 'BULLISH',
  state: 'CONFLUENCE',
  score: 5,
  max_score: 10,
  dimensions: ['STRUCTURE', 'IMBALANCE', 'DISPLACEMENT', 'PRICE_ACTION'],
  components: [
    {
      dimension: 'STRUCTURE',
      label: 'Structure',
      points: 2,
      reason: 'CHOCH (M15)',
      events: ['smc_1'],
      timeframes: ['M15'],
    },
  ],
  contradictions: [],
  events: [],
  why: ['Structure haussier (M15) : CHOCH (M15) [+2]'],
  against: ['Aucun élément opposé dans la fenêtre'],
  reference_price: 1.4249,
  window_start: 1790847900,
  window_end: 1790848800,
}

const confluencePayload: ConfluenceListResponse = {
  count: 1,
  symbol: 'USDCAD',
  timeframe: 'M15',
  confluences: [confluenceGroup],
  counts: { CONFLUENCE: 1 },
  by_direction: { BULLISH: 1 },
  engines: { CONFLUENCE_ENGINE: 'ENABLED' },
  stats: {},
  trading_signal: false,
}

const opportunity: Opportunity = {
  id: 'op_da9427791f258fb6',
  symbol: 'USDCAD',
  timeframe: 'M15',
  direction: 'BUY',
  state: 'CREATED',
  score: 8,
  max_score: 10,
  confluence_id: 'cf_7297e4c819ca19ec',
  confluence_state: 'CONFLUENCE',
  reference_price: 1.4249,
  conditions: [
    {
      label: 'Structure alignee sur la direction',
      passed: true,
      detail: 'dimensions observees : STRUCTURE, IMBALANCE',
      points: 3,
      dimension: 'STRUCTURE',
      gate: false,
    },
    {
      label: 'Liquidite observee',
      passed: false,
      detail: 'aucune lecture de liquidite dans la fenetre',
      points: 0,
      dimension: 'LIQUIDITY',
      gate: false,
    },
    {
      label: 'Volatilite utilisable',
      passed: true,
      detail: 'ATR 11.31 pip(s)',
      points: 0,
      dimension: 'VOLATILITY',
      gate: true,
    },
  ],
  evidence: ['confluence cf_7297e4c819ca19ec : CONFLUENCE 5/10'],
  no_trade_reason: null,
  blocked_by: null,
  watch_levels: [
    { label: 'PRIX DE REFERENCE', price: 1.4249, kind: 'REFERENCE', note: 'prix reel' },
  ],
  created_at: '2026-10-01T10:16:00+00:00',
  updated_at: '2026-10-01T10:16:00+00:00',
  observed_bar_time: 1790848800,
  confirmation_bar_time: null,
  expires_at: '2026-10-01T17:30:00+00:00',
  generation: 1,
  alert_key: 'USDCAD|M15|BUY|cf_7297e4c819ca19ec',
  note: 'direction BUY observee',
}

const opportunitiesPayload: OpportunitiesResponse = {
  count: 1,
  symbol: 'USDCAD',
  timeframe: 'M15',
  opportunities: [opportunity],
  counts: { CREATED: 1 },
  directions: { BUY: 1 },
  engines: { OPPORTUNITY_ENGINE: 'ENABLED' },
  stats: {},
  trading_signal: false,
  order_execution: false,
}

const overview: OpportunityOverview = {
  symbol: 'USDCAD',
  timeframe: 'M15',
  direction: 'BUY',
  state: 'CREATED',
  score: 8,
  max_score: 10,
  opportunity_id: opportunity.id,
  confluence_id: confluenceGroup.id,
  reference_price: 1.4249,
  no_trade_reason: null,
  tracked: 2,
  named: 1,
}

const telegramStatus: TelegramStatus = {
  mode: 'DRY_RUN',
  enabled: true,
  configured: true,
  notifier: {
    status: 'CONFIGURED',
    bot_token_present: true,
    bot_token_preview: '123456',
    chat_id_present: true,
    chat_id_preview: '-1',
    capabilities: ['send_message', 'send_image'],
  },
  queue: { queued: 0, sending: 0, retrying: 0, sent: 3, failed: 0, skipped: 0 },
  dispatcher: {
    running: true,
    enqueued: 3,
    duplicates_ignored: 1,
    skipped: 0,
    sent: 3,
    failed: 0,
    last_sent_at: '2026-10-01T10:17:00+00:00',
    last_error: null,
  },
  note: 'DRY_RUN (defaut) : aucun envoi reseau.',
}

const capture: CaptureRow = {
  id: 'cap_2306d81ce1290e53',
  opportunity_id: opportunity.id,
  symbol: 'USDCAD',
  timeframe: 'M15',
  timestamp: '2026-10-01T10:16:04+00:00',
  bar_time: 1790848800,
  path: '/tmp/USDCAD_M15_phone.png',
  telegram_path: '/tmp/USDCAD_M15_telegram.png',
  digest: 'abc',
  width: 1080,
  height: 1350,
  size_bytes: 58133,
  candles_drawn: 120,
  overlays: { items: [{ kind: 'LEVEL', label: 'BUY - prix de reference', priority: 1, source: 'OPPORTUNITY', source_id: opportunity.id }] },
  state: 'RENDERED',
}

const alertHistory: TelegramHistoryResponse = {
  count: 1,
  alerts: [
    {
      id: 'al_f863890ff82922ae',
      alert_id: 'al_f863890ff82922ae',
      opportunity_id: opportunity.id,
      capture_id: capture.id,
      symbol: 'USDCAD',
      timeframe: 'M15',
      event_type: 'OPPORTUNITY_CREATED',
      message: '🚨 SMART MARKET VISION',
      caption: '🟢 USDCAD · M15 — BUY',
      status: 'SENT',
      mode: 'DRY_RUN',
      attempts: 1,
      max_attempts: 5,
      last_error: null,
      next_attempt_at: null,
      created_at: '2026-10-01T10:16:05+00:00',
      updated_at: '2026-10-01T10:16:05+00:00',
      sent_at: '2026-10-01T10:16:05+00:00',
      provider_message_id: null,
    },
  ],
  counts: { SENT: 1 },
  trading_signal: false,
  note: 'Historique reel.',
}

describe('MarketOverview', () => {
  it('shows the six real values of the header', () => {
    render(
      <MarketOverview
        symbol="USDCAD"
        timeframe="M15"
        price={1.4249}
        digits={5}
        marketState="CONNECTED"
        confluence={confluenceGroup}
        overview={overview}
      />,
    )
    expect(screen.getByTestId('overview-symbol').textContent).toBe('USDCAD')
    expect(screen.getByTestId('overview-timeframe').textContent).toBe('M15')
    expect(screen.getByTestId('overview-price').textContent).toBe('1.42490')
    expect(screen.getByTestId('overview-market-state').textContent).toBe('CONNECTED')
    expect(screen.getByTestId('overview-confluence').textContent).toBe('5/10')
    expect(screen.getByTestId('overview-opportunity').textContent).toBe('🟢 BUY')
  })

  it('shows a dash instead of inventing a confluence or a price', () => {
    render(
      <MarketOverview
        symbol="EURUSD"
        timeframe="M15"
        price={null}
        digits={5}
        marketState={null}
        confluence={null}
        overview={null}
      />,
    )
    expect(screen.getByTestId('overview-price').textContent).toBe('—')
    expect(screen.getByTestId('overview-confluence').textContent).toBe('—')
    expect(screen.getByTestId('overview-opportunity').textContent).toBe('⛔ NO_TRADE')
  })
})

describe('ConfluencePanel', () => {
  it('shows the state, the score and the components that earned each point', () => {
    render(<ConfluencePanel confluence={confluencePayload} current={confluenceGroup} />)
    expect(screen.getByTestId('confluence-score').textContent).toBe('5.0/10')
    expect(screen.getByTestId('confluence-id').textContent).toContain('cf_7297e4c819ca19ec')
    const components = screen.getByTestId('confluence-components')
    expect(components.textContent).toContain('Structure')
    expect(components.textContent).toContain('+2')
  })

  it('never presents the score as a probability', () => {
    render(<ConfluencePanel confluence={confluencePayload} current={confluenceGroup} />)
    const text = (document.body.textContent ?? '').toLowerCase()
    // the only occurrence allowed is the explicit disclaimer that DENIES it
    expect(text).toContain('jamais une probabilité')
    expect(text).not.toContain('probabilité de')
    expect(text).not.toContain('chance de')
    expect(text).not.toContain('réussite')
    expect(text).not.toContain('%')
  })

  it('says explicitly when there is no confluence', () => {
    render(<ConfluencePanel confluence={{ ...confluencePayload, count: 0, confluences: [] }} current={null} />)
    expect(screen.getByTestId('confluence-empty')).toBeTruthy()
  })

  it('surfaces an engine error instead of an empty list', () => {
    render(<ConfluencePanel confluence={null} current={null} error="CONFLUENCE INDISPONIBLE" />)
    expect(screen.getByTestId('confluence-error').textContent).toContain('INDISPONIBLE')
  })
})

describe('OpportunityPanel', () => {
  it('shows the analytical direction, the state and every condition checked', () => {
    render(<OpportunityPanel opportunities={opportunitiesPayload} overview={overview} />)
    expect(screen.getByTestId('opportunity-direction').textContent).toBe('🟢 BUY')
    expect(screen.getByTestId('opportunity-score').textContent).toBe('8.0/10')
    const conditions = screen.getByTestId('opportunity-conditions').textContent ?? ''
    expect(conditions).toContain('Structure alignee sur la direction')
    expect(conditions).toContain('Liquidite observee')
    expect(conditions).toContain('critère bloquant')
  })

  it('states that a direction is an observation, not an order', () => {
    render(<OpportunityPanel opportunities={opportunitiesPayload} overview={overview} />)
    expect(screen.getByTestId('opportunity-panel').textContent).toContain('aucun ordre')
  })

  it('always shows the reason of a NO_TRADE', () => {
    const refusal: Opportunity = {
      ...opportunity,
      direction: 'NO_TRADE',
      state: 'ACTIVE',
      score: 4,
      no_trade_reason: 'DIRECTIONS_CONTRADICTOIRES',
    }
    render(
      <OpportunityPanel
        opportunities={{ ...opportunitiesPayload, opportunities: [refusal] }}
        overview={{ ...overview, direction: 'NO_TRADE', no_trade_reason: 'DIRECTIONS_CONTRADICTOIRES' }}
      />,
    )
    expect(screen.getByTestId('opportunity-reason').textContent).toContain('DIRECTIONS_CONTRADICTOIRES')
  })

  it('says when nothing was observed instead of filling the panel', () => {
    render(<OpportunityPanel opportunities={{ ...opportunitiesPayload, count: 0, opportunities: [] }} overview={null} />)
    expect(screen.getByTestId('opportunity-empty')).toBeTruthy()
  })
})

describe('AlertsPanel', () => {
  it('shows the telegram mode and the queue counters', () => {
    render(<AlertsPanel telegram={telegramStatus} history={alertHistory} captures={[capture]} />)
    expect(screen.getByTestId('telegram-mode').textContent).toBe('DRY_RUN')
    expect(screen.getByTestId('telegram-queue').textContent).toContain('sent 3')
  })

  it('lists the real alerts with their identity and capture', () => {
    render(<AlertsPanel telegram={telegramStatus} history={alertHistory} captures={[capture]} />)
    const row = screen.getByTestId('alert-row')
    expect(row.textContent).toContain('ENVOYÉE')
    expect(row.textContent).toContain(opportunity.id)
    expect(row.textContent).toContain(capture.id)
  })

  it('shows the real captures with their dimensions and overlays', () => {
    render(<AlertsPanel telegram={telegramStatus} history={alertHistory} captures={[capture]} />)
    const gallery = screen.getByTestId('capture-gallery')
    expect(gallery.textContent).toContain(capture.id)
    expect(screen.getByTestId('capture-count').textContent).toContain('1 capture(s) réelle(s)')
    const image = gallery.querySelector('img')
    expect(image?.getAttribute('src')).toBe(`/api/captures/${capture.id}/file?tier=telegram`)
  })

  it('keeps the captures of the other pairs visible, current pair first', () => {
    const other: CaptureRow = {
      ...capture,
      id: 'cap_otherpair00000000',
      symbol: 'GBPJPY',
      timestamp: '2026-10-01T11:00:00+00:00',
    }
    render(
      <AlertsPanel
        telegram={telegramStatus}
        history={alertHistory}
        captures={[other, capture]}
        symbol={capture.symbol}
      />,
    )
    const rows = screen.getByTestId('capture-gallery').querySelectorAll('li')
    expect(rows.length).toBe(2)
    // la paire affichee passe devant, l'autre reste visible (chacune est etiquetee)
    expect(rows[0].textContent).toContain(capture.symbol)
    expect(rows[1].textContent).toContain('GBPJPY')
  })

  it('never renders a token', () => {
    render(<AlertsPanel telegram={telegramStatus} history={alertHistory} captures={[]} />)
    const text = document.body.textContent ?? ''
    expect(text).not.toContain('bot_token')
    expect(text).not.toContain('TELEGRAM_BOT_TOKEN')
  })

  it('says when the history is empty', () => {
    render(<AlertsPanel telegram={null} history={{ ...alertHistory, count: 0, alerts: [] }} captures={[]} />)
    expect(screen.getByTestId('alerts-empty')).toBeTruthy()
    expect(screen.getByTestId('telegram-mode').textContent).toBe('—')
  })

  it('surfaces a delivery error', () => {
    const failing = {
      ...alertHistory,
      alerts: [{ ...alertHistory.alerts[0], status: 'FAILED', last_error: 'HTTP 500' }],
    }
    render(<AlertsPanel telegram={telegramStatus} history={failing} captures={[]} />)
    expect(screen.getByTestId('alert-error').textContent).toContain('HTTP 500')
  })
})

describe('Vocabulary', () => {
  it('translates the engine values without inventing any', () => {
    expect(directionText('BUY')).toBe('🟢 BUY')
    expect(directionText('SELL')).toBe('🔴 SELL')
    expect(directionText('WATCH')).toBe('👀 WATCH')
    expect(directionText('NO_TRADE')).toBe('⛔ NO_TRADE')
    expect(directionText('INCONNU')).toBe('INCONNU')
    expect(stateText('STRONG_CONFLUENCE')).toBe('CONFLUENCE FORTE')
    expect(stateText('CONTRADICTED')).toBe('CONTRADICTION')
    expect(stateText('QUEUED')).toBe('EN FILE')
  })
})
