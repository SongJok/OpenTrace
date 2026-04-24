import { useEffect, useMemo, useRef, useState } from 'react'
import { Copy, RotateCcw, Quote, Pencil, GitBranch, ShieldCheck } from 'lucide-react'
import { Message, useChatStore, type ExecutionGraphData } from '../store/chat'
import { getTraceVisibility } from '../store/theme'
import { apiBranchConversation, apiGetMessages, apiPatchMessage, type ReasoningStep } from '../api/client'
import { useAuthStore } from '../store/auth'
import MarkdownMessage from './MarkdownMessage'
import ReasoningChain from './ReasoningChain'
import ExecutionGraphPanel from './ExecutionGraphPanel'
import DagTimeline, { type DagTimelineItem } from './DagTimeline'
import { CardShell } from './CardShell'
import { DarkPanel } from './ui/DarkPanel'
import { t } from '../i18n'

function parseEpistemicMeta(messageText: string): { level?: string; issues: string[] } {
  const match = messageText.match(/^([📊📄🔗🧠💡⚠️])\s+/)
  const emoji = match?.[1]
  const level = emoji === '📊'
    ? 'FACT'
    : emoji === '📄'
      ? 'DOCUMENT'
      : emoji === '🔗'
        ? 'SEARCH'
        : emoji === '🧠'
          ? 'MEMORY'
          : emoji === '💡'
            ? 'INFERENCE'
            : emoji === '⚠️'
              ? 'SPECULATION'
              : undefined

  const issues: string[] = []
  const issueSection = messageText.match(/epistemic_issues[:：]\s*([\s\S]{0,300})/i)
  if (issueSection?.[1]) {
    issues.push(issueSection[1].trim())
  }
  return { level, issues }
}

