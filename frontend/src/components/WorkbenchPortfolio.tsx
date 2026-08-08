import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  CircleAlert,
  FolderKanban,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  Workflow,
} from 'lucide-react'
import type {
  WorkbenchPortfolio as WorkbenchPortfolioData,
  WorkbenchPortfolioItem,
  WorkbenchPortfolioStatus,
} from '../api/client'
import { useChatPreferences } from '../store/chatPreferences'

const statusLabels: Record<WorkbenchPortfolioStatus, string> = {
  critical: '存在阻塞',
  attention: '需要关注',
  active: '推进中',
  ready: '可开始',
  foundation: '待完善',
}

const statusTone: Record<WorkbenchPortfolioStatus, string> = {
  critical: 'border-red-500/30 bg-red-500/10 text-red-500',
  attention: 'border-amber-500/30 bg-amber-500/10 text-amber-500',
  active: 'border-blue-500/30 bg-blue-500/10 text-blue-500',
  ready: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-500',
  foundation: 'border-[var(--border)] bg-[var(--surface-raised)] text-[var(--text-secondary)]',
}

const filterOptions: Array<{ id: 'all' | WorkbenchPortfolioStatus; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'critical', label: '存在阻塞' },
  { id: 'attention', label: '需要关注' },
  { id: 'active', label: '推进中' },
  { id: 'ready', label: '可开始' },
  { id: 'foundation', label: '待完善' },
]

