/**
 * Realtime client: one-time ticket, durable user_seq cursor, ACK, replay and
 * bounded jittered reconnect.
 *
 * The server may repeat an event (at-least-once delivery). A payload is applied
 * at most once and only for the next contiguous user_seq; a gap triggers the
 * authorized HTTP replay endpoint instead of skipping ahead. `closeWS` is kept
 * for older views but now detaches only the supplied listener.
 */

import http from './http'
import {
  ackFrame,
  applySequenced,
  createState,
  reconnectDelay,
  resetState,
  shouldStopForAuth,
} from './realtimeProtocol.mjs'

const WS_PATH = '/ws'
const HEARTBEAT_INTERVAL_MS = 20000
const HEARTBEAT_TIMEOUT_MS = 60000
const OPEN = 1
const CLOSED = 3

let socket = null
let sessionToken = null
let reconnectTimer = null
let heartbeatTimer = null
let watchdogTimer = null
let reconnectAttempts = 0
let epoch = 0
let stopped = true
let lastFrameAt = 0
let replaying = null
let connecting = false
let frameChain = Promise.resolve()
const state = createState()
const listeners = new Set()

function currentToken() {
  try {
    return localStorage.getItem('token')
  } catch {
    return null
  }
}

function currentUserId() {
  try {
    const user = JSON.parse(localStorage.getItem('user') || 'null')
    return user && Number.isSafeInteger(Number(user.id)) ? String(user.id) : null
  } catch {
    return null
  }
}

function cursorKey() {
  const uid = currentUserId()
  return uid ? `ws:last_seq:${uid}` : null
}

function loadCursor() {
  const key = cursorKey()
  if (!key) return 0
  try {
    const value = Number(sessionStorage.getItem(key) || '0')
    return Number.isSafeInteger(value) && value >= 0 ? value : 0
  } catch {
    return 0
  }
}

function saveCursor() {
  const key = cursorKey()
  if (!key) return
  try {
    sessionStorage.setItem(key, String(state.lastSeq))
  } catch {
    /* storage may be unavailable in private mode */
  }
}

function clearCursors() {
  try {
    for (let i = sessionStorage.length - 1; i >= 0; i -= 1) {
      const key = sessionStorage.key(i)
      if (key && key.startsWith('ws:last_seq:')) sessionStorage.removeItem(key)
    }
  } catch {
    /* ignore */
  }
}

function sessionTokenChanged() {
  return !sessionToken || currentToken() !== sessionToken
}

async function dispatch(frame) {
  let applied = true
  for (const handler of [...listeners]) {
    try {
      await handler?.(frame)
    } catch {
      // Do not advance the durable cursor when a business callback/snapshot
      // failed. The caller closes/replays instead of ACKing an unapplied event.
      applied = false
    }
  }
  return applied
}

function clearReconnectTimer() {
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

function clearTimers() {
  clearReconnectTimer()
  if (heartbeatTimer !== null) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
  if (watchdogTimer !== null) {
    clearInterval(watchdogTimer)
    watchdogTimer = null
  }
}

function detachSocket(ws) {
  if (!ws) return
  ws.onopen = null
  ws.onmessage = null
  ws.onerror = null
  ws.onclose = null
  try {
    ws.close()
  } catch {
    /* already closed */
  }
}

function dispose({ resetCursor = false } = {}) {
  epoch += 1
  stopped = true
  connecting = false
  reconnectAttempts = 0
  clearTimers()
  const old = socket
  socket = null
  sessionToken = null
  detachSocket(old)
  frameChain = Promise.resolve()
  if (resetCursor) {
    resetState(state)
    clearCursors()
  }
}

function scheduleReconnect(myEpoch, delayMs = null) {
  if (stopped || myEpoch !== epoch) return
  const token = sessionToken
  if (!token || currentToken() !== token) {
    dispose({ resetCursor: true })
    return
  }
  clearReconnectTimer()
  const delay = delayMs ?? reconnectDelay(reconnectAttempts)
  reconnectAttempts += 1
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    if (stopped || myEpoch !== epoch) return
    if (!sessionToken || currentToken() !== sessionToken) {
      dispose({ resetCursor: true })
      return
    }
    openSocket(myEpoch)
  }, delay)
}

function sendRaw(frame) {
  if (socket && socket.readyState === OPEN) {
    try {
      socket.send(JSON.stringify(frame))
      return true
    } catch {
      return false
    }
  }
  return false
}

function ackEvent(frame) {
  sendRaw(ackFrame(Number(frame.user_seq), frame.event_id))
}

