import { useEffect, useState } from 'react'

export function Clock() {
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(id)
  }, [])

  const text = new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai',
  }).format(now)

  return (
    <time dateTime={now.toISOString()} className="num text-xs leading-none text-mute">
      {text}
    </time>
  )
}
