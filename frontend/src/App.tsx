import { useState } from 'react'
import { Route, Routes, useNavigate } from 'react-router-dom'
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

  return (
    <div className="flex h-dvh w-screen max-w-[100vw] overflow-hidden bg-[#F3F5F8] text-paper">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded-btn focus:bg-panel focus:px-3 focus:py-2"
      >
        跳到主要内容
      </a>
      {menuOpen ? (
        <button type="button" className="fixed inset-0 z-20 bg-paper/30 md:hidden" aria-label="关闭导航" onClick={() => setMenuOpen(false)} />
      ) : null}
      <Sidebar open={menuOpen} onNavigate={() => setMenuOpen(false)} onStart={() => setConfirmOpen(true)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="no-print flex h-12 shrink-0 items-center px-4 md:hidden">
          <button type="button" className="btn btn-ghost h-11 w-11 px-0" aria-label="打开导航" onClick={() => setMenuOpen(true)}>
            <Icon name="menu" />
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
