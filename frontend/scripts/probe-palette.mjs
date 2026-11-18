/**
 * 命令面板验收（CDP 真按键，不用假数据）。
 *
 * 判定：
 * 1. Ctrl+K 能弹出面板，焦点落在输入框
 * 2. 输入「报告」能过滤出对应项，且命中文字被 <mark> 高亮
 * 3. 输入「?土壤湿度45%，今天该浇水吗？」回车 → 出现答案 + 引用，且数值护栏生效
 * 4. Esc 回菜单、再 Esc 关闭
 * 5. 全程无 console error
 *
 * 用法：node frontend/scripts/probe-palette.mjs [baseUrl]
 */
import { spawn } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'

const BASE = (process.argv[2] || 'http://localhost:5173').replace(/\/+$/, '')
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9351
const SHOT = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/check/palette.png'
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/palette_profile'
rmSync(profile, { recursive: true, force: true })
mkdirSync(profile, { recursive: true })

const chrome = spawn(
  CHROME,
  ['--headless=new', '--disable-gpu', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--window-size=1440,1000', 'about:blank'],
  { stdio: 'ignore' },
)
await new Promise((r) => setTimeout(r, 2500))
const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()
const page = list.find((i) => i.type === 'page')
const ws = new WebSocket(page.webSocketDebuggerUrl)
let id = 0
const pend = new Map()
const send = (method, params) =>
  new Promise((res) => {
    const i = ++id
    pend.set(i, res)
    ws.send(JSON.stringify({ id: i, method, params }))
  })
ws.onmessage = (e) => {
  const m = JSON.parse(e.data)
  if (m.id && pend.has(m.id)) {
    pend.get(m.id)(m.result)
    pend.delete(m.id)
  }
}
await new Promise((r) => (ws.onopen = r))
await send('Runtime.enable')
await send('Page.enable')

const errors = []
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data)
  if (m.method === 'Runtime.exceptionThrown') errors.push('EXC: ' + String(m.params.exceptionDetails.exception?.description || '').slice(0, 300))
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push('ERR: ' + m.params.args.map((a) => a.value ?? '').join(' ').slice(0, 300))
})

const ev = async (expression) => (await send('Runtime.evaluate', { awaitPromise: true, returnByValue: true, expression })).result?.value
const key = async (k, code, vk, modifiers = 0) => {
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: k, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, modifiers })
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: k, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, modifiers })
}
const ctrlK = async () => {
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17, modifiers: 2 })
  await key('k', 'KeyK', 75, 2)
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17 })
}
const type = async (text) => {
  await send('Input.insertText', { text })
}

await send('Page.navigate', { url: `${BASE}/` })
await new Promise((r) => setTimeout(r, 3500))

const report = {}

// 1) Ctrl+K
await ctrlK()
await new Promise((r) => setTimeout(r, 400))
report.opened = await ev(`!!document.querySelector('[role="dialog"][aria-label="命令面板"]')`)
report.focused = await ev(`document.activeElement?.getAttribute('aria-label')`)

// 2) 过滤 + 高亮
await type('报告')
await new Promise((r) => setTimeout(r, 300))
report.filtered = await ev(`(()=>{const rows=[...document.querySelectorAll('[data-row]')];return {n:rows.length,texts:rows.map(r=>r.innerText.split('\\n')[0])}})()`)
report.highlight = await ev(`[...document.querySelectorAll('mark')].map(m=>m.textContent)`)

// 3) 清空后问 AI
await ev(`(()=>{const i=document.querySelector('input[aria-label="搜索或提问"]');const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(i,'');i.dispatchEvent(new Event('input',{bubbles:true}))})()`)
await new Promise((r) => setTimeout(r, 200))
await type('?土壤湿度45%，今天该浇水吗？')
await new Promise((r) => setTimeout(r, 300))
await key('Enter', 'Enter', 13)
await new Promise((r) => setTimeout(r, 30000))

report.answerText = await ev(`(()=>{const d=document.querySelector('[role="dialog"][aria-label="命令面板"]');return d? d.innerText.replace(/\\s+/g,' ').slice(0,520):'面板已关闭'})()`)
report.citationCount = await ev(`document.querySelectorAll('[role="dialog"] .line-clamp-2').length`)
const shot = await send('Page.captureScreenshot', { format: 'png' })
writeFileSync(SHOT, Buffer.from(shot.data, 'base64'))

// 4) Esc 两次
await key('Escape', 'Escape', 27)
await new Promise((r) => setTimeout(r, 300))
report.backToMenu = await ev(`!!document.querySelector('input[aria-label="搜索或提问"]')`)
await key('Escape', 'Escape', 27)
await new Promise((r) => setTimeout(r, 300))
report.closed = await ev(`!document.querySelector('[role="dialog"][aria-label="命令面板"]')`)

console.log(JSON.stringify({ ...report, consoleErrors: errors.slice(0, 5) }, null, 2))
console.log('截图:', SHOT)

chrome.kill()
process.exit(0)
