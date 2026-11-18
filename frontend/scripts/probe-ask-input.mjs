/**
 * 侧栏版权行删除 + 问 AI 输入框「×」清空 验收：
 * 1. 侧栏底部不再有「不宕机404 · 2026」小字（也不留孤立分隔线）
 * 2. Ctrl+K 打开问 AI 面板 → 输入文字后才出现 × 按钮
 * 3. 点 × → 输入框整行清空、焦点仍在输入框、× 随之消失、Esc 提示还在
 * 4. 0 console error
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { spawn } from 'node:child_process'

const BASE = process.argv[2] ?? 'http://localhost:5173'
const SHOT_DIR = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/ask'
mkdirSync(SHOT_DIR, { recursive: true })
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9397
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, '--user-data-dir=D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/ask_profile', '--window-size=1440,900', 'about:blank'], { stdio: 'ignore' })
await new Promise((r) => setTimeout(r, 2500))
const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()
const page = list.find((i) => i.type === 'page')
const ws = new WebSocket(page.webSocketDebuggerUrl)
let id = 0
const pend = new Map()
const send = (m, p) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: p })) })
const errors = []
ws.onmessage = (e) => {
  const m = JSON.parse(e.data)
  if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.text)
  if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errors.push(m.params.entry.text)
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id) }
}
await new Promise((r) => ws.onopen = r)
const ev = async (ex) => {
  const r = await send('Runtime.evaluate', { awaitPromise: true, returnByValue: true, expression: ex })
  return r?.exceptionDetails ? { err: JSON.stringify(r.exceptionDetails).slice(0, 300) } : r.result?.value
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const shot = async (name) => {
  const cap = await send('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: 1440, height: 900, scale: 1 } })
  writeFileSync(`${SHOT_DIR}/${name}.png`, Buffer.from(cap.data, 'base64'))
}

await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })
await send('Page.navigate', { url: BASE })
await wait(8000)

const sidebar = await ev(`(() => {
  const aside = document.querySelector('aside[aria-label="主导航"]')
  const text = aside ? aside.innerText.replace(/\\s+/g, ' ').trim() : ''
  const tails = aside ? [...aside.children].slice(-3).map((el) => el.tagName + ':' + el.className.slice(0, 40)) : []
  return {
    hasCopyright: /不宕机\\s*404/.test(text),
    navTail: text.slice(-40),
    lastChildTags: tails,
    navBottom: Math.round(aside.querySelector('nav').getBoundingClientRect().bottom),
    asideBottom: Math.round(aside.getBoundingClientRect().bottom),
  }
})()`)
await shot('sidebar')
// 空输入菜单态截图（看导航行是否只剩一行）

// Ctrl+K 打开面板
await ev(`window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }))`)
await wait(500)
const emptyInput = await ev(`(() => {
  const input = document.querySelector('input[aria-label="搜索或提问"]')
  return { panelOpen: Boolean(input), value: input?.value ?? null, hasClear: Boolean(document.querySelector('button[aria-label="清空输入"]')) }
})()`)

// 输入文字（走 React 受控输入：先取 setter 再派发 input 事件）
await ev(`(() => {
  const input = document.querySelector('input[aria-label="搜索或提问"]')
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  setter.call(input, '? 土壤湿度低于多少要浇水')
  input.dispatchEvent(new Event('input', { bubbles: true }))
})()`)
await wait(400)
const filled = await ev(`(() => {
  const clear = document.querySelector('button[aria-label="清空输入"]')
  const input = document.querySelector('input[aria-label="搜索或提问"]')
  const rect = clear?.getBoundingClientRect()
  const inputRect = input?.getBoundingClientRect()
  return {
    value: input?.value ?? null,
    hasClear: Boolean(clear),
    clearSize: rect ? [Math.round(rect.width), Math.round(rect.height)] : null,
    rightOfInput: rect && inputRect ? Math.round(rect.left) >= Math.round(inputRect.right) - 2 : null,
    rowsShown: document.querySelectorAll('[data-row]').length,
  }
})()`)
await shot('palette-filled')

// 点 ×
await ev(`document.querySelector('button[aria-label="清空输入"]').click()`)
await wait(400)
const cleared = await ev(`(() => {
  const input = document.querySelector('input[aria-label="搜索或提问"]')
  return {
    value: input?.value ?? null,
    focused: document.activeElement === input,
    hasClear: Boolean(document.querySelector('button[aria-label="清空输入"]')),
    escHint: document.body.innerText.includes('Esc'),
    rowsShown: document.querySelectorAll('[data-row]').length,
    firstRow: document.querySelector('[data-row]')?.innerText.replace(/\\s+/g, ' ').trim() ?? null,
  }
})()`)
await shot('palette-cleared')

console.log(JSON.stringify({ sidebar, emptyInput, filled, cleared, errors: errors.slice(0, 5) }, null, 2))
console.log('console errors:', errors.length)
ws.close(); chrome.kill(); process.exit(0)
