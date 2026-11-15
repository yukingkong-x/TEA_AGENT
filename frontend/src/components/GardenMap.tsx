import type { Device, DeviceStatus } from '../data/snapshot'

const dotClass: Record<DeviceStatus, string> = {
  online: 'bg-leaf breath',
  suspect: 'bg-warn',
  offline: 'bg-mute',
  alarm: 'bg-danger',
}

export function GardenMap({ devices, onSelect }: { devices: Device[]; onSelect: (device: Device) => void }) {
  return (
    <div className="relative overflow-hidden rounded-b-card bg-[#F3F6F2]">
      <svg viewBox="0 0 800 460" className="h-[300px] w-full md:h-[360px]" aria-hidden="true">
        <rect width="800" height="460" fill="#F3F6F2" />
        <path d="M80 64 H720 V396 H80 Z" fill="#E7F3EA" />
        <path d="M116 128 H684 V352 H116 Z" fill="#D7EBD9" />
        {Array.from({ length: 8 }, (_, index) => (
          <path key={index} d={`M132 ${156 + index * 24} H668`} stroke="#7EBE8C" strokeOpacity="0.95" strokeWidth="2" />
        ))}
        <text x="132" y="112" fill="#86909C" fontSize="14" fontFamily="PingFang SC, Noto Sans SC, sans-serif">
          A区茶垄
        </text>
      </svg>
      {devices.map((device) => (
        <button
          key={device.id}
          type="button"
          className="absolute hidden md:block"
          style={{ left: `${device.x}%`, top: `${device.y}%`, transform: 'translate(-50%, -50%)' }}
          onClick={() => onSelect(device)}
        >
          <span className="pointer-events-none absolute bottom-8 left-1/2 w-max -translate-x-1/2 rounded-btn border border-line bg-panel px-3 py-2 text-left shadow-[0_8px_20px_rgba(26,26,26,0.08)]">
            <span className="block text-sm leading-normal text-paper">{device.name}</span>
            <span className="num mt-1 block text-xs leading-none text-tea">{device.reading}</span>
          </span>
          <span className="grid h-11 w-11 place-items-center">
            <span className={`h-3.5 w-3.5 rounded-full ${dotClass[device.status]}`} />
          </span>
        </button>
      ))}
      <ul className="grid gap-2 border-t border-line p-3 md:hidden">
        {devices.map((device) => (
          <li key={device.id}>
            <button
              type="button"
              className="lift flex h-11 w-full items-center gap-3 rounded-btn bg-ink px-3 text-left"
              onClick={() => onSelect(device)}
            >
              <span className={`h-2.5 w-2.5 rounded-full ${dotClass[device.status]}`} aria-hidden="true" />
              <span className="text-sm text-paper">{device.name}</span>
              <span className="num ml-auto text-sm text-tea">{device.reading}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
