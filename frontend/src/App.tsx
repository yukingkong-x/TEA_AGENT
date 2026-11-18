import { useEffect, useState } from 'react'
import { Route, Routes, useNavigate } from 'react-router-dom'
import { CommandPalette } from './components/CommandPalette'
import { ConfirmDialog } from './components/ConfirmDialog'
import { Icon } from './components/Icon'
import { Sidebar } from './components/Sidebar'
import { CanvasPage } from './pages/CanvasPage'
import { ChatPage } from './pages/ChatPage'
import { DashboardPage } from './pages/DashboardPage'
import { ReportPage } from './pages/ReportPage'
import { SettingsPage } from './pages/SettingsPage'
import { TasksPage } from './pages/TasksPage'

export function App() {
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)

  // 快捷键监听放在 CommandPalette 内部（它常驻挂载），这里只接它抛出的开启信号，
  // 免得两处都监听 Ctrl+K 导致「开一次又立刻被关掉」。
  useEffect(() => {
    const open = () => setPaletteOpen(true)
    window.addEventListener('zhiqiu:palette', open)
    return () => window.removeEventListener('zhiqiu:palette', open)
  }, [])

  return (
    <div className="relative isolate flex h-dvh w-screen max-w-[100vw] overflow-hidden bg-[#F2F5F7] text-paper">
      {/*
       * 环境光：大面积柔光渐变 + 两团低饱和有色光晕 + 两道路带感的白色光弧。
       * 弧形光晕是整个「磨砂玻璃」手感的地基——玻璃卡片的 backdrop-blur 有东西可磨，
       * 卡片边缘那道白高光也才有来处；纯色底上做毛玻璃永远是脏的灰。
       */}
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden" aria-hidden="true">
        <div className="ambient-base" />
        <div className="ambient-orb -left-[16%] -top-[24%] h-[700px] w-[700px] bg-[#B7E0CA] opacity-40" />
        <div className="ambient-orb -bottom-[30%] -right-[12%] h-[760px] w-[760px] bg-[#C4D7EE] opacity-35" />
        <div className="ambient-orb left-[34%] top-[38%] h-[560px] w-[560px] bg-[#F3E6C4] opacity-25" />
        <div className="ambient-arc ambient-arc-a" />
        <div className="ambient-arc ambient-arc-b" />
      </div>

      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded-btn focus:bg-panel focus:px-3 focus:py-2"
      >
        跳到主要内容
      </a>
      {menuOpen ? (
        <button type="button" className="fixed inset-0 z-20 bg-paper/30 md:hidden" aria-label="关闭导航" onClick={() => setMenuOpen(false)} />
      ) : null}
      <Sidebar
        open={menuOpen}
        onNavigate={() => setMenuOpen(false)}
        onStart={() => setConfirmOpen(true)}
        onAsk={() => setPaletteOpen(true)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="no-print flex h-12 shrink-0 items-center px-4 md:hidden">
          <button type="button" className="btn btn-ghost h-11 w-11 px-0" aria-label="打开导航" onClick={() => setMenuOpen(true)}>
            <Icon name="menu" variant="current" />
          </button>
        </div>
        <main id="main" className="flex min-h-0 flex-1 flex-col overflow-x-hidden overflow-y-auto px-4 pb-4 pt-4 sm:px-5">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/canvas" element={<CanvasPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/report" element={<ReportPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <ConfirmDialog
        open={confirmOpen}
        title="开始巡园"
        body="按默认工作流走一轮 A区茶垄。点确认后画布会立刻向后端下发执行，节点动画跟着引擎事件亮。"
        confirmLabel="开始巡园"
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false)
          // 不在这一层发 POST：跳过去由画布自己下发，WS 订阅已挂好，前几个节点的事件不会漏。
          navigate('/canvas', { state: { arm: true } })
        }}
      />
    </div>
  )
}
