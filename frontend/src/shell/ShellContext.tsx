import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type RunMode = 'mock' | 'real'
type LinkState = 'open' | 'closed'

type ShellValue = {
  mode: RunMode
  setMode: (mode: RunMode) => void
  link: LinkState
}

const ShellContext = createContext<ShellValue | null>(null)

function useDashboardLink(): LinkState {
  const [link, setLink] = useState<LinkState>('closed')

  useEffect(() => {
    const url = import.meta.env.VITE_WS_URL
    if (!url) return

    let socket: WebSocket | null = null
    let timer = 0
    let stopped = false
    const connect = () => {
      socket = new WebSocket(url)
      socket.onopen = () => setLink('open')
      socket.onclose = () => {
        setLink('closed')
        if (!stopped) timer = window.setTimeout(connect, 5000)
      }
      socket.onerror = () => {
        socket?.close()
      }
    }
    connect()
    return () => {
      stopped = true
      window.clearTimeout(timer)
      socket?.close()
    }
  }, [])

  return link
}

export function ShellProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<RunMode>('mock')
  const link = useDashboardLink()
  const value = useMemo(() => ({ mode, setMode, link }), [mode, link])
  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>
}

export function useShell() {
  const value = useContext(ShellContext)
  if (!value) {
    throw new Error('ShellProvider 缺失')
  }
  return value
}
