/**
 * 后端时间统一是 MySQL 原生格式 `2026-11-14 09:30:00`（空格分隔）。
 * Safari / iOS WebKit 不认空格分隔的 new Date()，直接 Invalid Date ——
 * 演示投 iPad 时全站时间栏会炸，所以所有时间必须过这一层。
 */

export function parseTs(value?: string | null): Date | null {
  if (!value) return null
  const normalized = value.includes('T') ? value : value.replace(' ', 'T')
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

const pad = (n: number) => String(n).padStart(2, '0')

/** `11-14 09:30:05`；解析失败返回 `—`，绝不输出 Invalid Date */
export function formatClock(value?: string | null): string {
  const date = parseTs(value)
  if (!date) return '—'
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

/** `09:30` */
export function formatTime(value?: string | null): string {
  const date = parseTs(value)
  if (!date) return '—'
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function tsMillis(value?: string | null): number | null {
  const date = parseTs(value)
  return date ? date.getTime() : null
}
