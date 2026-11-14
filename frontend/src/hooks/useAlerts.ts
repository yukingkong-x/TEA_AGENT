/**
 * 报警条数据源。
 *
 * 后端两处来源，字段不完全一样，统一normalize 成 AlertDto：
 * 1. `GET /api/alerts` —— 有 acknowledged / created_at；
 * 2. WS `alert` —— `core/queries.raise_alert` 推的是 `{id, level, source, message}`，
 *    没有 acknowledged 与 created_at，**不能当成完整行直接用**（队友B 的坑）；
 *    `source` 统一是 `agent:<agent_key>`，展示时把人话补上。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { endpoints } from '../api/endpoints'
import { dashboardSocket } from '../api/socket'
import type { AlertDto } from '../api/types'

const LEVEL_WEIGHT: Record<string, number> = { critical: 3, warning: 2, info: 1 }

export type AlertItem = AlertDto & { at: string }

function normalize(dto: Partial<AlertDto>, fallbackAt = new Date().toISOString()): AlertItem {
  return {
    id: typeof dto.id === 'number' ? dto.id : -Date.now(),
    level: (dto.level ?? 'info') as AlertDto['level'],
    source: dto.source ?? 'system',
    message: dto.message ?? '（没有内容）',
    acknowledged: Boolean(dto.acknowledged),
    created_at: dto.created_at ?? fallbackAt,
    at: dto.created_at ?? fallbackAt,
  }
}

/** source: "agent:scout" → "scout"，其余原样（system / device:xxx） */
export function sourceLabel(source: string) {
  if (source.startsWith('agent:')) return source.slice('agent:'.length)
  if (source.startsWith('device:')) return source.slice('device:'.length)
  return source
}

export function useAlerts() {
  const [rows, setRows] = useState<AlertItem[]>([])
  const [source, setSource] = useState<'backend' | 'local' | 'loading'>('loading')

  const load = useCallback(async () => {
    try {
      const page = await endpoints.alerts({ page: 1, page_size: 50 })
      setRows(page.items.map((item) => normalize(item)))
      setSource('backend')
    } catch {
      setSource('local')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const off = dashboardSocket.on<Partial<AlertDto>>('alert', (data) => {
      if (!data || typeof data.message !== 'string') return
      setRows((current) => {
        const next = normalize(data)
        // 同一条报警可能 REST 先取到、WS 又推一遍，按 id 去重
        if (current.some((item) => item.id === next.id)) return current
        return [next, ...current]
      })
    })
    return off
  }, [])

  const pending = useMemo(
    () =>
      rows
        .filter((item) => !item.acknowledged)
        .sort((a, b) => (LEVEL_WEIGHT[b.level] ?? 0) - (LEVEL_WEIGHT[a.level] ?? 0)),
    [rows],
  )

  const ack = useCallback(async (id: number) => {
    setRows((current) => current.map((item) => (item.id === id ? { ...item, acknowledged: true } : item)))
    try {
      await endpoints.ackAlert(id)
    } catch {
      // ack 失败原地回滚，别让大屏把已确认的报警一直挂着
      setRows((current) => current.map((item) => (item.id === id ? { ...item, acknowledged: false } : item)))
    }
  }, [])

  return { rows, pending, source, reload: load, ack }
}
