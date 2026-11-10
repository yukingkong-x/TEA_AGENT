type GardenPhotoProps = {
  src: string
  label: string
}

export function GardenPhoto({ src, label }: GardenPhotoProps) {
  return (
    <div className="h-36 overflow-hidden rounded-card border border-line bg-[#E7F3EA] sm:h-44">
      <img src={src} alt={label} className="h-full w-full object-cover" />
    </div>
  )
}
