import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'

export type RunMode = 'mock' | 'real'

type ShellValue = {
  mode: RunMode
  setMode: (mode: RunMode) => void
}

const ShellContext = createContext<ShellValue | null>(null)

export function ShellProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<RunMode>('mock')
  const value = useMemo(() => ({ mode, setMode }), [mode])
  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>
}

export function useShell() {
  const value = useContext(ShellContext)
  if (!value) {
    throw new Error('ShellProvider 缺失')
  }
  return value
}
