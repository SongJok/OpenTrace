import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CalendarClock,
  CheckCircle2,
  Clock3,
  Focus,
  ShieldCheck,
  Target,
} from 'lucide-react'
import type {
  WorkbenchAttentionItem,
  WorkbenchOperatingPulse,
  WorkbenchTimelineItem,
} from '../api/client'

const priorityLabels = { p0: 'P0', p1: 'P1', p2: 'P2', p3: 'P3' } as const
const priorityTone = {
  p0: 'border-red-500/30 bg-red-500/10 text-red-500',
  p1: 'border-orange-500/30 bg-orange-500/10 text-orange-500',
  p2: 'border-amber-500/30 bg-amber-500/10 text-amber-500',
  p3: 'border-[var(--border)] bg-[var(--surface-raised)] text-[var(--text-secondary)]',
} as const

function formatClock(value: string, timezone: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: timezone,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function formatMinutes(value: number) {
  if (value < 60) return `${value} 分钟`
  const hours = Math.floor(value / 60)
  const minutes = value % 60
  return minutes ? `${hours} 小时 ${minutes} 分` : `${hours} 小时`
}

function focusIcon(item: WorkbenchAttentionItem) {
  if (item.type === 'approval') return ShieldCheck
  if (item.type === 'alert') return AlertTriangle
  if (item.type === 'goal') return Target
  if (item.type === 'automation') return Bot
  return Clock3
}

function timelineIcon(item: WorkbenchTimelineItem) {
  if (item.type === 'calendar' && item.event_type === 'focus') return Focus
  if (item.type === 'calendar') return CalendarClock
  if (item.type === 'alert') return AlertTriangle
  return Bot
}

export function WorkbenchTodayPulse({ pulse }: { pulse: WorkbenchOperatingPulse }) {
  const navigate = useNavigate()
  const visibleFocusItems = pulse.focus_items.slice(0, 5)
  const visibleTimeline = pulse.timeline.slice(0, 7)
  const dateLabel = useMemo(() => {
    const date = new Date(`${pulse.local_date}T00:00:00`)
    return Number.isNaN(date.getTime())
      ? pulse.local_date
      : new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(date)
  }, [pulse.local_date])
  const statusTone = pulse.status === 'critical'
    ? 'border-red-500/25 bg-red-500/5'
    : pulse.status === 'attention'
      ? 'border-amber-500/25 bg-amber-500/5'
      : 'border-emerald-500/25 bg-emerald-500/5'

  return (
    <section className={`overflow-hidden rounded-3xl border ${statusTone}`} aria-label="今日工作脉搏">
      <div className="border-b border-[var(--border)] bg-[var(--surface)] px-5 py-4 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
              <CalendarClock size={14} />今日工作脉搏 · {dateLabel} · {pulse.timezone}
            </div>
            <h2 className="mt-2 text-lg font-semibold">{pulse.headline}</h2>
            <p className="mt-1 text-xs leading-5 text-[var(--text-secondary)]">
              由审批、Responses、Goal、定时任务、预警与日历事实确定性计算，不使用模型猜测优先级。
            </p>
          </div>
          <button
            type="button"
            onClick={() => navigate('/work?tab=inbox')}
            className="inline-flex items-center gap-1 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--accent)]"
          >
            打开行动中心<ArrowRight size={13} />
          </button>
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <PulseMetric label="立即处理" value={pulse.summary.urgent_items} detail={pulse.summary.overdue_automations ? `${pulse.summary.overdue_automations} 个自动化逾期` : '无逾期自动化'} />
          <PulseMetric label="今日安排" value={pulse.summary.calendar_events} detail={`会议 ${formatMinutes(pulse.summary.meeting_minutes)}`} />
          <PulseMetric label="自动化节点" value={pulse.summary.due_automations} detail="任务与指标检查" />
          <PulseMetric label="Goal 待推进" value={pulse.summary.stale_goals} detail={`专注时间 ${formatMinutes(pulse.summary.focus_minutes)}`} />
        </div>
      </div>

      <div className="grid bg-[var(--bg)] lg:grid-cols-[1.2fr_0.8fr]">
        <div className="border-b border-[var(--border)] p-5 sm:p-6 lg:border-b-0 lg:border-r">
          <div className="mb-3 flex items-center justify-between">
            <div><h3 className="text-sm font-medium">优先工作</h3><p className="text-xs text-[var(--text-secondary)]">风险、类型、等待时长与逾期共同排序。</p></div>
            <span className="text-[10px] text-[var(--text-secondary)]">最多展示 5 项</span>
          </div>
          <div className="space-y-2">
            {visibleFocusItems.map((item) => {
              const Icon = focusIcon(item)
              const priority = item.priority || 'p3'
              return (
                <button
                  key={`${item.type}-${item.id}`}
                  type="button"
                  onClick={() => navigate(item.route)}
                  className="flex w-full items-start gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3 text-left hover:border-[var(--accent)]/40"
                >
                  <div className="grid h-9 w-9 flex-none place-items-center rounded-xl bg-[var(--surface-raised)] text-[var(--accent)]"><Icon size={16} /></div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-2"><h4 className="min-w-0 flex-1 text-sm font-medium">{item.title}</h4><span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${priorityTone[priority]}`}>{priorityLabels[priority]}</span></div>
                    <p className="mt-1 line-clamp-2 text-xs leading-5 text-[var(--text-secondary)]">{item.priority_reason || item.description}</p>
                  </div>
                </button>
              )
            })}
            {visibleFocusItems.length === 0 && <div className="rounded-2xl border border-dashed border-[var(--border)] p-8 text-center"><CheckCircle2 size={24} className="mx-auto text-emerald-500" /><p className="mt-2 text-sm font-medium">当前没有阻塞事项</p><p className="mt-1 text-xs text-[var(--text-secondary)]">可以按今日时间线继续推进。</p></div>}
          </div>
        </div>

        <div className="p-5 sm:p-6">
          <div className="mb-3"><h3 className="text-sm font-medium">今日时间线</h3><p className="text-xs text-[var(--text-secondary)]">个人安排与企业自动化共用一个时间视图。</p></div>
          <div className="space-y-1">
            {visibleTimeline.map((item) => {
              const Icon = timelineIcon(item)
              return (
                <button key={`${item.type}-${item.id}`} type="button" onClick={() => navigate(item.route)} className="flex w-full items-start gap-3 rounded-xl px-2 py-2.5 text-left hover:bg-[var(--surface)]">
                  <div className={`mt-0.5 grid h-8 w-8 flex-none place-items-center rounded-lg ${item.status === 'overdue' ? 'bg-red-500/10 text-red-500' : item.status === 'in_progress' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-[var(--surface-raised)] text-[var(--accent)]'}`}><Icon size={15} /></div>
                  <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><span className="w-12 flex-none text-[11px] font-medium">{formatClock(item.start_at, pulse.timezone)}</span><span className="truncate text-xs font-medium">{item.title}</span></div><p className="ml-14 mt-0.5 truncate text-[10px] text-[var(--text-secondary)]">{item.description}</p></div>
                </button>
              )
            })}
            {visibleTimeline.length === 0 && <div className="rounded-2xl border border-dashed border-[var(--border)] p-8 text-center"><Clock3 size={24} className="mx-auto text-[var(--text-secondary)]" /><p className="mt-2 text-sm font-medium">今天暂无计划节点</p><p className="mt-1 text-xs text-[var(--text-secondary)]">可从日历、定时任务或主动预警建立节奏。</p></div>}
          </div>
        </div>
      </div>
    </section>
  )
}

function PulseMetric({ label, value, detail }: { label: string; value: number; detail: string }) {
  return <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg)] px-4 py-3"><div className="flex items-end justify-between gap-2"><span className="text-xs text-[var(--text-secondary)]">{label}</span><span className="text-2xl font-semibold">{value}</span></div><p className="mt-1 truncate text-[10px] text-[var(--text-secondary)]">{detail}</p></div>
}
