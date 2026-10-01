/**
 * WebSocket subscription with automatic reconnection.
 *
 * Status semantics (shown to the user):
 *   LIVE         : socket open AND a real event received recently
 *   RECONNECTING : socket closed, a retry is scheduled
 *   DISCONNECTED : no data for longer than the staleness window
 *
 * The hook never fabricates an event: if nothing real arrives, the status
 * degrades instead of pretending the feed is alive.
 */
import { useEffect, useRef, useState } from 'react'
import { streamUrl } from '../api/client'
import type { MarketEvent, StreamStatus, Timeframe } from '../types/market'

const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 15000
/** No real event for this long => the feed is not LIVE any more. */
const STALE_AFTER_MS = 45000

export interface StreamState {
  status: StreamStatus
  lastEvent: MarketEvent | null
  lastMessageAt: Date | null
  attempts: number
}

export function useMarketStream(symbol: string, timeframe: Timeframe): StreamState {
  const [status, setStatus] = useState<StreamStatus>('DISCONNECTED')
  const [lastEvent, setLastEvent] = useState<MarketEvent | null>(null)
  const [lastMessageAt, setLastMessageAt] = useState<Date | null>(null)
  const [attempts, setAttempts] = useState(0)

  const socketRef = useRef<WebSocket | null>(null)
  const timerRef = useRef<number | null>(null)
  const attemptsRef = useRef(0)
  const closedRef = useRef(false)
  const lastMessageRef = useRef<number>(0)

  useEffect(() => {
    closedRef.current = false
    attemptsRef.current = 0
    setAttempts(0)
    setStatus('RECONNECTING')

    // Each subscription (symbol/timeframe pair) owns its socket: the handlers
    // below close over THESE identifiers, so a late callback from a previous
    // subscription can never resurrect it (it used to reopen the old symbol
    // ~1s after a pair change and overwrite the panel with stale data).
    let currentSocket: WebSocket | null = null
    let reconnectTimer: number | null = null
    let generationClosed = false

    const connect = () => {
      if (generationClosed) return
      let socket: WebSocket
      try {
        socket = new WebSocket(streamUrl(symbol, timeframe))
      } catch {
        scheduleReconnect()
        return
      }
      currentSocket = socket
      socketRef.current = socket

      socket.onopen = () => {
        // Still RECONNECTING until a real event arrives: an open socket is not proof of data.
        if (socket !== currentSocket) return
        lastMessageRef.current = 0
      }

      socket.onmessage = (raw: MessageEvent<string>) => {
        // ignore anything from a socket that is not the live subscription
        if (generationClosed || socket !== currentSocket) return
        let event: MarketEvent
        try {
          event = JSON.parse(raw.data) as MarketEvent
        } catch {
          return
        }
        lastMessageRef.current = Date.now()
        setLastEvent(event)
        setLastMessageAt(new Date())
        setStatus('LIVE')
        attemptsRef.current = 0
        setAttempts(0)
      }

      socket.onerror = () => {
        if (generationClosed || socket !== currentSocket) return
        setStatus('RECONNECTING')
      }

      socket.onclose = () => {
        // A socket closed by the effect cleanup must never reconnect: only the
        // socket that is still the current one may schedule a retry.
        if (generationClosed || socket !== currentSocket) return
        currentSocket = null
        socketRef.current = null
        scheduleReconnect()
      }
    }

    const scheduleReconnect = () => {
      if (generationClosed) return
      attemptsRef.current += 1
      setAttempts(attemptsRef.current)
      setStatus('RECONNECTING')
      const delay = Math.min(RECONNECT_BASE_MS * 2 ** (attemptsRef.current - 1), RECONNECT_MAX_MS)
      reconnectTimer = window.setTimeout(connect, delay)
      timerRef.current = reconnectTimer
    }

    connect()

    const watchdog = window.setInterval(() => {
      if (generationClosed) return
      const age = Date.now() - lastMessageRef.current
      if (lastMessageRef.current === 0) {
        if (currentSocket?.readyState !== WebSocket.OPEN) setStatus('RECONNECTING')
        return
      }
      if (age > STALE_AFTER_MS) setStatus('DISCONNECTED')
    }, 5000)

    return () => {
      generationClosed = true
      closedRef.current = true
      window.clearInterval(watchdog)
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
      if (timerRef.current) window.clearTimeout(timerRef.current)
      // detach first, so the close handler cannot reconnect this generation
      const socketToClose = currentSocket
      currentSocket = null
      if (socketRef.current === socketToClose) socketRef.current = null
      try {
        socketToClose?.close()
      } catch {
        /* already closing */
      }
    }
  }, [symbol, timeframe])

  return { status, lastEvent, lastMessageAt, attempts }
}
