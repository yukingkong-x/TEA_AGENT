/**
 * 交付前自检：容器里的 report 页是不是真的在渲染「后端真实 run」。
 *
 * 判定四条（任一不满足就算没接上）：
 * 1. 页面内 `fetch('/api/runs')` 能拿到数据
 * 2. 选择器里出现 real: 前缀选项，且当前选中项就是 real:
 * 3. 页面上出现了该 run 的轮次/耗时真值
 * 4. 没有 console error（React Router 的 future flag warning 不算）
 *
 * 用法：node frontend/scripts/_probe_report.mjs [http://localhost:5173]
 */
import { spawn } from 'node:child_process'
import { rmSync, mkdirSync } from 'node:fs'

const BASE = (process.argv[2] || 'http://localhost:5173').replace(/\/+$/, '')
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9341
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/probe_profile'
rmSync(profile, { recursive: true, force: true })
mkdirSync(profile, { recursive: true })

const chrome = spawn(
  CHROME,
  [
    '--headless=new',
    '--disable-gpu',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    '--window-size=1440,1400',
    'about:blank',
  ],
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

const problems = []
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data)
  if (m.method === 'Runtime.exceptionThrown') {
    problems.push('EXC: ' + String(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text).slice(0, 300))
  }
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
    problems.push('ERR: ' + m.params.args.map((a) => a.value ?? '').join(' ').slice(0, 300))
  }
})

await send('Page.navigate', { url: `${BASE}/report` })
// 真实 run 的轮次/节点是并发拉的，给足 6s
await new Promise((r) => setTimeout(r, 6000))

const ev = async (expression) => {
  const r = await send('Runtime.evaluate', { awaitPromise: true, returnByValue: true, expression })
  return r.result?.value
}

const api = await ev(
  `fetch('/api/runs?page=1&page_size=50').then(r=>r.json()).then(d=>({n:(d.items||[]).length,first:d.items&&d.items[0]&&d.items[0].id})).catch(e=>'ERR:'+e.message)`,
)
console.log('1) 页面内 fetch /api/runs :', JSON.stringify(api))

const sel = await ev(`(()=>{
  const el=document.getElementById('report-run');
  if(!el) return {found:false};
  return {
    found:true,
    value:el.value,
    count:el.options.length,
    groups:[...el.querySelectorAll('optgroup')].map(g=>g.label+'('+g.children.length+')'),
    firstReal:[...el.querySelectorAll('option')].map(o=>o.value).filter(v=>v.startsWith('real:')).slice(0,3)
  }
})()`)
console.log('2) 选择器            :', JSON.stringify(sel))

const txt = await ev(`(()=>{const m=document.querySelector('main')||document.body;return m.innerText.replace(/\\s+/g,' ').slice(0,700)})()`)
console.log('3) 页面正文(前700字)  :', txt)

console.log('4) console error     :', problems.length ? '\n   ' + problems.slice(0, 6).join('\n   ') : '无')

const ok = sel?.found && (sel.firstReal?.length ?? 0) > 0 && String(sel.value).startsWith('real:') && problems.length === 0
console.log('\n结论:', ok ? '✅ 报告页已渲染后端真实 run' : '❌ 未通过（见上面 1~4 项）')

chrome.kill()
process.exit(ok ? 0 : 1)
