import React from 'react'
import type { ReasoningStep, ToolRunStatus } from '../api/client'
import clsx from 'clsx'
import { CardShell } from './CardShell'
import { DarkPillButton } from './ui/DarkPanel'

const stageIconMap: Record<ReasoningStep['stage'], string> = {
  ROUTE: '🚦',
  REASON: '🧠',
  DECIDE: '⚙️',
  EXECUTE: '🔧',
  OBSERVE: '👀',
  REFLECT: '🔁',
  PLAN: '🗺️',
  ACT: '▶️',
  DRAFT: '✍️',
  CRITIC: '🧪',
  REWRITE: '♻️',
  FINAL: '✅',
  FUSION: '🔄',
  EVIDENCE: '📋',
}

const toolIconMap: Record<string, string> = {
  search: '🔍',
  code: '💻',
  doc: '📄',
  sql: '🗄️',
  tool: '🧰',
  'agent:data': '🗄️',
  'agent:web': '🌐',
  'agent:tool': '🧰',
  'agent:memory': '🧠',
}

function readableToolName(tool: string): string {
  const normalized = tool.toLowerCase()
  const nameMap: Record<string, string> = {
    'agent:data': 'DataAgent（数据分析）',
    'agent:web': 'WebAgent（联网检索）',
    'agent:tool': 'ToolAgent（工具执行）',
    'agent:memory': 'MemoryAgent（记忆检索）',
  }
  return nameMap[normalized] || tool
}

function toolLabel(tool: string, status: ToolRunStatus | string) {
  const normalized = tool.toLowerCase()
  const verbMap: Record<string, string> = {
    search: '正在检索信息',
    sql: '正在调用 SQL 查询',
    doc: '正在读取文档',
    code: '正在执行代码',
    tool: '正在调用工具',
    'agent:data': 'DataAgent 正在执行',
    'agent:web': 'WebAgent 正在执行',
    'agent:tool': 'ToolAgent 正在执行',
    'agent:memory': 'MemoryAgent 正在执行',
  }

  if (status === 'success') return `${readableToolName(tool)} 执行完成`
  if (status === 'error') return `${readableToolName(tool)} 执行失败`
  if (status === 'timeout') return `${readableToolName(tool)} 执行超时`
  return verbMap[normalized] || `正在调用 ${readableToolName(tool)}`
}

export function ToolCallStatus({
  tool,
  status,
  preview,
}: {
  tool: string
  status: ToolRunStatus | string
  preview?: string
}) {
  const normalized = tool.toLowerCase()
  const icon = toolIconMap[normalized] || '🛠️'

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 shadow-[0_10px_30px_rgba(0,0,0,0.18)]">
      <div className="flex items-center gap-2 text-[13px] text-[var(--text)]">
        <span>{icon}</span>
        <span className="font-medium tracking-[0.01em]">{toolLabel(normalized, status)}...</span>
      </div>
      {preview ? <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{preview}</div> : null}
    </div>
  )
}

function ReasoningStepRow({ step }: { step: ReasoningStep }) {
  return (
    <div className="relative pl-5">
      <div className="absolute left-[7px] top-2 h-[calc(100%-4px)] w-px bg-[linear-gradient(180deg,rgba(110,231,255,0.42),rgba(110,231,255,0.05))]" />
      <div className="relative rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 shadow-[0_10px_30px_rgba(0,0,0,0.12)]">
        <div className="mb-2 flex items-center gap-2 text-[12px] uppercase tracking-[0.22em] text-[var(--text-secondary)]">
          <span className="text-sm">{stageIconMap[step.stage]}</span>
          <span>{step.stage}</span>
          <span
            className={clsx(
              'ml-auto rounded-full border border-[var(--border)] bg-[var(--bg-secondary)] px-2 py-0.5 text-[10px] tracking-[0.18em] text-[var(--text)]'
            )}
          >
            {step.status}
          </span>
        </div>

        <div className="text-[14px] leading-6 text-[var(--text)]">{step.content}</div>

        {step.tool ? (
          <div className="mt-3 space-y-2">
            <div className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-1 text-[12px] text-[var(--text)]">
              <span>🔧</span>
              <span>{readableToolName(step.tool.name)}</span>
            </div>
            <ToolCallStatus tool={step.tool.name} status={step.tool.status} preview={step.tool.preview} />
          </div>
        ) : null}
      </div>
    </div>
  )
}

export default function ReasoningChain({
  steps,
  autoExpand = false,
  collapseOnEvent,
}: {
  steps: ReasoningStep[]
  autoExpand?: boolean
  collapseOnEvent?: string
}) {
  const [collapsed, setCollapsed] = React.useState(true)
  const [stageFilter, setStageFilter] = React.useState<'ALL' | ReasoningStep['stage']>('ALL')
  const [onlyRunning, setOnlyRunning] = React.useState(false)

  React.useEffect(() => {
    if (autoExpand) setCollapsed(false)
  }, [autoExpand])

  React.useEffect(() => {
    if (!collapseOnEvent) return
    const onDone = () => setCollapsed(true)
    window.addEventListener(collapseOnEvent, onDone as EventListener)
    return () => window.removeEventListener(collapseOnEvent, onDone as EventListener)
  }, [collapseOnEvent])

  if (!steps.length) return null

  const filtered = steps.filter((s) => {
    if (stageFilter !== 'ALL' && s.stage !== stageFilter) return false
    if (onlyRunning && s.status !== 'running') return false
    return true
  })

  return (
    <CardShell
      eyebrow="REASONING"
      title="Reasoning Chain"
      meta={`推理链路 · ${filtered.length}/${steps.length} steps`}
      accent="from-cyan-400/60 via-sky-400/40 to-indigo-400/30"
      className="mb-4 overflow-hidden"
    >
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="flex w-full items-center justify-between rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-left"
      >
        <div className="text-xs text-[var(--text-secondary)]">点击切换展开 / 折叠</div>
        <div className="text-xs text-[var(--text-secondary)]">{collapsed ? '展开' : '折叠'}</div>
      </button>

      {!collapsed ? (
        <div className="mt-3">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <select
              value={stageFilter}
              onChange={(e) => setStageFilter(e.target.value as 'ALL' | ReasoningStep['stage'])}
              className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1 text-xs text-[var(--text)]"
            >
              <option value="ALL">全部阶段</option>
              <option value="REASON">REASON</option>
              <option value="DECIDE">DECIDE</option>
              <option value="EXECUTE">EXECUTE</option>
              <option value="OBSERVE">OBSERVE</option>
              <option value="REFLECT">REFLECT</option>
            </select>
            <button
              type="button"
              onClick={() => setOnlyRunning((v) => !v)}
              className={clsx(
                'rounded-full border px-3 py-1 text-xs',
                onlyRunning
                  ? 'border-[var(--accent)] bg-[var(--accent-dim)] text-[var(--accent)]'
                  : 'border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]'
              )}
            >
              仅看运行中
            </button>
          </div>
          <div className="space-y-3">
            {filtered.map((step) => (
              <ReasoningStepRow key={step.id} step={step} />
            ))}
          </div>
        </div>
      ) : null}
    </CardShell>
  )
}
