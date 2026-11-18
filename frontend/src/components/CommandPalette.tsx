/**
 * 命令面板（Ctrl/⌘ + K）：一个入口同时解决「跳页面」「查资料」「问 AI」。
 *
 * 三种状态：
 * 1. 菜单模式：输入过滤导航项，命中文字高亮，↑↓ 选择、Enter 进入；
 * 2. 问 AI：输入框里以 `?` 开头，或选中「问 AI」那一项 → 调 /api/qa/ask；
 * 3. 答案态：展示答案 + 引用卡片，Esc 回菜单，再 Esc 关闭。
 *
 * 为什么答案要单独一态而不是弹窗上面再弹一层：引用可能有好几条，
 * 需要滚动看；叠弹窗会让「关闭」到底关哪一层变得含糊。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { endpoints } from '../api/endpoints'
import type { QaAnswerDto } from '../api/types'
import { navItems } from '../data/nav'
import { Icon } from './Icon'

type Props = {
  open: boolean
  onClose: () => void
}

type Row = { kind: 'nav'; to: string; label: string } | { kind: 'ask'; question: string }

/** 命中片段高亮：把 query 在文本里出现的位置切开上色，不区分大小写 */
function Highlight({ text, query }: { text: string; query: string }) {
  const q = query.trim().toLowerCase()
  if (!q) return <>{text}</>
  const at = text.toLowerCase().indexOf(q)
  if (at < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, at)}
      <mark className="rounded bg-tea/15 px-0.5 text-tea">{text.slice(at, at + q.length)}</mark>
      {text.slice(at + q.length)}
    </>
  )
}

