import type { SVGProps } from 'react'

type IconName = 'board' | 'flow' | 'chat' | 'tasks' | 'report' | 'settings' | 'menu' | 'close'

const paths: Record<IconName, string> = {
  board: 'M4 4h6v6H4V4zm10 0h6v6h-6V4zM4 14h6v6H4v-6zm10 2h6v4h-6v-4z',
  flow: 'M5 7h4v4H5V7zm10 0h4v4h-4V7zM7 11v2h10v-2M12 13v4m-5 0h10v4H7v-4z',
  chat: 'M5 6h14v9H8l-3 3V6z',
  tasks: 'M6 6h12M6 12h12M6 18h8',
  report: 'M12 5a7 7 0 1 1 0 14 7 7 0 0 1 0-14zm0 3v4l3 2',
  settings: 'M4 8h10M18 8h2M4 16h2M10 16h10M14 6v4M8 14v4',
  menu: 'M5 7h14M5 12h14M5 17h14',
  close: 'M7 7l10 10M17 7 7 17',
}

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true" {...props}>
      <path d={paths[name]} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
