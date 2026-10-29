/** WebSocket 连接：消息/通知实时提醒，断线按指数退避重连。 */

const WS_PATH = '/ws'
const HEARTBEAT_INTERVAL_MS = 30000
const BASE_RECONNECT_DELAY_MS = 1000
const MAX_RECONNECT_DELAY_MS = 30000
const MAX_RECONNECT_ATTEMPTS = 8
const AUTH_CLOSE_CODES = new Set([4401, 4403])
const OPEN = 1
const CLOSED = 3

let socket = null
let sessionToken = null
let onMessageHandler = null
let pingTimer = null
let reconnectTimer = null
let reconnectAttempts = 0
let epoch = 0
let stopped = true

function currentToken() {
  try {
    return localStorage.getItem('token')
  } catch {
    return null
  }
}

/** 本地 token 仍是本连接建立时使用的 token 才允许继续。 */
function sessionTokenChanged() {
  return !sessionToken || currentToken() !== sessionToken
}

function clearReconnectTimer() {
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

function clearPingTimer() {
  if (pingTimer !== null) {
    clearInterval(pingTimer)
    pingTimer = null
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
    /* 已关闭或浏览器拒绝关闭时无需处理 */
  }
}

/** 作废当前代次：旧 socket 的后续事件不再影响新连接。 */
function disposeCurrent() {
  epoch += 1
  stopped = true
  reconnectAttempts = 0
  clearReconnectTimer()
  clearPingTimer()
  const old = socket
  socket = null
  sessionToken = null
  onMessageHandler = null
  detachSocket(old)
}

function buildUrl(token) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}${WS_PATH}?token=${encodeURIComponent(token)}`
}

function scheduleReconnect(myEpoch) {
  if (stopped || myEpoch !== epoch) return
  const token = sessionToken
  const latest = currentToken()
  if (!token || latest !== token) {
    // token 已清除或更换：旧连接不能再用旧 token 续命。
    stopped = true
    return
  }
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    stopped = true
    return
  }
  clearReconnectTimer()
  const delay = Math.min(BASE_RECONNECT_DELAY_MS * 2 ** reconnectAttempts, MAX_RECONNECT_DELAY_MS)
  reconnectAttempts += 1
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    if (stopped || myEpoch !== epoch) return
    if (!sessionToken || currentToken() !== sessionToken) {
      stopped = true
      return
    }
    openSocket(myEpoch)
  }, delay)
}

function startHeartbeat(ws, myEpoch) {
  clearPingTimer()
  const timer = setInterval(() => {
    if (stopped || myEpoch !== epoch || ws !== socket) {
      clearInterval(timer)
      if (pingTimer === timer) pingTimer = null
      return
    }
    if (!sessionToken || currentToken() !== sessionToken) {
      // 本地 token 已变化：主动结束旧连接，且不触发重连。
      closeWS()
      return
    }
    if (ws.readyState === OPEN) {
      try {
        ws.send(JSON.stringify({ type: 'ping' }))
      } catch {
        clearInterval(timer)
        if (pingTimer === timer) pingTimer = null
        try {
          ws.close()
        } catch {
          /* 关闭失败交由 onclose 兜底 */
        }
      }
    } else if (ws.readyState === CLOSED) {
      clearInterval(timer)
      if (pingTimer === timer) pingTimer = null
      if (ws === socket) {
        // 先摘除当前 socket，避免随后到达的 onclose 重复累计重连次数。
        socket = null
        scheduleReconnect(myEpoch)
      }
    }
  }, HEARTBEAT_INTERVAL_MS)
  pingTimer = timer
}

function openSocket(myEpoch) {
  if (stopped || myEpoch !== epoch) return
  const token = sessionToken
  if (!token) {
    stopped = true
    return
  }
  if (currentToken() !== token) {
    disposeCurrent()
    return
  }

  let ws
  try {
    ws = new WebSocket(buildUrl(token))
  } catch {
    scheduleReconnect(myEpoch)
    return
  }
  socket = ws

  ws.onopen = () => {
    if (stopped || myEpoch !== epoch || ws !== socket) return
    if (sessionTokenChanged()) {
      // 建连期间 token 已切换/清除：在开始心跳前就结束旧连接，且不重连。
      disposeCurrent()
      return
    }
    startHeartbeat(ws, myEpoch)
  }

  ws.onmessage = (event) => {
    if (myEpoch !== epoch || ws !== socket) return
    if (sessionTokenChanged()) {
      // 不能等下一次心跳：立即停止旧连接，并丢弃这个属于旧会话的帧。
      disposeCurrent()
      return
    }
    try {
      const data = JSON.parse(event.data)
      onMessageHandler?.(data)
    } catch {
      /* 忽略非 JSON 帧 */
    }
  }

  ws.onclose = (event) => {
    if (myEpoch !== epoch || ws !== socket) return
    socket = null
    clearPingTimer()
    if (AUTH_CLOSE_CODES.has(event?.code)) {
      // 认证失败重试无意义，等待用户重新登录后由页面重新 connectWS。
      stopped = true
      return
    }
    if (stopped) return
    scheduleReconnect(myEpoch)
  }

  ws.onerror = () => {
    /* 浏览器随后触发 onclose，由 onclose 统一重连/停止。 */
  }
}

export function connectWS(onMessage) {
  const token = currentToken()
  disposeCurrent()
  if (!token) return
  stopped = false
  reconnectAttempts = 0
  sessionToken = token
  onMessageHandler = onMessage ?? null
  openSocket(epoch)
}

export function closeWS() {
  disposeCurrent()
}