/** 引用摘要去 Markdown 记号：知识库切片是原文档片段，常带 **加粗**、#、> 这些符号 */
function plain(text: string) {
  return text
    .replace(/[*`]/g, '')
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/^>\s*/gm, '')
}

/**
 * 答案轻量渲染：只处理三类东西——**加粗**、[n] 引用、换行分段。
 * 不上完整 Markdown 解析器：答案是我们自己的提示词约束出来的短文本，
 * 引入 marked/react-markdown 反而多一个依赖和一个 XSS 面积。
 * [n] 上色后和下面的引用卡片一一对应，用户能点着对。
 */
function RichAnswer({ text }: { text: string }) {
  const boldSplit = /(\*\*[^*]+\*\*)/g
  const refSplit = /(\[\d+\])/g

  const inline = (source: string, keyBase: string): React.ReactNode[] => {
    const nodes: React.ReactNode[] = []
    let index = 0
    for (const part of source.split(boldSplit)) {
      if (!part) continue
      if (part.startsWith('**') && part.endsWith('**')) {
        nodes.push(
          <strong key={`${keyBase}-b${index++}`} className="font-semibold text-paper">
            {part.slice(2, -2)}
          </strong>,
        )
        continue
      }
      for (const ref of part.split(refSplit)) {
        if (!ref) continue
        if (/^\[\d+\]$/.test(ref)) {
          nodes.push(
            <span key={`${keyBase}-r${index++}`} className="num rounded bg-tea/10 px-1 text-tea">
              {ref}
            </span>,
          )
        } else {
          nodes.push(<span key={`${keyBase}-t${index++}`}>{ref}</span>)
        }
      }
    }
    return nodes
  }

  return (
    <div className="grid gap-1.5">
      {text
        .split('\n')
        .filter((line) => line.trim())
        .map((line, i) => (
          <p key={i} className="text-base leading-relaxed text-paper">
            {inline(line, `p${i}`)}
          </p>
        ))}
    </div>
  )
}

export function CommandPalette({ open, onClose }: Props) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const [answer, setAnswer] = useState<QaAnswerDto | null>(null)
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  /** `?` 开头 = 明确要问 AI；否则按菜单搜 */
  const askMode = query.trimStart().startsWith('?')
  const keyword = askMode ? query.trimStart().slice(1).trim() : query.trim()

  const rows = useMemo<Row[]>(() => {
    const q = keyword.toLowerCase()
    const nav = navItems
      .filter((item) => {
        if (!q) return true
        const haystack = [item.label, item.to, ...item.keywords].join(' ').toLowerCase()
        return haystack.includes(q)
      })
      .map((item) => ({ kind: 'nav' as const, to: item.to, label: item.label }))

    // 有输入就先给「问 AI」这一项，符合「想不到去哪一页 → 直接问」的直觉
    if (keyword) {
      return [{ kind: 'ask' as const, question: keyword }, ...nav]
    }
    return nav
  }, [keyword])

  // 每次打开重置状态；关闭时把焦点还给原来的元素（通常是侧栏那颗按钮）
  useEffect(() => {
    if (!open) return
    setQuery('')
    setCursor(0)
    setAnswer(null)
    setError('')
    setAsking(false)
    const timer = window.setTimeout(() => inputRef.current?.focus(), 30)
    return () => window.clearTimeout(timer)
  }, [open])

  useEffect(() => {
    if (open) return
    setQuery('')
    setAnswer(null)
    setError('')
  }, [open])

  const runAsk = useCallback(async (question: string) => {
    const text = question.trim()
    if (!text || asking) return
    setAsking(true)
    setError('')
    setAnswer(null)
    try {
      setAnswer(await endpoints.askQa(text))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setAsking(false)
    }
  }, [asking])

  const choose = useCallback(
    (row: Row | undefined) => {
      if (!row) return
      if (row.kind === 'nav') {
        navigate(row.to)
        onClose()
        return
      }
      void runAsk(row.question)
    },
    [navigate, onClose, runAsk],
  )

  // 键盘：全局开关 + 面板内上下选择
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const meta = event.metaKey || event.ctrlKey
      if (meta && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        if (open) onClose()
        else window.dispatchEvent(new CustomEvent('zhiqiu:palette'))
        return
      }
      if (!open) return
      if (event.key === 'Escape') {
        event.preventDefault()
        // 答案态 → 先回菜单；菜单态 → 关闭
        if (answer || error) {
          setAnswer(null)
          setError('')
          inputRef.current?.focus()
        } else {
          onClose()
        }
        return
      }
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setCursor((value) => Math.min(value + 1, rows.length - 1))
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault()
        setCursor((value) => Math.max(value - 1, 0))
      }
      if (event.key === 'Enter') {
        event.preventDefault()
        if (answer || error) return
        choose(rows[cursor])
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose, rows, cursor, choose, answer, error])

  // 选中项滚进视野（列表可能比面板高）
  useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>(`[data-row="${cursor}"]`)
    node?.scrollIntoView({ block: 'nearest' })
  }, [cursor, rows.length])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]" role="dialog" aria-modal="true" aria-label="命令面板">
      <button type="button" className="absolute inset-0 cursor-default bg-[#0d1f16]/35 backdrop-blur-[3px]" aria-label="关闭命令面板" onClick={onClose} />

      <div className="relative w-full max-w-[680px] overflow-hidden rounded-card border border-white/70 bg-white/85 shadow-[0_24px_80px_-24px_rgba(16,40,28,0.45)] backdrop-blur-2xl">
        <div className="flex items-center gap-3 border-b border-line/70 px-4 py-3">
          <Icon name={askMode ? 'spark' : 'search'} variant="current" className={askMode ? 'text-tea' : 'text-mute'} />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setCursor(0)
              setAnswer(null)
              setError('')
            }}
            placeholder="搜索页面，或输入问题后回车问 AI（前缀 ? 可直接问）"
            className="h-10 w-full bg-transparent text-lg text-paper placeholder:text-mute focus:outline-none"
            aria-label="搜索或提问"
          />
          {query ? (
            <button
              type="button"
              aria-label="清空输入"
              title="清空输入"
              className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-mute transition-colors hover:bg-[#F2F4F3] hover:text-paper"
              onClick={() => {
                // 一键清空整行输入，顺手把答案/报错回菜单态，焦点留在输入框继续打
                setQuery('')
                setCursor(0)
                setAnswer(null)
                setError('')
                inputRef.current?.focus()
              }}
            >
              <Icon name="close" width={14} height={14} variant="current" />
            </button>
          ) : null}
          <kbd className="shrink-0 rounded-md border border-line bg-white/70 px-1.5 py-0.5 text-xs text-mute">Esc</kbd>
        </div>

        {answer ? (
          <div className="max-h-[52vh] overflow-y-auto px-5 py-4">
            <div className="flex items-start gap-2">
              <Icon name="spark" className="mt-1 shrink-0 text-tea" />
              <div className="min-w-0 flex-1">
                <RichAnswer text={answer.answer ?? ''} />
                {answer.degraded ? (
                  <p className="mt-2 text-sm text-warn">模型降级：{answer.reason || '未配置 Key 或被限流'}</p>
                ) : null}
                {answer.guarded ? <p className="mt-2 text-sm text-mute">数值结论已由平台拦截，避免模型心算出错。</p> : null}
                {answer.citations.length ? (
                  <div className="mt-4 grid gap-2">
                    <p className="text-sm text-mute">引用资料（{answer.citations.length}）</p>
                    {answer.citations.map((hit) => (
                      <div key={`${hit.index}-${hit.doc_id}`} className="rounded-xl border border-line bg-panel2/50 px-3 py-2">
                        <p className="text-sm text-tea">
                          [{hit.index}] {hit.title}
                        </p>
                        <p className="mt-1 line-clamp-2 text-sm text-dim">{plain(hit.snippet)}</p>
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="mt-4 flex items-center gap-3 text-sm text-mute">
                  <span className="num">{answer.latency_ms ?? 0} ms</span>
                  {answer.provider ? <span>· {answer.provider}</span> : null}
                  <button type="button" className="ml-auto text-tea" onClick={() => setAnswer(null)}>
                    再问一个
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : asking ? (
          <div className="flex items-center gap-3 px-5 py-8 text-base text-dim">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-tea/30 border-t-tea" />
            正在检索知识库并生成回答…
          </div>
        ) : error ? (
          <div className="px-5 py-6">
            <p className="text-base text-danger">{error}</p>
            <button type="button" className="mt-3 text-sm text-tea" onClick={() => keyword && runAsk(keyword)}>
              重试
            </button>
          </div>
        ) : (
          <div ref={listRef} className="max-h-[46vh] overflow-y-auto py-2">
            {rows.length === 0 ? (
              <p className="px-5 py-6 text-base text-mute">没有匹配的页面。直接按 Enter 把它当问题问 AI。</p>
            ) : (
              rows.map((row, index) => {
                const active = index === cursor
                return (
                  <button
                    key={row.kind === 'nav' ? row.to : 'ask'}
                    type="button"
                    data-row={index}
                    onMouseEnter={() => setCursor(index)}
                    onClick={() => choose(row)}
                    className={`flex w-full items-center gap-3 px-4 py-2.5 text-left ${active ? 'bg-panel2' : 'hover:bg-[#F7F8FA]'}`}
                  >
                    <span className={active ? 'text-tea' : 'text-mute'}>
                      <Icon name={row.kind === 'ask' ? 'spark' : navItems.find((item) => item.to === row.to)?.icon ?? 'board'} />
                    </span>
                    <span className="min-w-0 flex-1">
                      {row.kind === 'ask' ? (
                        <>
                          <span className="block truncate text-base text-paper">
                            问 AI：<span className="text-tea">{row.question}</span>
                          </span>
                          <span className="block truncate text-sm text-mute">检索知识库后回答，带引用</span>
                        </>
                      ) : (
                        /* 导航行不再带关键词小字（zk · dashboard · home 那行），keywords 仍参与搜索匹配 */
                        <span className="block truncate text-base text-paper">
                          <Highlight text={row.label} query={keyword} />
                        </span>
                      )}
                    </span>
                    {active ? <Icon name="enter" variant="current" className="shrink-0 text-mute" /> : null}
                  </button>
                )
              })
            )}
          </div>
        )}

        <div className="flex items-center gap-4 border-t border-line/70 px-4 py-2 text-xs text-mute">
          <span>↑↓ 选择</span>
          <span>Enter 确认</span>
          <span>? 问 AI</span>
          <span className="ml-auto">Ctrl / ⌘ + K</span>
        </div>
      </div>
    </div>
  )
}
