import { alertText } from '../data/snapshot'

export function AlertBar() {
  return (
    <div className="flex h-12 items-center gap-3 overflow-hidden rounded-card border border-[#E7D3B4] bg-[#FBF6EF] px-4" role="status">
      <span className="h-2 w-2 shrink-0 rounded-full bg-[#E4B423]" aria-hidden="true" />
      <span className="shrink-0 text-xs leading-none text-[#8A6414]">预警</span>
      <p className="min-w-0 flex-1 truncate text-sm leading-normal text-paper">{alertText}</p>
    </div>
  )
}
