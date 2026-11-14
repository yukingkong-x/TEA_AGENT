import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { dashboardSocket, WS_URL } from '../api/socket'
import { endpoints } from '../api/endpoints'
import { ApiError } from '../api/client'

export type RunMode = 'mock' | 'real'
export type LinkState = 'connecting' | 'open' | 'closed'

type ShellValue = {
  mode: RunMode
  setMode: (mode: RunMode) => void
  link: LinkState
  /** WS 已连上（顶栏指示灯与「实时」角标用） */
  live: boolean
  /** 最近一次切模式的失败原因，设置页可提示 */
  lastError: string | null
  wsUrl: string
}

const ShellContext = createContext<ShellValue | null>(null)

export function ShellProvider({ children }: { children: ReactNode }) {
  // 初值只能是 mock：真实模式要等 WS 首帧 mode_changed 才能确定，
  // 硬编码 mock 的话后端已经切 Real 了大屏还显示 Mock。
  const [mode, setModeState] = useState<RunMode>('mock')
  const [link, setLink] = useState<LinkState>('connecting')
  const [lastError, setLastError] = useState<string | null>(null)

  useEffect(() => {
    dashboardSocket.connect()

    const unsubscribe = dashboardSocket.subscribe((message) => {
      if (message.type === '__open') {
        setLink('open')
        return
      }
      if (message.type === '__close') {
        setLink('closed')
        return
      }
      if (message.type === 'mode_changed') {
        const next = (message.data as { mode?: string } | undefined)?.mode
        if (next === 'mock' || next === 'real') setModeState(next)
      }
    })

    return () => {
      unsubscribe()
      dashboardSocket.close()
    }
  }, [])

  const setMode = useCallback((next: RunMode) => {
    setModeState(next)
    setLastError(null)
    // 乐观更新：后端会广播 mode_changed，WS 收到的值才是最终态
    endpoints.setMode(next).catch((err: unknown) => {
      setModeState((current) => (current === next ? 'mock' : current))
      setLastError(err instanceof ApiError ? err.message : '切换失败')
    })
  }, [])

  const value = useMemo<ShellValue>(
    () => ({ mode, setMode, link, live: link === 'open', lastError, wsUrl: WS_URL }),
    [mode, setMode, link, lastError],
  )

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>
}

export function useShell() {
  const value = useContext(ShellContext)
  if (!value) {
    throw new Error('ShellProvider 缺失')
  }
  return value
}
