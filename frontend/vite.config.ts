import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 后端在 8000，前端只调 /api 与 /ws；换机器只改 VITE_PROXY_TARGET 一处。
// /ws 必须单独配且开 ws:true：socket.ts 的兜底是同源地址，开发态靠这条转发；
// 少了它，`npm run dev` 下大屏一条消息都收不到（页面不报错，只是静默）。
const target = process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target, changeOrigin: true },
      '/ws': { target, changeOrigin: true, ws: true },
    },
  },
})
