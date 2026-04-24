import React from 'react'
import clsx from 'clsx'
import type { ExecutionGraphData, ExecutionGraphNode } from '../store/chat'
import { t } from '../i18n'

const stageColors: Record<string, string> = {
  REASON: 'from-gray-50 to-gray-100 border-gray-200 text-black',
  DECIDE: 'from-gray-50 to-gray-100 border-gray-200 text-black',
  EXECUTE: 'from-gray-50 to-gray-100 border-gray-200 text-black',
  OBSERVE: 'from-gray-50 to-gray-100 border-gray-200 text-black',
  REFLECT: 'from-gray-50 to-gray-100 border-gray-200 text-black',
  AGENT: 'from-sky-50 to-blue-100 border-blue-200 text-black',
}

function summarizeNode(node: ExecutionGraphNode) {
  if (String(node.type) === 'agent_call') {
    const agentType = String((node.metadata as any)?.agent_type || 'agent')
    const q = String((node.metadata as any)?.query || '')
    const labelMap: Record<string, string> = {
      data: 'DataAgent（数据分析）',
      web: 'WebAgent（联网检索）',
      tool: 'ToolAgent（工具执行）',
      memory: 'MemoryAgent（记忆检索）',
    }
    const label = labelMap[agentType] || `${agentType}Agent`
    return `${label} · ${q.slice(0, 80)}`
  }

  const toolCalls = Array.isArray((node.metadata as any)?.tool_calls) ? (node.metadata as any).tool_calls : []
  if (toolCalls.length) {
    return toolCalls
      .map((call: any) => call?.tool)
      .filter(Boolean)
      .join(', ')
  }
  const observation = typeof (node.metadata as any)?.observation === 'string' ? (node.metadata as any).observation : ''
  if (observation) return observation.slice(0, 120)
  const output = node.output && typeof node.output === 'object' ? JSON.stringify(node.output) : ''
  return output.slice(0, 120)
}

function statusTone(status: string) {
  if (status === 'SUCCESS') return 'bg-emerald-100 text-emerald-700 border-emerald-200'
  if (status === 'FAILED') return 'bg-rose-100 text-rose-700 border-rose-200'
  if (status === 'RUNNING') return 'bg-sky-100 text-sky-700 border-sky-200'
  return 'bg-gray-100 text-gray-700 border-gray-200'
}

