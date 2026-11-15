export function Markdown({ source }: { source: string }) {
  const lines = source.split('\n')
  return (
    <div className="grid gap-2 text-sm leading-normal text-paper">
      {lines.map((line, index) => {
        if (!line.trim()) return null
        if (line.startsWith('# ')) return <h2 key={index}>{line.slice(2)}</h2>
        if (line.startsWith('## ')) return <h3 key={index}>{line.slice(3)}</h3>
        if (line.startsWith('- ')) return <p key={index}>{line.slice(2)}</p>
        return <p key={index}>{line}</p>
      })}
    </div>
  )
}
