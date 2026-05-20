import { useMemo } from 'react'
import { GitBranch } from 'lucide-react'

interface GraphNode {
  name: string
  edge_count: number
}

interface GraphEdge {
  id: string
  source: string
  target: string
  join_type: string
  is_verified: boolean
}

interface TableRelationGraphProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  width?: number
  height?: number
}

const NODE_COLORS = ['#2563eb', '#16a34a', '#ca8a04', '#9333ea', '#0891b2', '#dc2626', '#ea580c', '#4f46e5', '#059669', '#db2777']
const HIGHLIGHT_COLOR = '#3b82f6'

function layoutNodes(nodes: GraphNode[], edges: GraphEdge[], width: number, height: number) {
  // Simple layered layout based on edge direction (topological sort)
  const nodeNameSet = new Set(nodes.map(n => n.name))
  const inDegree = new Map<string, number>()
  const outEdges = new Map<string, string[]>()
  const adjList = new Map<string, string[]>()

  for (const n of nodes) {
    inDegree.set(n.name, 0)
    adjList.set(n.name, [])
  }
  for (const e of edges) {
    if (!nodeNameSet.has(e.source) || !nodeNameSet.has(e.target)) continue
    const deg = inDegree.get(e.target) ?? 0
    inDegree.set(e.target, deg + 1)
    const outs = adjList.get(e.source) || []
    outs.push(e.target)
    adjList.set(e.source, outs)
    const oe = outEdges.get(e.source) || []
    oe.push(e.target)
    outEdges.set(e.source, oe)
  }

  // BFS layers
  const layers: string[][] = []
  const assigned = new Set<string>()
  const queue: string[] = []
  for (const [name, deg] of inDegree) {
    if (deg === 0) queue.push(name)
  }

  while (queue.length > 0) {
    layers.push([...queue])
    const next: string[] = []
    for (const cur of queue) {
      assigned.add(cur)
      for (const dep of (adjList.get(cur) || [])) {
        if (assigned.has(dep)) continue
        const deg = (inDegree.get(dep) ?? 1) - 1
        inDegree.set(dep, deg)
        if (deg === 0 && !next.includes(dep)) next.push(dep)
      }
    }
    queue.length = 0
    queue.push(...next)
  }

  // Remaining nodes in 0deg
  const orphans = nodes.filter(n => !assigned.has(n.name))
  if (orphans.length > 0) layers.push(orphans.map(n => n.name))

  // Compute positions
  const positions = new Map<string, { x: number; y: number }>()
  const PAD_X = 80
  const PAD_Y = 50

  for (let li = 0; li < layers.length; li++) {
    const layer = layers[li]
    const y = PAD_Y + (li / Math.max(1, layers.length - 1)) * (height - PAD_Y * 2)
    for (let ni = 0; ni < layer.length; ni++) {
      const x = PAD_X + (ni / Math.max(1, layer.length - 1)) * (width - PAD_X * 2)
      positions.set(layer[ni], { x, y })
    }
  }

  return { positions, layers }
}

export default function TableRelationGraph({ nodes, edges, width = 700, height = 400 }: TableRelationGraphProps) {
  const { positions, layers } = useMemo(
    () => layoutNodes(nodes, edges, width, height),
    [nodes, edges, width, height],
  )

  if (nodes.length === 0) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>
        <GitBranch size={40} />
        <p style={{ marginTop: 8 }}>暂无关系图数据</p>
      </div>
    )
  }

  const nodePositions = [...positions.entries()]
  const edgeLines = edges.filter(e => positions.has(e.source) && positions.has(e.target))

  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, overflow: 'hidden', background: '#fafbfc' }}>
      <svg width={width} height={height} style={{ display: 'block' }}>
        {/* Grid */}
        <defs>
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#f0f0f0" strokeWidth="0.5" />
          </pattern>
          <marker id="arrowHead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
            <polygon points="0 0, 8 3, 0 6" fill="#9ca3af" />
          </marker>
        </defs>
        <rect width={width} height={height} fill="url(#grid)" />

        {/* Edges */}
        {edgeLines.map((e) => {
          const src = positions.get(e.source)!
          const tgt = positions.get(e.target)!
          return (
            <g key={e.id}>
              <line
                x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
                stroke={e.is_verified ? '#16a34a' : '#d1d5db'}
                strokeWidth={e.is_verified ? 2 : 1.2}
                markerEnd={e.is_verified ? 'url(#arrowHead)' : undefined}
              />
              {/* Label */}
              <text
                x={(src.x + tgt.x) / 2} y={(src.y + tgt.y) / 2 - 6}
                textAnchor="middle" fontSize={9} fill="#6b7280"
              >
                {e.join_type}
              </text>
            </g>
          )
        })}

        {/* Nodes */}
        {nodePositions.map(([name, pos], i) => {
          const node = nodes.find(n => n.name === name)
          const color = node?.edge_count ? HIGHLIGHT_COLOR : NODE_COLORS[i % NODE_COLORS.length]
          return (
            <g key={name}>
              <rect
                x={pos.x - 50} y={pos.y - 18} width={100} height={36}
                rx={8} fill="#fff" stroke={color} strokeWidth={1.5}
                filter="drop-shadow(0 1px 2px rgba(0,0,0,0.06))"
              />
              <text
                x={pos.x} y={pos.y + 5}
                textAnchor="middle" fontSize={11} fontWeight={600} fill="#374151"
              >
                {name.length > 14 ? name.slice(0, 13) + '…' : name}
              </text>
            </g>
          )
        })}
      </svg>

      {/* Legend */}
      <div style={{ padding: '8px 12px', borderTop: '1px solid #e5e7eb', fontSize: 11, color: '#6b7280', display: 'flex', gap: 16 }}>
        <span>● 已验证 (绿色箭头)</span>
        <span>○ 未验证 (灰色线)</span>
        <span>{nodes.length} 表, {edges.length} 关系</span>
        <span>{layers.length} 层级</span>
      </div>
    </div>
  )
}