function formatTime(value?: string | null) {
  if (!value) return '暂无活动'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

function StatusIcon({ status }: { status: WorkbenchPortfolioStatus }) {
  if (status === 'critical') return <AlertTriangle size={15} />
  if (status === 'attention') return <CircleAlert size={15} />
  if (status === 'active') return <Workflow size={15} />
  if (status === 'ready') return <CheckCircle2 size={15} />
  return <FolderKanban size={15} />
}

function useOpenPortfolioItem() {
  const navigate = useNavigate()
  const setProjectId = useChatPreferences((state) => state.setProjectId)
  return (item: WorkbenchPortfolioItem) => {
    if (item.project_id && item.next_action.route.startsWith('/chat')) {
      setProjectId(item.project_id)
    }
    navigate(item.next_action.route)
  }
}

export function WorkbenchPortfolioSnapshot({ portfolio }: { portfolio: WorkbenchPortfolioData }) {
  const navigate = useNavigate()
  const openItem = useOpenPortfolioItem()
  const priorityItems = portfolio.items
    .filter((item) => ['critical', 'attention', 'active'].includes(item.status))
    .slice(0, 3)

  return (
    <section aria-label="工作组合快照" className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2"><FolderKanban size={17} className="text-[var(--accent)]" /><h2 className="font-medium">Project 工作组合</h2></div>
          <p className="mt-1 text-xs leading-5 text-[var(--text-secondary)]">
            {portfolio.summary.critical_projects
              ? `${portfolio.summary.critical_projects} 个 Project 存在阻塞，需要先处理风险或失败。`
              : portfolio.summary.attention_projects
                ? `${portfolio.summary.attention_projects} 个 Project 等待审批、确认或恢复。`
                : `${portfolio.summary.active_work} 项工作正在稳定推进。`}
          </p>
        </div>
        <button type="button" onClick={() => navigate('/work?tab=portfolio')} className="inline-flex items-center gap-1 text-xs font-medium text-[var(--accent)]">
          查看完整组合<ArrowRight size={13} />
        </button>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {priorityItems.map((item) => (
          <button key={item.project_id || 'unassigned'} type="button" onClick={() => openItem(item)} className="group rounded-xl border border-[var(--border)] bg-[var(--bg)] p-4 text-left hover:border-[var(--accent)]/40">
            <div className="flex items-start justify-between gap-2">
              <span className="min-w-0 truncate text-sm font-medium">{item.name}</span>
              <span className={`inline-flex flex-none items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${statusTone[item.status]}`}><StatusIcon status={item.status} />{statusLabels[item.status]}</span>
            </div>
            <p className="mt-2 line-clamp-2 text-xs leading-5 text-[var(--text-secondary)]">{item.status_reason}</p>
            <div className="mt-3 flex items-center justify-between text-xs font-medium text-[var(--accent)]"><span>{item.next_action.label}</span><ArrowRight size={12} className="transition-transform group-hover:translate-x-0.5" /></div>
          </button>
        ))}
        {priorityItems.length === 0 && (
          <div className="col-span-full rounded-xl border border-dashed border-[var(--border)] p-6 text-center">
            <CheckCircle2 size={22} className="mx-auto text-emerald-500" />
            <p className="mt-2 text-sm font-medium">当前工作组合没有阻塞</p>
            <p className="mt-1 text-xs text-[var(--text-secondary)]">可从已就绪 Project 开始新的企业工作。</p>
          </div>
        )}
      </div>
    </section>
  )
}

export function WorkbenchPortfolio({ portfolio }: { portfolio: WorkbenchPortfolioData }) {
  const openItem = useOpenPortfolioItem()
  const [filter, setFilter] = useState<'all' | WorkbenchPortfolioStatus>('all')
  const [query, setQuery] = useState('')
  const visibleItems = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase()
    return portfolio.items.filter((item) => {
      if (filter !== 'all' && item.status !== filter) return false
      if (!keyword) return true
      return `${item.name} ${item.description} ${item.status_reason} ${item.next_action.title}`
        .toLocaleLowerCase()
        .includes(keyword)
    })
  }, [filter, portfolio.items, query])

  return (
    <div className="space-y-6">
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <PortfolioMetric icon={Workflow} label="当前工作单元" value={portfolio.summary.active_work} detail={`${portfolio.summary.active_projects} 个 Project 稳定推进`} tone="text-[var(--accent)]" />
        <PortfolioMetric icon={AlertTriangle} label="阻塞 Project" value={portfolio.summary.critical_projects} detail="失败执行或关键预警" tone="text-red-500" />
        <PortfolioMetric icon={ShieldCheck} label="待人工确认" value={portfolio.summary.pending_approvals + portfolio.summary.unacknowledged_alerts} detail={`${portfolio.summary.pending_approvals} 审批 · ${portfolio.summary.unacknowledged_alerts} 预警`} tone="text-amber-500" />
        <PortfolioMetric icon={CheckCircle2} label={`${portfolio.window_days} 日交付轮次`} value={`${portfolio.response_candidates_truncated ? '≥' : ''}${portfolio.summary.delivered_turns_7d}`} detail="已完成的持久 Response" tone="text-emerald-500" />
      </section>

      {portfolio.response_candidates_truncated && <div role="status" className="rounded-2xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs leading-5 text-amber-600">当前工作组合已达到 {portfolio.response_candidate_limit} 条 Response 候选上限；界面用“≥”标记交付量，避免把有界投影误解为完整历史统计。</div>}

      <section className="overflow-hidden rounded-3xl border border-[var(--border)] bg-[var(--surface)]">
        <div className="border-b border-[var(--border)] p-4 sm:p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="flex items-center gap-2"><FolderKanban size={18} className="text-[var(--accent)]" /><h2 className="font-medium">Project 工作组合驾驶舱</h2></div>
              <p className="mt-1 max-w-3xl text-xs leading-5 text-[var(--text-secondary)]">按 Project 合并 Responses、Goals、审批、预警与自动化；状态只来自持久事实，下一步始终返回可处理入口。</p>
            </div>
            <label className="relative min-w-0 lg:w-72">
              <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 Project 或下一步" aria-label="搜索工作组合" className="h-9 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] pl-9 pr-3 text-xs outline-none focus:border-[var(--accent)]" />
            </label>
          </div>
          <div className="mt-4 flex gap-1 overflow-x-auto pb-1" role="tablist" aria-label="工作组合状态">
            {filterOptions.map((option) => {
              const count = option.id === 'all' ? portfolio.items.length : portfolio.items.filter((item) => item.status === option.id).length
              return (
                <button key={option.id} type="button" role="tab" aria-selected={filter === option.id} onClick={() => setFilter(option.id)} className={`flex-none rounded-lg px-3 py-1.5 text-xs ${filter === option.id ? 'bg-[var(--accent-dim)] font-medium text-[var(--accent)]' : 'text-[var(--text-secondary)] hover:bg-[var(--surface-raised)]'}`}>
                  {option.label} {count}
                </button>
              )
            })}
          </div>
        </div>

        <div className="grid gap-4 p-4 lg:grid-cols-2 lg:p-5">
          {visibleItems.map((item) => (
            <article key={item.project_id || 'unassigned'} className="flex min-h-72 flex-col rounded-2xl border border-[var(--border)] bg-[var(--bg)] p-4 sm:p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2"><div className="grid h-9 w-9 flex-none place-items-center rounded-xl bg-[var(--surface-raised)] text-[var(--accent)]">{item.project_id ? <FolderKanban size={16} /> : <Sparkles size={16} />}</div><div className="min-w-0"><h3 className="truncate text-sm font-medium">{item.name}</h3><p className="mt-0.5 text-[10px] text-[var(--text-secondary)]">最近活动 {formatTime(item.last_activity_at)}</p></div></div>
                </div>
                <span className={`inline-flex flex-none items-center gap-1 rounded-full border px-2 py-1 text-[10px] ${statusTone[item.status]}`}><StatusIcon status={item.status} />{statusLabels[item.status]}</span>
              </div>
              <p className="mt-3 line-clamp-2 text-xs leading-5 text-[var(--text-secondary)]">{item.description || item.status_reason}</p>
              <p className="mt-2 text-xs font-medium">{item.status_reason}</p>

              <div className="mt-4 grid grid-cols-3 gap-2 sm:grid-cols-6">
                <MiniMetric label="当前工作" value={item.active_work} icon={Workflow} />
                <MiniMetric label="Goals" value={item.active_goals} icon={Target} />
                <MiniMetric label="待审批" value={item.pending_approvals} icon={ShieldCheck} />
                <MiniMetric label="失败" value={item.failed_responses_7d} icon={AlertTriangle} />
                <MiniMetric label="预警" value={item.unacknowledged_alerts} icon={CircleAlert} />
                <MiniMetric label="自动化" value={item.active_automations} icon={Bot} />
              </div>

              <div className="mt-4 flex flex-wrap gap-2 text-[10px] text-[var(--text-secondary)]">
                <span className={`rounded-full border px-2 py-1 ${item.instructions_ready ? 'border-emerald-500/30 text-emerald-500' : 'border-amber-500/30 text-amber-500'}`}>{item.instructions_ready ? '业务指令已就绪' : '业务指令待完善'}</span>
                <span className="rounded-full border border-[var(--border)] px-2 py-1">{item.data_source_count} 个授权数据源</span>
                <span className="rounded-full border border-[var(--border)] px-2 py-1">{portfolio.window_days} 日交付 {item.delivered_turns_7d}</span>
              </div>

              <div className="mt-auto rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3">
                <p className="text-[10px] font-medium text-[var(--accent)]">建议下一步 · {item.next_action.label}</p>
                <div className="mt-1 flex items-end justify-between gap-3"><div className="min-w-0"><h4 className="text-xs font-medium">{item.next_action.title}</h4><p className="mt-1 line-clamp-2 text-[10px] leading-4 text-[var(--text-secondary)]">{item.next_action.description}</p></div><button type="button" onClick={() => openItem(item)} className="inline-flex flex-none items-center gap-1 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-[11px] font-medium text-[var(--accent-foreground)]">{item.next_action.label}<ArrowRight size={11} /></button></div>
              </div>
            </article>
          ))}
          {visibleItems.length === 0 && (
            <div className="col-span-full rounded-2xl border border-dashed border-[var(--border)] p-12 text-center">
              <Search size={24} className="mx-auto text-[var(--text-secondary)]" />
              <h3 className="mt-3 text-sm font-medium">没有匹配的工作组合</h3>
              <p className="mt-1 text-xs text-[var(--text-secondary)]">调整状态筛选或搜索词后重试。</p>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

function PortfolioMetric({ icon: Icon, label, value, detail, tone }: { icon: typeof Workflow; label: string; value: number | string; detail: string; tone: string }) {
  return <div className="flex items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className={`grid h-10 w-10 flex-none place-items-center rounded-xl bg-[var(--surface-raised)] ${tone}`}><Icon size={18} /></div><div className="min-w-0"><div className="text-2xl font-semibold">{value}</div><div className="text-xs font-medium">{label}</div><div className="truncate text-[10px] text-[var(--text-secondary)]">{detail}</div></div></div>
}

function MiniMetric({ label, value, icon: Icon }: { label: string; value: number; icon: typeof Workflow }) {
  return <div className="rounded-lg bg-[var(--surface-raised)] p-2 text-center"><Icon size={12} className="mx-auto text-[var(--text-secondary)]" /><div className="mt-1 text-sm font-semibold">{value}</div><div className="truncate text-[9px] text-[var(--text-secondary)]">{label}</div></div>
}
