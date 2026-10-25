/** WebSocket 连接：消息/通知实时提醒，断线自动重连。 */

let socket = null
let reconnectTimer = null

export function connectWS(onMessage) {
  const token = localStorage.getItem('token')
  if (!token) return
  if (socket) closeWS()
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  socket = new WebSocket(`${proto}://${location.host}/ws?token=${token}`)
  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      onMessage?.(data)
    } catch {
      /* 忽略非 JSON 帧 */
    }
  }
  socket.onclose = () => {
    socket = null
    clearTimeout(reconnectTimer)
    if (localStorage.getItem('token')) {
      reconnectTimer = setTimeout(() => connectWS(onMessage), 5000)
    }
  }
  const ping = setInterval(() => {
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'ping' }))
    else clearInterval(ping)
  }, 30000)
}

export function closeWS() {
  clearTimeout(reconnectTimer)
  socket?.close()
  socket = null
}
