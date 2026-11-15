import '@fontsource/noto-sans-sc/latin-400.css'
import '@fontsource/noto-sans-sc/latin-500.css'
import '@fontsource/noto-sans-sc/latin-600.css'
import '@fontsource/noto-sans-sc/chinese-simplified-400.css'
import '@fontsource/noto-sans-sc/chinese-simplified-500.css'
import '@fontsource/noto-sans-sc/chinese-simplified-600.css'
import '@xyflow/react/dist/style.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App } from './App'
import { ShellProvider } from './shell/ShellContext'
import './index.css'

const root = document.getElementById('root')
if (!root) {
  throw new Error('找不到根节点')
}

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <ShellProvider>
        <App />
      </ShellProvider>
    </BrowserRouter>
  </StrictMode>,
)
