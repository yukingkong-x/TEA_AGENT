import type { ReactNode } from 'react'

/**
 * 日报/报告正文渲染器。
 *
 * 后端 content_md 是轻量 Markdown（标题/引用/表格/列表/加粗），之前只按行切片，
 * `**`、`>`、`|---|` 这些记号会原样漏到页面上。这里做成小块解析：
 * 块级（标题、引用、表格、列表、分隔线）按行归类，行内只认 **加粗** 和 `行内代码`，
 * 其余符号一律剥掉，保证页面出现的全是干净的排版。
 */

function inline(text: string): ReactNode[] {
  // 先按行内代码切，避免代码里的 ** 被误认成加粗
  const nodes: ReactNode[] = []
  const codeParts = text.split(/`([^`]+)`/g)
  codeParts.forEach((part, i) => {
    if (i % 2 === 1) {
      nodes.push(
        <code key={`c${i}`} className="rounded bg-panel2 px-1 py-0.5 font-mono text-[12px] text-tea">
          {part}
        </code>,
      )
      return
    }
    // **加粗**：成对处理，孤立的单个 ** 直接丢弃
    const boldParts = part.split(/\*\*([^*]+)\*\*/g)
    boldParts.forEach((seg, j) => {
      if (!seg) return
      nodes.push(j % 2 === 1 ? <strong key={`b${i}-${j}`}>{seg}</strong> : <span key={`s${i}-${j}`}>{seg}</span>)
    })
  })
  return nodes
}

function isTableRow(line: string): boolean {
  const t = line.trim()
  return t.startsWith('|') && t.endsWith('|') && t.length > 2
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .slice(1, -1)
    .split('|')
    .map((cell) => cell.trim())
}

function isSeparatorRow(line: string): boolean {
  const cells = splitRow(line)
  return cells.length > 0 && cells.every((cell) => /^:?-{2,}:?$/.test(cell))
}

export function Markdown({ source }: { source: string }) {
  const lines = source.split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  let key = 0

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    if (!trimmed) {
      i += 1
      continue
    }

    // 分隔线
    if (/^-{3,}$|^\*{3,}$/.test(trimmed)) {
      blocks.push(<hr key={key++} className="border-line" />)
      i += 1
      continue
    }

    // 标题（最多三级，日报只用到 ##）
    const heading = /^(#{1,3})\s+(.*)$/.exec(trimmed)
    if (heading) {
      const level = heading[1].length
      const text = inline(heading[2].replace(/#+\s*$/, ''))
      if (level === 1) {
        blocks.push(
          <h2 key={key++} className="mt-2 text-lg font-medium text-paper">
            {text}
          </h2>,
        )
      } else if (level === 2) {
        blocks.push(
          <h3 key={key++} className="mt-1 text-base font-medium text-paper">
            {text}
          </h3>,
        )
      } else {
        blocks.push(
          <p key={key++} className="text-sm font-medium text-paper">
            {text}
          </p>,
        )
      }
      i += 1
      continue
    }

    // 引用行（> 结论：…）：渲染成左侧茶绿引线的结论条
    if (trimmed.startsWith('>')) {
      const quote: string[] = []
      while (i < lines.length && lines[i].trim().startsWith('>')) {
        quote.push(lines[i].trim().replace(/^>\s?/, ''))
        i += 1
      }
      blocks.push(
        <blockquote
          key={key++}
          className="rounded-r-lg border-l-2 border-tea bg-tea/10 px-3 py-2 text-sm leading-relaxed text-paper"
        >
          {quote.map((row, idx) => (
            <p key={idx}>{inline(row)}</p>
          ))}
        </blockquote>,
      )
      continue
    }

    // 表格：连续的 |…| 行，分隔行不渲染
    if (isTableRow(trimmed)) {
      const rows: string[][] = []
      while (i < lines.length && isTableRow(lines[i].trim())) {
        if (!isSeparatorRow(lines[i].trim())) rows.push(splitRow(lines[i].trim()))
        i += 1
      }
      const [head, ...body] = rows
      blocks.push(
        <div key={key++} className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full border-collapse text-[13px] leading-snug">
            {head ? (
              <thead>
                <tr className="bg-tea/10">
                  {head.map((cell, c) => (
                    <th key={c} className="px-2.5 py-1.5 text-left font-medium text-paper">
                      {inline(cell)}
                    </th>
                  ))}
                </tr>
              </thead>
            ) : null}
            {body.length ? (
              <tbody>
                {body.map((row, r) => (
                  <tr key={r} className="border-t border-line">
                    {row.map((cell, c) => (
                      <td key={c} className="px-2.5 py-1.5 align-top text-paper/90">
                        {inline(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            ) : null}
          </table>
        </div>,
      )
      continue
    }

    // 列表：- / * / 1. 开头，圆点样式替代原始符号
    const listMatch = /^([-*]|\d+[.)])\s+(.*)$/.exec(trimmed)
    if (listMatch) {
      const items: { marker: string; text: string }[] = []
      while (i < lines.length) {
        const m = /^([-*]|\d+[.)])\s+(.*)$/.exec(lines[i].trim())
        if (!m) break
        items.push({ marker: m[1], text: m[2] })
        i += 1
      }
      const ordered = /^\d/.test(items[0].marker)
      blocks.push(
        ordered ? (
          <ol key={key++} className="ml-4 list-decimal space-y-1 text-sm leading-relaxed text-paper">
            {items.map((item, idx) => (
              <li key={idx}>{inline(item.text)}</li>
            ))}
          </ol>
        ) : (
          <ul key={key++} className="ml-4 list-disc space-y-1 text-sm leading-relaxed text-paper">
            {items.map((item, idx) => (
              <li key={idx}>{inline(item.text)}</li>
            ))}
          </ul>
        ),
      )
      continue
    }

    // 普通段落：剥掉残留的行内记号（孤立的 **、* 等）
    blocks.push(
      <p key={key++} className="text-sm leading-relaxed text-paper">
        {inline(trimmed.replace(/\*+/g, ''))}
      </p>,
    )
    i += 1
  }

  return <div className="grid gap-2.5 text-paper">{blocks}</div>
}
