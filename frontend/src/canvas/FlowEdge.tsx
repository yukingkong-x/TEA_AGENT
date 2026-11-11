import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type EdgeProps } from '@xyflow/react'

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
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  })
  const active = Boolean((data as { active?: boolean } | undefined)?.active)
  const reduce =
    typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

  return (
    <>
      <BaseEdge
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke: active ? '#2F7A4A' : '#8A948C',
          strokeWidth: active ? 2 : 1.25,
          strokeDasharray: active ? '7 5' : undefined,
        }}
        className={active && !reduce ? 'edge-flow' : undefined}
      />
      {active && !reduce ? (
        <circle r="3.5" fill="#2F7A4A">
          <animateMotion dur="1.2s" repeatCount="indefinite" path={path} />
        </circle>
      ) : null}
      {label ? (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan absolute rounded-btn bg-panel px-1.5 py-0.5 text-[12px] text-dim"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  )
}
