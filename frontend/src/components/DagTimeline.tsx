import React from 'react'
import clsx from 'clsx'
import { CardShell } from './CardShell'

export type DagTimelineItem = {
  node_id: string
  agent_type: string
  status: string
  preview?: string
  depends_on?: string[]
  duration_ms?: number
}

function statusClass(status: string) {
  const s = String(status || '').toUpperCase()
  if (s === 'RUNNING') return 'border-cyan-300/20 bg-cyan-300/10 text-cyan-100'
  if (s === 'SUCCESS') return 'border-emerald-300/20 bg-emerald-300/10 text-emerald-100'
  if (s === 'FAILED' || s === 'ERROR' || s === 'TIMEOUT') return 'border-rose-300/20 bg-rose-300/10 text-rose-100'
  return 'border-white/10 bg-white/5 text-white/62'
}

export default function DagTimeline({ items, title = 'DAG 流程' }: { items: DagTimelineItem[]; title?: string }) {
  const [expanded, setExpanded] = React.useState(true)
  const [activeNodeId, setActiveNodeId] = React.useState<string | null>(null)
  if (!items.length) return null

  React.useEffect(() => {
    const onSelect = (ev: Event) => {
      const ce = ev as CustomEvent<{ nodeId?: string }>
      const nodeId = ce.detail?.nodeId
      if (nodeId) setActiveNodeId(nodeId)
    }
    window.addEventListener('opentrace:select-dag-node', onSelect as EventListener)
    return () => window.removeEventListener('opentrace:select-dag-node', onSelect as EventListener)
  }, [])

  return (
    <CardShell
      eyebrow="DAG"
      title={title}
      meta={`${items.length} 个节点`}
      accent="from-violet-400/60 via-fuchsia-400/40 to-rose-400/30"
      className="mb-3 overflow-hidden"
    >
      <button type="button" onClick={() => setExpanded((v) => !v)} className="flex w-full items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-left">
        <div className="text-xs text-white/45">点击切换展开 / 折叠</div>
        <div className="text-xs text-white/52">{expanded ? '收起' : '展开'}</div>
      </button>
      {expanded ? (
        <div className="mt-3 space-y-2">
          {items.map((item, idx) => (
            <div
              key={item.node_id}
              className={clsx(
                'rounded-2xl border px-3 py-2 shadow-[0_10px_30px_rgba(0,0,0,0.12)] transition-all',
                activeNodeId === item.node_id ? 'border-cyan-300/20 bg-cyan-300/10 ring-1 ring-cyan-300/15' : 'border-white/10 bg-white/5'
              )}
              onClick={() => window.dispatchEvent(new CustomEvent('opentrace:select-dag-node', { detail: { nodeId: item.node_id } }))}
            >
              <div className="flex items-center gap-2 text-xs text-white/72">
                <span className="rounded-full bg-white/8 px-2 py-0.5 text-white/84">{idx + 1}</span>
                <span className="font-medium">{item.agent_type}</span>
                <span className={clsx('rounded-full border px-2 py-0.5 text-[10px] tracking-[0.16em]', statusClass(item.status))}>{item.status}</span>
              </div>
              <div className="mt-1 text-sm text-white/88">{item.preview || '执行中...'}</div>
              <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-white/52">
                {typeof item.duration_ms === 'number' ? <span>耗时：{item.duration_ms} ms</span> : null}
                {Array.isArray(item.depends_on) && item.depends_on.length > 0 ? <span>依赖：{item.depends_on.join(', ')}</span> : null}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </CardShell>
  )
}