function levelBadge(level?: string) {
  if (!level) return null
  const cls = level === 'FACT'
    ? 'bg-emerald-100 text-emerald-700 border-emerald-200'
    : level === 'DOCUMENT'
      ? 'bg-sky-100 text-sky-700 border-sky-200'
      : level === 'SEARCH'
        ? 'bg-indigo-100 text-indigo-700 border-indigo-200'
        : level === 'INFERENCE'
          ? 'bg-amber-100 text-amber-700 border-amber-200'
          : 'bg-zinc-100 text-zinc-700 border-zinc-200'
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold ${cls}`}>{level}</span>
}

function tryParseToolCard(content: string): { type: 'time' | 'weather' | 'table'; data: any } | null {
  const candidates = [content.trim()]

  const fenceMatch = content.match(/```(?:json)?\s*([\s\S]*?)```/i)
  if (fenceMatch?.[1]) candidates.unshift(fenceMatch[1].trim())

  const objectMatch = content.match(/\{[\s\S]*\}/)
  if (objectMatch?.[0]) candidates.unshift(objectMatch[0].trim())

  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate)
      if (parsed && typeof parsed === 'object') {
        if (parsed.type === 'time' || parsed.time || parsed.timestamp || parsed.displayTime) return { type: 'time', data: parsed }
        if (parsed.city && (parsed.temperature !== undefined || parsed.weather)) return { type: 'weather', data: parsed }
        if (parsed.type === 'table' && Array.isArray(parsed.rows)) return { type: 'table', data: parsed }
      }
    } catch {
      // ignore non-json content
    }
  }

  const looseTimeMatch = content.match(/(?:current\s+time|\btime\b|当前时间|现在时间)[:：\s\-]*([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)/i)
  if (looseTimeMatch?.[1]) {
    return {
      type: 'time',
      data: {
        type: 'time',
        displayTime: looseTimeMatch[1],
        time: looseTimeMatch[1],
      },
    }
  }

  return null
}

function parseTimeFromData(data: any): Date | null {
  const candidates = [data?.timestamp, data?.iso, data?.dateTime, data?.datetime, data?.time].filter(Boolean)
  for (const candidate of candidates) {
    if (candidate instanceof Date && !Number.isNaN(candidate.getTime())) return candidate
    const parsed = new Date(String(candidate))
    if (!Number.isNaN(parsed.getTime())) return parsed
  }
  return null
}

function formatClockTime(date: Date | null, fallback: string) {
  if (!date) return fallback || '—'
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function formatTimeLabel(data: any, fallback: string) {
  return String(data?.displayTime || data?.formattedTime || data?.time || fallback || '')
}

function formatTimeLocation(data: any) {
  const pieces = [data?.location, data?.city, data?.timezoneLabel, data?.timezone].filter(Boolean)
  return pieces.length ? String(pieces[0]) : ''
}

function formatBeijingLabel(value: any) {
  const normalized = normalizeTimezoneLabel(value)
  if (!normalized) return ''
  return normalized === 'Beijing' ? 'Beijing' : normalized
}

function formatTimeSubtitle(data: any) {
  return String(data?.subtitle || data?.description || data?.detail || data?.summary || '')
}

function formatOffset(data: any) {
  const raw = data?.offset ?? data?.utcOffset ?? data?.timezoneOffset ?? data?.relativeOffset
  if (raw === undefined || raw === null || raw === '') return ''
  const text = String(raw)
  if (/^[+-]?\d+$/.test(text)) {
    const hours = Number(text)
    const sign = hours >= 0 ? '+' : ''
    return `UTC${sign}${hours}`
  }
  return text
}

function normalizeTimezoneLabel(value: any) {
  const text = String(value ?? '').trim()
  if (!text) return ''

  const normalized = text
    .replace(/^Asia\/Shanghai$/i, 'Beijing')
    .replace(/^Shanghai(?:,?\s*China)?$/i, 'Beijing')
    .replace(/^UTC\s*\+?8(?:[:：]00)?$/i, 'Beijing')

  return normalized
}

function formatCountLabel(label: string, value: any) {
  if (value === undefined || value === null || value === '') return null
  return `${label} ${value}`
}

export default function ChatMessage({ message }: { message: Message }) {
  const activeId = useChatStore((s) => s.activeId)
  const showReasoning = getTraceVisibility('reasoning')
  const showDag = getTraceVisibility('dag')
  const showExecutionGraph = getTraceVisibility('executionGraph')
  const showDecisionTrace = getTraceVisibility('decisionTrace')
  const showFlowCards = getTraceVisibility('flowCards')
  const messages = useChatStore((s) => (activeId ? s.messages[activeId] ?? [] : []))
  const steps = useChatStore((s) => {
    if (!activeId || message.role !== 'assistant') return message.reasoning_steps ?? []
    return s.getReasoningStepsForMessage(activeId, message.id)
  })
  const executionGraph = useChatStore((s) => {
    if (!activeId || message.role !== 'assistant') return message.execution_graph ?? null
    return s.getExecutionGraphForMessage(activeId, message.id) ?? message.execution_graph ?? null
  })

  const isLastAssistant = useMemo(() => {
    if (message.role !== 'assistant') return false
    const assistants = messages.filter((m) => m.role === 'assistant')
    return assistants.length > 0 && assistants[assistants.length - 1].id === message.id
  }, [messages, message.id, message.role])

  if (message.role === 'user') {
    return <UserMessage message={message} />
  }

  if (message.status === 'streaming') {
    return (
      <div>
        <ReasoningChain
          steps={steps}
          autoExpand
          collapseOnEvent={`opentrace:assistant-stream-done:${message.id}`}
        />
        <ExecutionGraphPanel
          graph={executionGraph}
          autoExpand
          collapseOnEvent={`opentrace:assistant-stream-done:${message.id}`}
        />
        <StreamingMessage text={message.streamText} />
      </div>
    )
  }

  return (
    <FinalMessage
      messageId={message.id}
      content={message.finalText}
      steps={steps}
      executionGraph={executionGraph}
      citations={message.citations}
      annotations={message.annotations}
      showRegenerate={isLastAssistant}
    />
  )
}

function UserMessage({ message }: { message: Message }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(message.finalText)

  const quote = () => {
    window.dispatchEvent(
      new CustomEvent('opentrace:prefill', {
        detail: { text: `> ${message.finalText}\n`, autoSend: false },
      })
    )
  }

  const copy = async () => {
    await navigator.clipboard.writeText(message.finalText)
  }

  const save = () => {
    const text = value.trim()
    if (!text || text === message.finalText) {
      setEditing(false)
      return
    }
    setEditing(false)
    window.dispatchEvent(
      new CustomEvent('opentrace:regen', {
        detail: {
          mode: 'edit-regenerate',
          messageId: message.id,
          newContent: text,
        },
      })
    )
  }

  return (
    <div className="max-w-[85%] rounded-3xl border border-[var(--border)] bg-[var(--surface)] px-5 py-3 text-[15px] leading-relaxed text-[var(--text)] shadow-[0_10px_30px_rgba(0,0,0,0.08)]">
      {editing ? (
        <div className="space-y-2">
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text)]"
            rows={3}
          />
          <div className="flex gap-2 justify-end text-xs">
            <button onClick={() => setEditing(false)} className="rounded px-2 py-1 bg-[var(--bg-secondary)] text-[var(--text-secondary)]">
              取消
            </button>
            <button onClick={save} className="rounded px-2 py-1 bg-[var(--accent)] text-white">
              保存并重生成
            </button>
          </div>
        </div>
      ) : (
        <>
          <div>{message.finalText}</div>
          <div className="mt-2 flex items-center gap-2 opacity-80">
            <button onClick={copy} className="p-1 hover:opacity-100" title="复制">
              <Copy size={14} />
            </button>
            <button onClick={quote} className="p-1 hover:opacity-100" title="引用到输入框">
              <Quote size={14} />
            </button>
            <button onClick={() => setEditing(true)} className="p-1 hover:opacity-100" title="编辑并重生成">
              <Pencil size={14} />
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function DecisionTraceCard({ executionGraph, annotations }: { executionGraph: ExecutionGraphData | null; annotations?: Array<any> }) {
  const [expanded, setExpanded] = useState(false)
  const state = (executionGraph?.state || {}) as any
  const taskModel = state?.task_model || {}
  const confirmedFacts = Number(taskModel?.confirmed_facts_count || 0)
  const hypotheses = Number(taskModel?.hypotheses_count || 0)
  const replan = Boolean(taskModel?.replan_triggered)
  const avgConfidence = (() => {
    const arr = (annotations || [])
      .map((a: any) => Number(a?.annotation?.confidence))
      .filter((v: number) => Number.isFinite(v))
    if (!arr.length) return null
    return Math.round((arr.reduce((x: number, y: number) => x + y, 0) / arr.length) * 100)
  })()
  const sourceRatio = (() => {
    const arr = (annotations || []).map((a: any) => String(a?.annotation?.source_type || '')).filter(Boolean)
    if (!arr.length) return { db: 0, doc: 0, web: 0 }
    const total = arr.length
    const db = arr.filter((x: string) => x === 'database').length
    const doc = arr.filter((x: string) => x === 'document').length
    const web = arr.filter((x: string) => x === 'web_search').length
    return {
      db: Math.round((db / total) * 100),
      doc: Math.round((doc / total) * 100),
      web: Math.round((web / total) * 100),
    }
  })()
  const topCitations = (annotations || [])
    .flatMap((a: any) => a?.annotation?.citations || [])
    .slice(0, 5)

  return (
    <CardShell
      eyebrow="TRACE"
      title="决策追溯"
      meta="系统依据、证据与重规划状态"
      accent="from-slate-400/60 via-zinc-300/40 to-stone-200/30"
      className="mb-3 overflow-hidden"
    >
      <div className="grid grid-cols-2 gap-2 text-xs text-[var(--text-secondary)] md:grid-cols-3">
        <div className="rounded-2xl bg-[var(--bg-secondary)] px-3 py-2"><span className="text-[var(--text-secondary)]">已确认事实</span><div className="mt-1 text-sm text-[var(--text)]">{confirmedFacts}</div></div>
        <div className="rounded-2xl bg-[var(--bg-secondary)] px-3 py-2"><span className="text-[var(--text-secondary)]">假设数量</span><div className="mt-1 text-sm text-[var(--text)]">{hypotheses}</div></div>
        <div className="rounded-2xl bg-[var(--bg-secondary)] px-3 py-2"><span className="text-[var(--text-secondary)]">重规划</span><div className="mt-1 text-sm text-[var(--text)]">{replan ? '是' : '否'}</div></div>
        <div className="rounded-2xl bg-[var(--bg-secondary)] px-3 py-2"><span className="text-[var(--text-secondary)]">综合置信度</span><div className="mt-1 text-sm text-[var(--text)]">{avgConfidence !== null ? `${avgConfidence}%` : '—'}</div></div>
        <div className="rounded-2xl bg-[var(--bg-secondary)] px-3 py-2"><span className="text-[var(--text-secondary)]">DB 证据</span><div className="mt-1 text-sm text-[var(--text)]">{sourceRatio.db}%</div></div>
        <div className="rounded-2xl bg-[var(--bg-secondary)] px-3 py-2"><span className="text-[var(--text-secondary)]">Doc / Web</span><div className="mt-1 text-sm text-[var(--text)]">{sourceRatio.doc}% / {sourceRatio.web}%</div></div>
      </div>
      {topCitations.length > 0 ? (
        <div className="mt-4">
          <button
            type="button"
            className="text-xs text-[var(--text-secondary)] underline decoration-[var(--border)] underline-offset-2 hover:text-[var(--text)]"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? '收起证据明细' : '展开证据明细'}
          </button>
          {expanded ? (
            <div className="mt-2 space-y-2 text-xs text-white/78">
              {topCitations.map((c: any, idx: number) => (
                <div key={`${c.id || idx}`} className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">
                  <div className="font-medium text-white">{idx + 1}. {c.source_name || '来源'}</div>
                  {c.snippet ? <div className="mt-1 text-white/58">{String(c.snippet).slice(0, 120)}</div> : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </CardShell>
  )
}

function StreamingMessage({ text }: { text: string }) {
  return (
    <pre className="m-0 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 font-mono text-[15px] leading-relaxed whitespace-pre-wrap break-words text-[var(--text)]">
      {text}
    </pre>
  )
}

function TimeCard({ data }: { data: any }) {
  const parsedDate = parseTimeFromData(data)
  const [now, setNow] = useState(() => parsedDate ?? new Date())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const currentDate = now
  const timeText = formatClockTime(currentDate, '—')
  const dateText = currentDate.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).replaceAll('/', '-')
  const timezoneText = formatBeijingLabel(data?.timezoneLabel || data?.timezone || data?.location || data?.city)
  const subtitle = formatTimeSubtitle(data)
  const offset = formatOffset(data)
  const hour = currentDate.getHours() % 12
  const minute = currentDate.getMinutes()
  const second = currentDate.getSeconds()
  const hourAngle = hour * 30 + minute * 0.5 + second * (0.5 / 60)
  const minuteAngle = minute * 6 + second * 0.1
  const secondAngle = second * 6

  return (
    <DarkPanel accent="from-zinc-200/80 via-zinc-100/60 to-transparent" className="overflow-hidden rounded-[28px]">
      <div className="bg-[var(--time-card-bg,var(--surface))] px-6 py-5 text-[var(--time-card-text,var(--text))] md:px-7 md:py-6">
        <div className="grid items-center gap-5 md:grid-cols-[minmax(0,1fr)_160px]">
          <div className="min-w-0">
            <div className="inline-flex items-center rounded-full border px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.22em]" style={{ borderColor: 'var(--time-card-border, var(--border))', color: 'var(--time-card-faint, var(--text-secondary))' }}>
              现在
            </div>
            <div className="mt-2 text-[46px] font-semibold leading-none tracking-[-0.075em] md:text-[52px]" style={{ color: 'var(--time-card-text, var(--text))' }}>
              {timeText}
            </div>
            <div className="mt-2 flex items-center gap-2 text-[12px]" style={{ color: 'var(--time-card-muted, var(--text-secondary))' }}>
              {timezoneText ? <span>{timezoneText}</span> : null}
              <span style={{ color: 'var(--time-card-faint, var(--text-secondary))' }}>{dateText}</span>
            </div>
          </div>
          <div className="flex items-center justify-end">
            <div className="relative h-[138px] w-[138px] rounded-full bg-transparent">
              {[...Array(12)].map((_, idx) => {
                const angle = (idx * 30 - 60) * (Math.PI / 180)
                const x = 50 + 40 * Math.cos(angle)
                const y = 50 + 40 * Math.sin(angle)
                const mark = idx === 0 ? 12 : idx
                return (
                  <span
                    key={mark}
                    className="absolute -translate-x-1/2 -translate-y-1/2 text-[10px] font-medium"
                    style={{ left: `${x}%`, top: `${y}%`, color: 'var(--time-card-text,var(--text))' }}
                  >
                    {mark}
                  </span>
                )
              })}
              <div className="absolute left-1/2 top-1/2 h-[2px] w-[42px] origin-left rounded-full" style={{ backgroundColor: 'var(--time-card-text,var(--text))', transform: `translateY(-50%) rotate(${hourAngle - 90}deg)` }} />
              <div className="absolute left-1/2 top-1/2 h-[2px] w-[52px] origin-left rounded-full" style={{ backgroundColor: 'var(--time-card-text,var(--text))', transform: `translateY(-50%) rotate(${minuteAngle - 90}deg)` }} />
              <div className="absolute left-1/2 top-1/2 h-[1px] w-[54px] origin-left rounded-full" style={{ backgroundColor: 'var(--time-card-accent,var(--accent))', transform: `translateY(-50%) rotate(${secondAngle - 90}deg)` }} />
              <div className="absolute left-1/2 top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ backgroundColor: 'var(--time-card-accent,var(--accent))' }} />
            </div>
          </div>
        </div>
      </div>
    </DarkPanel>
  )
}

function FinalMessage({
  messageId,
  content,
  steps,
  executionGraph,
  citations,
  annotations,
  showRegenerate,
}: {
  messageId: string
  content: string
  steps: ReasoningStep[]
  executionGraph: ExecutionGraphData | null
  citations?: Array<{ id: number; title: string; url: string; snippet?: string }>
  annotations?: Array<{ id: string; text: string; annotation?: { level: string; source_type: string; confidence: number; caveats?: string[]; citations?: Array<{ id: string; source_name: string; snippet?: string; url?: string }> } | null }>
  showRegenerate: boolean
}) {
  const showReasoning = getTraceVisibility('reasoning')
  const showDag = getTraceVisibility('dag')
  const showExecutionGraph = getTraceVisibility('executionGraph')
  const showDecisionTrace = getTraceVisibility('decisionTrace')
  const showFlowCards = getTraceVisibility('flowCards')
  const token = useAuthStore((s) => s.token)!
  const activeId = useChatStore((s) => s.activeId)
  const setMessages = useChatStore((s) => s.setMessages)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(content)

  const copy = async () => {
    await navigator.clipboard.writeText(content)
  }

  const quote = () => {
    window.dispatchEvent(
      new CustomEvent('opentrace:prefill', {
        detail: { text: `> ${content}\n`, autoSend: false },
      })
    )
  }

  const regenerate = () => {
    window.dispatchEvent(
      new CustomEvent('opentrace:regen', {
        detail: { mode: 'regenerate' },
      })
    )
  }

  const saveAssistantEdit = async () => {
    if (!activeId) return
    const text = value.trim()
    if (!text || text === content) {
      setEditing(false)
      return
    }
    await apiPatchMessage(token, messageId, text)
    const msgs = await apiGetMessages(token, activeId)
    setMessages(activeId, msgs)
    setEditing(false)
  }

  const branchHere = async () => {
    if (!activeId) return
    const result = await apiBranchConversation(token, activeId, messageId)
    window.dispatchEvent(
      new CustomEvent('opentrace:switch-conversation', {
        detail: { conversationId: result.conversation_id },
      })
    )
  }

  const streamingDoneEvent = typeof window !== 'undefined' ? `opentrace:assistant-stream-done:${messageId}` : ''
  const toolCard = tryParseToolCard(content)

  const dagTimeline = useMemo<DagTimelineItem[]>(() => {
    const nodes = Array.isArray(executionGraph?.nodes) ? executionGraph.nodes : []
    return nodes
      .filter((n) => String(n.type) === 'agent_call')
      .map((n) => ({
        node_id: n.id,
        agent_type: String((n.metadata as any)?.agent_type || 'agent'),
        status: String(n.status || 'SUCCESS'),
        preview: String((n.output as any)?.preview || (n.metadata as any)?.query || ''),
        depends_on: Array.isArray((n.metadata as any)?.depends_on) ? (n.metadata as any).depends_on : undefined,
      }))
  }, [executionGraph])

  return (
    <div>
      {showReasoning ? <ReasoningChain steps={steps} collapseOnEvent={streamingDoneEvent} /> : null}
      {showDag ? <DagTimeline items={dagTimeline} /> : null}
      {showExecutionGraph ? <ExecutionGraphPanel graph={executionGraph} collapseOnEvent={streamingDoneEvent} /> : null}
      {showDecisionTrace ? <DecisionTraceCard executionGraph={executionGraph} annotations={annotations} /> : null}
      {showFlowCards ? (
        <div className="space-y-2">
          {toolCard?.type === 'time' ? <TimeCard data={toolCard.data} /> : null}
          {toolCard?.type === 'weather' ? (
            <CardShell
              eyebrow="WEATHER"
              title={String(toolCard.data.city || '天气')}
              meta={formatCountLabel('温度', `${toolCard.data.temperature ?? '-'}°C`) || undefined}
              accent="from-sky-500/70 via-cyan-400/45 to-emerald-300/35"
            >
              <div className="grid grid-cols-3 gap-3 text-sm">
                <div className="rounded-2xl bg-white/6 px-3 py-2">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-white/42">天气</div>
                  <div className="mt-1 text-white/88">{toolCard.data.weather || '-'}</div>
                </div>
                <div className="rounded-2xl bg-white/6 px-3 py-2">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-white/42">湿度</div>
                  <div className="mt-1 text-white/88">{toolCard.data.humidity ?? '-'}%</div>
                </div>
                <div className="rounded-2xl bg-white/6 px-3 py-2">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-white/42">风速</div>
                  <div className="mt-1 text-white/88">{toolCard.data.windSpeed ?? toolCard.data.wind_speed ?? '-'}{toolCard.data.windSpeed || toolCard.data.wind_speed ? ' m/s' : ''}</div>
                </div>
              </div>
            </CardShell>
          ) : null}
          {toolCard?.type === 'table' ? (
            <CardShell
              eyebrow="DATA"
              title={toolCard.data.title || 'SQL 查询结果'}
              meta={toolCard.data.summary || undefined}
              accent="from-violet-500/65 via-fuchsia-400/40 to-rose-300/35"
            >
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-white/50">
                <div>{typeof toolCard.data.rowCount === 'number' ? `${toolCard.data.rowCount} 行` : '结果表'}</div>
                <div>{typeof toolCard.data.tableCount === 'number' ? `${toolCard.data.tableCount} 表` : ''}</div>
              </div>
              <div className="mt-3 overflow-x-auto rounded-2xl border border-white/10 bg-black/20">
                <table className="min-w-full text-xs">
                  <thead className="sticky top-0 bg-white/8 text-white/70 backdrop-blur">
                    <tr>
                      {(toolCard.data.columns || []).map((col: string) => (
                        <th key={col} className="px-3 py-2 text-left font-medium whitespace-nowrap">{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(toolCard.data.rows || []).slice(0, 20).map((row: Record<string, any>, idx: number) => (
                      <tr key={idx} className="border-t border-white/8 odd:bg-white/[0.03] even:bg-white/[0.015]">
                        {(toolCard.data.columns || []).map((col: string) => (
                          <td key={col} className="px-3 py-2 align-top text-white/85 whitespace-pre-wrap break-words">{String(row?.[col] ?? '')}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardShell>
          ) : null}
        </div>
      ) : null}
      {editing ? (
        <div className="space-y-2 my-2">
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm"
            rows={5}
          />
          <div className="flex gap-2 text-xs">
            <button onClick={() => setEditing(false)} className="px-2 py-1 rounded border border-[var(--border)]">取消</button>
            <button onClick={() => void saveAssistantEdit()} className="px-2 py-1 rounded bg-[var(--accent)] text-white">保存答案</button>
          </div>
        </div>
      ) : toolCard?.type === 'time' ? (
        <TimeCard data={toolCard.data} />
      ) : toolCard?.type === 'weather' ? (
        <CardShell
          eyebrow="WEATHER"
          title={String(toolCard.data.city || '天气')}
          meta={formatCountLabel('温度', `${toolCard.data.temperature ?? '-'}°C`) || undefined}
          accent="from-sky-500/70 via-cyan-400/45 to-emerald-300/35"
        >
          <div className="grid grid-cols-3 gap-3 text-sm">
            <div className="rounded-2xl bg-white/6 px-3 py-2">
              <div className="text-[11px] uppercase tracking-[0.18em] text-white/42">天气</div>
              <div className="mt-1 text-white/88">{toolCard.data.weather || '-'}</div>
            </div>
            <div className="rounded-2xl bg-white/6 px-3 py-2">
              <div className="text-[11px] uppercase tracking-[0.18em] text-white/42">湿度</div>
              <div className="mt-1 text-white/88">{toolCard.data.humidity ?? '-'}%</div>
            </div>
            <div className="rounded-2xl bg-white/6 px-3 py-2">
              <div className="text-[11px] uppercase tracking-[0.18em] text-white/42">风速</div>
              <div className="mt-1 text-white/88">{toolCard.data.windSpeed ?? toolCard.data.wind_speed ?? '-'}{toolCard.data.windSpeed || toolCard.data.wind_speed ? ' m/s' : ''}</div>
            </div>
          </div>
        </CardShell>
      ) : toolCard?.type === 'table' ? (
        <CardShell
          eyebrow="DATA"
          title={toolCard.data.title || 'SQL 查询结果'}
          meta={toolCard.data.summary || undefined}
          accent="from-violet-500/65 via-fuchsia-400/40 to-rose-300/35"
        >
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-white/50">
            <div>{typeof toolCard.data.rowCount === 'number' ? `${toolCard.data.rowCount} 行` : '结果表'}</div>
            <div>{typeof toolCard.data.tableCount === 'number' ? `${toolCard.data.tableCount} 表` : ''}</div>
          </div>
          <div className="mt-3 overflow-x-auto rounded-2xl border border-white/10 bg-black/20">
            <table className="min-w-full text-xs">
              <thead className="sticky top-0 bg-white/8 text-white/70 backdrop-blur">
                <tr>
                  {(toolCard.data.columns || []).map((col: string) => (
                    <th key={col} className="px-3 py-2 text-left font-medium whitespace-nowrap">{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(toolCard.data.rows || []).slice(0, 20).map((row: Record<string, any>, idx: number) => (
                  <tr key={idx} className="border-t border-white/8 odd:bg-white/[0.03] even:bg-white/[0.015]">
                    {(toolCard.data.columns || []).map((col: string) => (
                      <td key={col} className="px-3 py-2 align-top text-white/85 whitespace-pre-wrap break-words">{String(row?.[col] ?? '')}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              className="rounded-full border border-white/12 bg-white/6 px-3 py-1 text-xs text-white/88 hover:bg-white/10"
              onClick={() => navigator.clipboard.writeText(String(toolCard.data.sql || ''))}
            >
              复制 SQL
            </button>
            <button
              type="button"
              className="rounded-full border border-white/12 bg-white/6 px-3 py-1 text-xs text-white/88 hover:bg-white/10"
              onClick={() => {
                const csv = [toolCard.data.columns || [], ...(toolCard.data.rows || []).map((row: Record<string, any>) => (toolCard.data.columns || []).map((col: string) => JSON.stringify(row?.[col] ?? '')))].map((r: any[]) => r.join(',')).join('\n')
                void navigator.clipboard.writeText(csv)
              }}
            >
              复制 CSV
            </button>
            <button
              type="button"
              className="rounded-full border border-white/12 bg-white/6 px-3 py-1 text-xs text-white/88 hover:bg-white/10"
              onClick={() =>
                window.dispatchEvent(
                  new CustomEvent('opentrace:prefill', {
                    detail: {
                      text: `请基于以下表格数据生成图表并解释：\n${JSON.stringify((toolCard.data.rows || []).slice(0, 20), null, 2)}`,
                      autoSend: false,
                    },
                  })
                )
              }
            >
              生成图表
            </button>
          </div>
          {toolCard.data.sql ? (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs text-white/52">查看 SQL</summary>
              <pre className="mt-2 whitespace-pre-wrap rounded-2xl bg-black/35 px-3 py-2 text-xs text-white/82">{toolCard.data.sql}</pre>
            </details>
          ) : null}
        </CardShell>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            {levelBadge(annotations?.[0]?.annotation?.level || parseEpistemicMeta(content).level)}
            {annotations?.[0]?.annotation?.confidence !== undefined ? (
              <span className="text-[10px] text-[var(--text-secondary)]">置信度 {Math.round((annotations[0].annotation!.confidence || 0) * 100)}%</span>
            ) : null}
          </div>
          <MarkdownMessage content={content} />
          {(annotations?.[0]?.annotation?.caveats?.length || 0) > 0 ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {(annotations?.[0]?.annotation?.caveats || []).join('\n')}
            </div>
          ) : parseEpistemicMeta(content).issues.length > 0 ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {parseEpistemicMeta(content).issues.join('\n')}
            </div>
          ) : null}
        </div>
      )}

      {Array.isArray(citations) && citations.length > 0 ? (
        <div className="mt-3 rounded-xl border border-[#e5e7eb] bg-[#f7f7f8] px-4 py-3">
          <div className="text-xs uppercase tracking-[0.2em] text-[#6b7280]">Sources</div>
          <div className="mt-2 space-y-2 text-sm text-[#111827]">
            {citations.map((c) => (
              <div key={c.id} className="flex flex-col gap-1">
                <a href={c.url || '#'} target="_blank" rel="noreferrer" className="text-[#111827] underline">
                  {c.id}. {c.title || c.url || 'Source'}
                </a>
                {c.snippet ? <div className="text-xs text-[#6b7280]">{c.snippet}</div> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-2 flex items-center gap-2 text-[var(--text-secondary)]">
        <button onClick={copy} className="p-1 hover:text-[var(--text)]" title={t('chat.copy')}>
          <Copy size={14} />
        </button>
        <button onClick={quote} className="p-1 hover:text-[var(--text)]" title={t('chat.quote')}>
          <Quote size={14} />
        </button>
        <button onClick={() => setEditing((v) => !v)} className="p-1 hover:text-[var(--text)]" title={t('chat.editAnswer')}>
          <Pencil size={14} />
        </button>
        <button onClick={() => void branchHere()} className="p-1 hover:text-[var(--text)]" title={t('chat.branch')}>
          <GitBranch size={14} />
        </button>
        {showRegenerate ? (
          <button onClick={regenerate} className="p-1 hover:text-[var(--text)]" title={t('chat.regenerate')}>
            <RotateCcw size={14} />
          </button>
        ) : null}
      </div>
    </div>
  )
}
