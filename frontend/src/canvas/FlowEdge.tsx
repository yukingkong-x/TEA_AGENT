import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@xyflow/react'

export function FlowEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  label,
  data,
  markerEnd,
}: EdgeProps) {
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  })
  const active = Boolean((data as { active?: boolean } | undefined)?.active)
  // Self-Loop 回边常显虚线：主链是实线，回流路径一眼分得清（PRD 9.1 的 loop 语义）
  const back = Boolean((data as { back?: boolean } | undefined)?.back)
  const reduce =
    typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

  return (
    <>
      <BaseEdge
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke: active ? '#1F7A45' : back ? '#5A6474' : '#86909C',
          strokeWidth: active ? 2 : 1.25,
          strokeDasharray: active ? '7 5' : back ? '6 4' : undefined,
        }}
        className={active && !reduce ? 'edge-flow' : undefined}
      />
      {active && !reduce ? (
        <circle r="3.5" fill="#1F7A45">
          <animateMotion dur="1.2s" repeatCount="indefinite" path={path} />
        </circle>
      ) : null}
      {label ? (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan absolute rounded-btn bg-panel px-1.5 py-0.5 text-xs leading-none text-mute"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  )
}
