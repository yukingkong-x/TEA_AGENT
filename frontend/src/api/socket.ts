/**
 * WS /ws/dashboard 客户端。
 *
 * 队友B 的坑（照他说的三处一起改，缺一条就静默收不到消息）：
 * 1. URL 必须有兜底 —— 仓库里没有 .env，`import.meta.env.VITE_WS_URL` 是 undefined；
 * 2. 必须挂 onmessage，否则连上了也一条都收不到；
 * 3. 必须每 20s 发一次 `{"type":"ping"}`，后端靠它探测断线（回 pong）。
 * 另外 WS 路由不带 /api 前缀，是 `/ws/dashboard`。
 */
import type { DashMessage } from './types'

export const WS_URL =
  import.meta.env.VITE_WS_URL ?? `ws://${location.hostname}:8000/ws/dashboard`

type Handler = (message: DashMessage) => void

const PING_INTERVAL = 20_000
const RECONNECT_BASE = 1_000
const RECONNECT_MAX = 10_000

export class DashboardSocket {
  private socket: WebSocket | null = null
  private handlers = new Set<Handler>()
  private pingTimer = 0
  private retryTimer = 0
  private attempt = 0
  private stopped = false

  constructor(private readonly url: string = WS_URL) {}

  connect(): void {
    if (this.socket) return
    // 单例可能被 close 过（React StrictMode 双挂载就会走一遍 close），
    // 重连前必须把停止标记清掉，否则 connect 直接 return，页面永远「离线」。
    this.stopped = false

    const socket = new WebSocket(this.url)
    this.socket = socket

    socket.onopen = () => {
      this.attempt = 0
      this.emitLocal({ type: '__open', data: {}, ts: Date.now() })
      this.pingTimer = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) socket.send('{"type":"ping"}')
      }, PING_INTERVAL)
    }

    socket.onmessage = (event) => {
      let message: DashMessage | null = null
      try {
        message = JSON.parse(String(event.data)) as DashMessage
      } catch {
        return
      }
      if (!message || typeof message.type !== 'string') return
      for (const handler of this.handlers) handler(message)
    }

    socket.onclose = () => {
      window.clearInterval(this.pingTimer)
      this.pingTimer = 0
      this.socket = null
      this.emitLocal({ type: '__close', data: {}, ts: Date.now() })
      if (this.stopped) return
      const delay = Math.min(RECONNECT_BASE * 2 ** this.attempt, RECONNECT_MAX)
      this.attempt += 1
      this.retryTimer = window.setTimeout(() => this.connect(), delay)
    }

    socket.onerror = () => socket.close()
  }

  /** 本地事件（__open / __close）也走同一个订阅口，页面不用另写连接状态机 */
  private emitLocal(message: DashMessage): void {
    for (const handler of this.handlers) handler(message)
  }

  subscribe(handler: Handler): () => void {
    this.handlers.add(handler)
    return () => this.handlers.delete(handler)
  }

  /** 按 type 订阅，回调拿到的是 data（已解包） */
  on<T = Record<string, unknown>>(type: string, handler: (data: T, message: DashMessage) => void): () => void {
    return this.subscribe((message) => {
      if (message.type === type) handler((message.data ?? {}) as T, message)
    })
  }

  close(): void {
    this.stopped = true
    window.clearInterval(this.pingTimer)
    window.clearTimeout(this.retryTimer)
    this.socket?.close()
    this.socket = null
    this.handlers.clear()
  }
}

/** 全局单例：整个 App 只该有一条 WS 连接 */
export const dashboardSocket = new DashboardSocket()