export default function ExecutionGraphPanel({ graph, autoExpand = false, collapseOnEvent }: { graph: ExecutionGraphData | null; autoExpand?: boolean; collapseOnEvent?: string }) {
  const [collapsed, setCollapsed] = React.useState(true)
  const [stageFilter, setStageFilter] = React.useState<string>('ALL')
  const [statusFilter, setStatusFilter] = React.useState<string>('ALL')
  const [zoom, setZoom] = React.useState(1)
  const [dragStart, setDragStart] = React.useState<{ x: number; y: number } | null>(null)
  const [offset, setOffset] = React.useState({ x: 0, y: 0 })
  const [selectedNode, setSelectedNode] = React.useState<ExecutionGraphNode | null>(null)
  const [highlightNodeId, setHighlightNodeId] = React.useState<string | null>(null)

  React.useEffect(() => {
    // 默认保持折叠，避免干扰结果浏览
  }, [])

  React.useEffect(() => {
    if (autoExpand) setCollapsed(false)
  }, [autoExpand])

  React.useEffect(() => {
    if (!collapseOnEvent) return
    const onDone = () => setCollapsed(true)
    window.addEventListener(collapseOnEvent, onDone as EventListener)
    return () => window.removeEventListener(collapseOnEvent, onDone as EventListener)
  }, [collapseOnEvent])

  React.useEffect(() => {
    if (!collapseOnEvent) return
    const onDone = () => setCollapsed(true)
    window.addEventListener(collapseOnEvent, onDone as EventListener)
    return () => window.removeEventListener(collapseOnEvent, onDone as EventListener)
  }, [collapseOnEvent])

  React.useEffect(() => {
    // 刷新后始终折叠，不持久化用户展开状态
  }, [collapsed])

  React.useEffect(() => {
    const onSelect = (ev: Event) => {
      const ce = ev as CustomEvent<{ nodeId?: string }>
      const nodeId = ce.detail?.nodeId
      if (!nodeId) return
      setHighlightNodeId(nodeId)
      const node = graph?.nodes?.find((n) => n.id === nodeId)
      if (node) setSelectedNode(node)
      if (collapsed) setCollapsed(false)
    }
    window.addEventListener('opentrace:select-dag-node', onSelect as EventListener)
    return () => window.removeEventListener('opentrace:select-dag-node', onSelect as EventListener)
  }, [graph, collapsed])

  if (!graph || !Array.isArray(graph.nodes) || graph.nodes.length === 0) return null

  const filteredNodes = graph.nodes.filter((n) => {
    if (stageFilter !== 'ALL' && n.stage !== stageFilter) return false
    if (statusFilter !== 'ALL' && n.status !== statusFilter) return false
    return true
  })

  return (
    <div className="mb-4 overflow-hidden rounded-[24px] border border-[var(--border)] bg-[var(--surface)] shadow-[0_4px_16px_rgba(0,0,0,0.06)]">
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <div>
          <div className="text-[11px] uppercase tracking-[0.24em] text-[var(--text-secondary)]">{t('executionGraph.title')}</div>
          <div className="mt-1 text-sm text-[var(--text)]">执行图谱 · {filteredNodes.length}/{graph.nodes.length} nodes / {graph.edges?.length ?? 0} edges</div>
        </div>
        <div className="text-xs text-[var(--text-secondary)]">{collapsed ? t('executionGraph.expand') : t('executionGraph.collapse')}</div>
      </button>

      {!collapsed ? (
        <div
          className="space-y-4 px-4 pb-4"
          onMouseDown={(e) => setDragStart({ x: e.clientX - offset.x, y: e.clientY - offset.y })}
          onMouseMove={(e) => {
            if (!dragStart) return
            setOffset({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y })
          }}
          onMouseUp={() => setDragStart(null)}
          onMouseLeave={() => setDragStart(null)}
        >
          <div className="flex flex-wrap gap-2 items-center">
            <button className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-2 py-1 text-xs text-[var(--text)]" onClick={() => setZoom((z) => Math.max(0.6, z - 0.1))}>{t('executionGraph.zoomOut')}</button>
            <button className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-2 py-1 text-xs text-[var(--text)]" onClick={() => setZoom((z) => Math.min(1.8, z + 0.1))}>{t('executionGraph.zoomIn')}</button>
            <button className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-2 py-1 text-xs text-[var(--text)]" onClick={() => { setZoom(1); setOffset({ x: 0, y: 0 }) }}>{t('executionGraph.reset')}</button>
            <select
              value={stageFilter}
              onChange={(e) => setStageFilter(e.target.value)}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-2 py-1 text-xs text-[var(--text)]"
            >
              <option value="ALL">全部阶段</option>
              <option value="REASON">REASON</option>
              <option value="DECIDE">DECIDE</option>
              <option value="EXECUTE">EXECUTE</option>
              <option value="OBSERVE">OBSERVE</option>
              <option value="REFLECT">REFLECT</option>
            </select>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg border border-white/15 bg-white/5 px-2 py-1 text-xs text-slate-100"
            >
              <option value="ALL">全部状态</option>
              <option value="SUCCESS">SUCCESS</option>
              <option value="RUNNING">RUNNING</option>
              <option value="FAILED">FAILED</option>
              <option value="PENDING">PENDING</option>
            </select>
          </div>
          <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            <button className="px-2 py-1 border border-[var(--border)] rounded" onClick={() => setZoom((z) => Math.max(0.5, z - 0.1))}>-</button>
            <span>{Math.round(zoom * 100)}%</span>
            <button className="px-2 py-1 border border-[var(--border)] rounded" onClick={() => setZoom((z) => Math.min(2, z + 0.1))}>+</button>
            <button className="px-2 py-1 border border-[var(--border)] rounded" onClick={() => { setOffset({ x: 0, y: 0 }); setZoom(1) }}>重置视图</button>
          </div>
          <div
            className="grid gap-3 cursor-grab"
            style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})`, transformOrigin: 'top left' }}
            onMouseDown={(e) => setDragStart({ x: e.clientX, y: e.clientY })}
            onMouseMove={(e) => {
              if (!dragStart) return
              const dx = e.clientX - dragStart.x
              const dy = e.clientY - dragStart.y
              setOffset((o) => ({ x: o.x + dx, y: o.y + dy }))
              setDragStart({ x: e.clientX, y: e.clientY })
            }}
            onMouseUp={() => setDragStart(null)}
            onMouseLeave={() => setDragStart(null)}
          >
            {filteredNodes.map((node, index) => {
              const accent = stageColors[node.stage] || 'from-slate-400/20 to-slate-400/5 border-white/10 text-slate-100'
              const summary = summarizeNode(node)
              return (
                <div key={node.id} className="flex gap-3">
                  <div className="flex w-8 flex-col items-center pt-1">
                    <div className="flex h-8 w-8 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[11px] text-[var(--text)]">
                      {index + 1}
                    </div>
                    {index < filteredNodes.length - 1 ? <div className="mt-2 h-full w-px bg-white/10" /> : null}
                  </div>
                  <div className={clsx('flex-1 rounded-2xl border bg-gradient-to-br px-4 py-3 transition-all duration-300', accent, node.status === 'RUNNING' && 'ring-2 ring-sky-400 shadow-lg shadow-sky-200/60 animate-pulse', highlightNodeId === node.id && 'ring-2 ring-amber-400 shadow-md shadow-amber-200/60')} onClick={() => setSelectedNode(node)}>
                    <div className="flex items-center gap-2">
                      <div className="text-[11px] uppercase tracking-[0.22em] opacity-80">{node.stage}</div>
                      <div className="text-[11px] opacity-60">{node.type}</div>
                      <div className={clsx('ml-auto rounded-full border px-2 py-0.5 text-[10px] tracking-[0.16em]', statusTone(node.status))}>
                        {node.status}
                      </div>
                    </div>
                    <div className="mt-2 text-sm leading-6 text-[var(--text)]">{summary || '无附加摘要'}</div>
                    <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-[var(--text)]">
                      <span className="rounded-full border border-[var(--border)] bg-[var(--bg-secondary)] px-2 py-1 text-[var(--text)]">id: {node.id}</span>
                      {node.metadata?.step_id ? (
                        <span className="rounded-full border border-[var(--border)] bg-[var(--bg-secondary)] px-2 py-1 text-[var(--text)]">step: {String(node.metadata.step_id)}</span>
                      ) : null}
                      <button
                        type="button"
                        className="rounded-full border border-[var(--border)] bg-[var(--bg-secondary)] px-2 py-1 text-[10px] text-[var(--text)]"
                        onClick={() => window.dispatchEvent(new CustomEvent('opentrace:graph-control', { detail: { action: 'prune', nodeId: node.id } }))}
                      >
                        剪枝
                      </button>
                      <button
                        type="button"
                        className="rounded-full border border-[var(--border)] bg-[var(--bg-secondary)] px-2 py-1 text-[10px] text-[var(--text)]"
                        onClick={() => window.dispatchEvent(new CustomEvent('opentrace:graph-control', { detail: { action: 'expand', nodeId: node.id } }))}
                      >
                        扩展
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
          {selectedNode ? (
            <div className="fixed right-4 top-20 z-40 w-[420px] max-h-[70vh] overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--surface)]/95 shadow-2xl backdrop-blur p-4">
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-sm font-semibold text-[var(--text)]">节点详情</h4>
                <button className="text-xs px-2 py-1 border border-[var(--border)] rounded text-[var(--text-secondary)]" onClick={() => setSelectedNode(null)}>关闭</button>
              </div>
              <div className="space-y-2 text-xs text-[var(--text-secondary)]">
                <div><span className="text-[var(--text-secondary)]">id:</span> {selectedNode.id}</div>
                <div><span className="text-[var(--text-secondary)]">stage:</span> {selectedNode.stage}</div>
                <div><span className="text-[var(--text-secondary)]">type:</span> {selectedNode.type}</div>
                <div><span className="text-[var(--text-secondary)]">status:</span> {selectedNode.status}</div>
                <div>
                  <div className="text-[var(--text-secondary)] mb-1">input</div>
                  <pre className="whitespace-pre-wrap rounded bg-[var(--bg-secondary)] p-2">{JSON.stringify(selectedNode.input ?? {}, null, 2)}</pre>
                </div>
                <div>
                  <div className="text-[var(--text-secondary)] mb-1">output</div>
                  <pre className="whitespace-pre-wrap rounded bg-[var(--bg-secondary)] p-2">{JSON.stringify(selectedNode.output ?? {}, null, 2)}</pre>
                </div>
                <div>
                  <div className="text-[var(--text-secondary)] mb-1">metadata</div>
                  <pre className="whitespace-pre-wrap rounded bg-[var(--bg-secondary)] p-2">{JSON.stringify(selectedNode.metadata ?? {}, null, 2)}</pre>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
