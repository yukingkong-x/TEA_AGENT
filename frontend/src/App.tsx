import { useState } from 'react'
import { Route, Routes, useNavigate } from 'react-router-dom'
import { ConfirmDialog } from './components/ConfirmDialog'
import { Sidebar } from './components/Sidebar'
import { Topbar } from './components/Topbar'
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
    <div className="flex h-dvh overflow-hidden bg-ink text-paper">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded-btn focus:bg-panel focus:px-3 focus:py-2"
      >
        跳到主要内容
      </a>
      {menuOpen ? (
        <button type="button" className="fixed inset-0 z-20 bg-ink/60 md:hidden" aria-label="关闭导航" onClick={() => setMenuOpen(false)} />
      ) : null}
      <Sidebar open={menuOpen} onNavigate={() => setMenuOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onMenu={() => setMenuOpen(true)} onStart={() => setConfirmOpen(true)} />
        <main id="main" className="min-h-0 flex-1 overflow-auto px-4 py-6 sm:px-6">
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
        body="按默认工作流走一轮 A区茶垄。这一步只进入画布，不会给设备下指令。"
        confirmLabel="开始巡园"
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false)
          navigate('/canvas', { state: { armed: true } })
        }}
      />
    </div>
  )
}