function startTimers(ws, myEpoch) {
  clearTimers()
  lastFrameAt = Date.now()
  heartbeatTimer = setInterval(() => {
    if (stopped || myEpoch !== epoch || ws !== socket || ws.readyState !== OPEN) return
    sendRaw({ type: 'ping' })
  }, HEARTBEAT_INTERVAL_MS)
  watchdogTimer = setInterval(() => {
    if (stopped || myEpoch !== epoch || ws !== socket) return
    if (Date.now() - lastFrameAt > HEARTBEAT_TIMEOUT_MS) {
      try {
        ws.close()
      } catch {
        /* onclose handles reconnect */
      }
    }
  }, 5000)
}

async function applyFrame(frame) {
  const myEpoch = epoch
  const result = await applySequenced(state, frame, async (payload) => {
    // Dispatch and await the business application before commit/ACK.
    const applied = await dispatch(payload)
    if (myEpoch !== epoch) throw new Error('stale realtime epoch')
    if (!applied) throw new Error('realtime handler rejected event')
  })
  if (myEpoch !== epoch) return false
  if (result.kind === 'duplicate') {
    ackEvent(frame)
    return true
  }
  if (result.kind === 'apply') {
    saveCursor()
    ackEvent(frame)
    return true
  }
  if (result.kind === 'gap') {
    await replay(result.expected)
    return true
  }
  if (result.kind === 'resync') {
    await handleResync(frame)
    return true
  }
  return true
}

async function replay(expectedSeq) {
  if (replaying) return replaying
  replaying = (async () => {
    let after = Math.max(0, state.lastSeq)
    for (let page = 0; page < 20; page += 1) {
      let data
      try {
        data = await http.get('/realtime/events', { params: { after_seq: after, limit: 200 } })
      } catch {
        scheduleReconnect(epoch)
        return
      }
      if (data.resync_required) {
        handleResync({ high_seq: data.high_seq, low_seq: data.low_seq, reason: 'cursor_expired' })
        return
      }
      for (const frame of data.events || []) {
        await applyFrame(frame)
      }
      const last = (data.events || []).length ? Number(data.events[data.events.length - 1].user_seq) : after
      after = Math.max(after, last)
      if (!data.has_more) return
    }
    handleResync({ high_seq: after, reason: 'replay_too_large' })
  })().finally(() => {
    replaying = null
  })
  return replaying
}

async function handleResync(frame) {
  // Never jump the cursor until every view's authoritative snapshot refresh has
  // completed. If a view rejects/fails, keep the old cursor and reconnect; the
  // server will issue resync again instead of silently skipping history.
  const myEpoch = epoch
  const applied = await dispatch({
    type: 'resync_required',
    reason: frame.reason || 'cursor_expired',
    low_seq: frame.low_seq,
    high_seq: frame.high_seq,
  })
  if (myEpoch !== epoch) return
  if (!applied) {
    // Snapshot failure: do not advance. Reconnect from the last durable cursor
    // after a bounded jittered delay, rather than a tight resync loop.
    dispose()
    stopped = false
    sessionToken = currentToken()
    if (sessionToken) scheduleReconnect(epoch, reconnectDelay(reconnectAttempts))
    return
  }
  try {
    window.dispatchEvent(new CustomEvent('realtime:resync', { detail: frame }))
  } catch {
    /* non-browser tests */
  }
  const high = Number(frame.high_seq)
  if (Number.isSafeInteger(high) && high >= 0) {
    state.lastSeq = high
    saveCursor()
  }
  dispose()
  stopped = false
  sessionToken = currentToken()
  if (!sessionToken) return
  openSocket(epoch)
}

async function handleFrame(frame, ws, myEpoch) {
  if (myEpoch !== epoch || ws !== socket) return
  lastFrameAt = Date.now()
  const runEpoch = epoch
  if (sessionTokenChanged()) {
    dispose({ resetCursor: true })
    return
  }
  if (!frame || typeof frame !== 'object') return
  switch (frame.type) {
    case 'hello':
      startTimers(ws, myEpoch)
      break
    case 'event':
      await applyFrame(frame)
      break
    case 'ping':
      sendRaw({ type: 'pong' })
      break
    case 'pong':
      break
    case 'replay_complete':
      lastFrameAt = Date.now()
      break
    case 'resync_required':
      await handleResync(frame)
      break
    case 'drain':
      try {
        ws.close()
      } catch {
        /* onclose reconnects */
      }
      break
    default:
      break
  }
  if (runEpoch !== epoch) return
}

