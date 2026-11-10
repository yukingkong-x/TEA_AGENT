import { alertText } from '../data/snapshot'

export function AlertBar() {
  return (
    <div className="flex h-12 items-center gap-3 overflow-hidden rounded-card border border-[#E7D3B4] bg-[#FBF6EF] px-4" role="status">
      <span className="shrink-0 text-[13px] font-medium text-warn">预警</span>
      <p className="min-w-0 flex-1 truncate text-sm text-paper">{alertText}</p>
    </div>
  )
}
