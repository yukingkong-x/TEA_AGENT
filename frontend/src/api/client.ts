/**
 * 唯一出口：所有 REST 调用都走这里，页面里不准再直接写 fetch。
 *
 * 三条约定（和队友B对齐过）：
 * 1. 后端 503 + `code: "SEAM_NOT_READY"` 不是错误，是「模块开发中」——
 *    页面必须显示空态，不能弹通用报错（彩排时这几页会被点到）。
 * 2. `detail` 可能是字符串，也可能是 FastAPI 的校验错误数组，统一压成一句人话。
 * 3. 默认 8 秒超时：后端 LLM 降级时接口会拖，超时比一直转圈友好。
 */

export const API_BASE = (import.meta.env.VITE_API_BASE ?? '/api').replace(/\/+$/, '')

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly seam: string | null
  readonly raw: unknown

  constructor(status: number, code: string, detail: string, raw: unknown, seam: string | null = null) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.seam = seam
    this.raw = raw
  }

  /** 接缝未就绪 —— 页面渲染「功能接入中」空态，不报错 */
  get notReady(): boolean {
    return this.code === 'SEAM_NOT_READY'
  }
}

export function isNotReady(err: unknown): err is ApiError {
  return err instanceof ApiError && err.notReady
}

function humanizeDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item && typeof item === 'object' && 'msg' in item) {
        const loc = Array.isArray((item as { loc?: unknown[] }).loc)
          ? (item as { loc: unknown[] }).loc.slice(1).join('.')
          : ''
        return loc ? `${loc}: ${String((item as { msg: unknown }).msg)}` : String((item as { msg: unknown }).msg)
      }
      return JSON.stringify(item)
    })
    return parts.join('；')
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  return '请求失败'
}

type Options = {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  /** 文件上传走这个：浏览器自己带 boundary，不要手动设 Content-Type */
  form?: FormData
  query?: Record<string, string | number | boolean | null | undefined>
  timeoutMs?: number
  signal?: AbortSignal
}

function buildUrl(path: string, query?: Options['query']): string {
  const url = `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

export async function request<T>(path: string, options: Options = {}): Promise<T> {
  const { method = 'GET', body, form, query, timeoutMs = 8000, signal } = options

  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  const onAbort = () => controller.abort()
  signal?.addEventListener('abort', onAbort)

  try {
    const payload = form ?? (body === undefined ? undefined : JSON.stringify(body))
    const headers = form || body === undefined ? undefined : { 'Content-Type': 'application/json' }
    const res = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: payload,
      signal: controller.signal,
    })

    const text = await res.text()
    let parsed: unknown = null
    if (text) {
      try {
        parsed = JSON.parse(text)
      } catch {
        parsed = text
      }
    }

    if (!res.ok) {
      const payload = (parsed ?? {}) as { detail?: unknown; code?: unknown; seam?: unknown }
      const code = typeof payload.code === 'string' ? payload.code : `HTTP_${res.status}`
      const seam = typeof payload.seam === 'string' ? payload.seam : null
      throw new ApiError(res.status, code, humanizeDetail(payload.detail ?? `HTTP ${res.status}`), parsed, seam)
    }

    return parsed as T
  } catch (err) {
    if (err instanceof ApiError) throw err
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(0, 'TIMEOUT', `请求超时（${Math.round(timeoutMs / 1000)}s）`, err)
    }
    throw new ApiError(0, 'NETWORK', '连不上后端：确认 FastAPI 已在 8000 端口启动', err)
  } finally {
    window.clearTimeout(timer)
    signal?.removeEventListener('abort', onAbort)
  }
}

export const api = {
  get: <T>(path: string, query?: Options['query'], timeoutMs?: number) =>
    request<T>(path, { method: 'GET', query, timeoutMs }),
  post: <T>(path: string, body?: unknown, query?: Options['query'], timeoutMs?: number) =>
    request<T>(path, { method: 'POST', body, query, timeoutMs }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body }),
  del: <T>(path: string, query?: Options['query']) => request<T>(path, { method: 'DELETE', query }),
  /** multipart/form-data（知识库上传） */
  upload: <T>(path: string, form: FormData, timeoutMs = 60_000) =>
    request<T>(path, { method: 'POST', form, timeoutMs }),
}