async function openSocket(myEpoch) {
  if (stopped || myEpoch !== epoch || connecting) return
  connecting = true
  const token = sessionToken
  if (!token) {
    stopped = true
    return
  }
  if (currentToken() !== token) {
    dispose({ resetCursor: true })
    return
  }
  if (state.lastSeq === 0) state.lastSeq = loadCursor()

  let ticket
  try {
    ticket = await http.post('/realtime/ticket', { since: state.lastSeq })
  } catch (error) {
    connecting = false
    const status = error?.response?.status
    if (status === 404 || status === 405 || status === 422) {
      // New client against an old backend: stop instead of reconnecting
      // forever. This is a deployment/version boundary, not a transient error.
      stopped = true
      dispatch({ type: 'protocol_incompatible', required_version: 2, status })
      return
    }
    scheduleReconnect(myEpoch)
    return
  }
  if (Number(ticket?.protocol_version) < 2) {
    connecting = false
    stopped = true
    dispatch({ type: 'protocol_incompatible', required_version: 2 })
    return
  }
  if (stopped || myEpoch !== epoch) {
    connecting = false
    return
  }
  if (sessionTokenChanged()) {
    dispose({ resetCursor: true })
    return
  }
  if (Number.isSafeInteger(ticket.since)) state.lastSeq = Math.max(state.lastSeq, ticket.since)

  let ws
  try {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const path = ticket.ws_path || WS_PATH
    ws = new WebSocket(`${proto}://${location.host}${path}?ticket=${encodeURIComponent(ticket.ticket)}`)
  } catch {
    connecting = false
    scheduleReconnect(myEpoch)
    return
  }
  socket = ws
  connecting = false
  ws.onopen = () => {
    if (stopped || myEpoch !== epoch || ws !== socket) return
    if (sessionTokenChanged()) {
      dispose({ resetCursor: true })
      return
    }
    lastFrameAt = Date.now()
  }
  ws.onmessage = (event) => {
    if (myEpoch !== epoch || ws !== socket) return
    let frame
    try {
      frame = JSON.parse(event.data)
    } catch {
      return
    }
    // Serialize all frames per socket: one event's async business application
    // must finish before the next frame can advance the cursor.
    frameChain = frameChain
      .then(() => handleFrame(frame, ws, myEpoch))
      .catch(() => {
        if (myEpoch === epoch && ws === socket) {
          try {
            ws.close()
          } catch {
            /* onclose schedules reconnect */
          }
        }
      })
  }
  ws.onclose = (event) => {
    if (myEpoch !== epoch || ws !== socket) return
    socket = null
    clearTimers()
    if (shouldStopForAuth(event?.code)) {
      // A fresh login is required; reconnecting with the same token is useless.
      stopped = true
      return
    }
    if (stopped) return
    scheduleReconnect(myEpoch)
  }
  ws.onerror = () => {
    /* onclose performs the single reconnect decision */
  }
}

/**
 * Attach a listener and ensure the singleton socket is running.
 * @returns {() => void} detach this listener only
 */
export function connectWS(onMessage) {
  if (typeof onMessage === 'function') listeners.add(onMessage)
  const token = currentToken()
  if (!token) return () => listeners.delete(onMessage)
  if (!stopped && socket && sessionToken === token) return () => detachListener(onMessage)
  if (!stopped && connecting && sessionToken === token) return () => detachListener(onMessage)
  if (sessionToken !== token) {
    dispose({ resetCursor: true })
  } else if (stopped) {
    clearTimers()
  }
  stopped = false
  sessionToken = token
  reconnectAttempts = 0
  openSocket(epoch)
  return () => detachListener(onMessage)
}

function detachListener(handler) {
  listeners.delete(handler)
  if (listeners.size === 0) closeWS()
}

/** Backward-compatible entry: with no handler, disconnect everything. */
export function closeWS(handler = null) {
  if (handler) {
    listeners.delete(handler)
    return
  }
  if (listeners.size > 0) {
    // Older views call closeWS() on unmount without a handler; keep other
    // listeners alive rather than tearing down the singleton socket.
    return
  }
  dispose()
}

/** Explicit cleanup used by logout/account switches and tests. */
export function resetWS() {
  listeners.clear()
  dispose({ resetCursor: true })
  if (replaying) replaying = null
}

if (typeof window !== 'undefined') {
  window.addEventListener('app:session-cleared', () => resetWS())
  window.addEventListener('app:session-changed', () => {
    dispose({ resetCursor: true })
    // Views re-attach their listener on mount/login; do not open a socket with
    // no business listener, otherwise early events advance the cursor unseen.
    if (currentToken() && listeners.size > 0) connectWS()
  })
}
