import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  BellRing,
  BookOpen,
  CheckCheck,
  CircleAlert,
  Inbox,
  Search,
  ShieldCheck,
  Workflow,
} from 'lucide-react'
import {
  apiListNotifications,
  apiReadAllNotifications,
  apiReadNotification,
  type EnterpriseWorkbenchOverview,
  type NotificationItem,
  type WorkbenchAttentionItem,
} from '../api/client'
import { useAuthStore } from '../store/auth'

type ActionCategory = 'all' | 'approval' | 'alert' | 'response' | 'knowledge' | 'notification'

type UnifiedActionItem = WorkbenchAttentionItem & {
  read?: boolean
  notificationKind?: NotificationItem['kind']
}

const categoryOptions: Array<{ id: ActionCategory; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'approval', label: '审批' },
  { id: 'alert', label: '预警' },
  { id: 'response', label: '失败执行' },
  { id: 'knowledge', label: '知识治理' },
  { id: 'notification', label: '通知' },
]

const categoryLabels: Record<string, string> = {
  approval: '待审批',
  alert: '主动预警',
  response: '执行异常',
  knowledge: '知识治理',
  notification: '工作通知',
}

function formatTime(value?: string | null) {
  if (!value) return '刚刚'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function actionIcon(type: string) {
  if (type === 'approval') return <ShieldCheck size={18} />
  if (type === 'alert') return <AlertTriangle size={18} />
  if (type === 'response') return <Workflow size={18} />
  if (type === 'knowledge') return <BookOpen size={18} />
  return <BellRing size={18} />
}

function actionTone(item: UnifiedActionItem) {
  if (item.severity === 'critical' || item.severity === 'error') {
    return 'border-red-500/25 bg-red-500/5 text-red-500'
  }
  if (item.severity === 'warning') {
    return 'border-amber-500/25 bg-amber-500/5 text-amber-500'
  }
  return 'border-[var(--border)] bg-[var(--surface)] text-[var(--accent)]'
}

export function WorkbenchActionCenter({
  overview,
  onRefresh,
}: {
  overview: EnterpriseWorkbenchOverview
  onRefresh: () => Promise<void>
}) {
  const token = useAuthStore((state) => state.token)!
  const navigate = useNavigate()
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [category, setCategory] = useState<ActionCategory>('all')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState('')

  const loadNotifications = async (quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      const result = await apiListNotifications(token, 100)
      setNotifications(result.items)
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '通知加载失败')
    } finally {
      if (!quiet) setLoading(false)
    }
  }

  useEffect(() => {
    void loadNotifications()
    const timer = window.setInterval(() => void loadNotifications(true), 30_000)
    return () => window.clearInterval(timer)
  }, [token])

  const items = useMemo<UnifiedActionItem[]>(() => {
    const attentionItems = overview.attention_items.filter((item) => item.type !== 'notification')
    const notificationItems: UnifiedActionItem[] = notifications.map((item) => ({
      id: item.id,
      type: 'notification',
      severity: item.level,
      title: item.title,
      description: item.body || '新的企业主动工作通知等待查看。',
      route: item.kind === 'alert' ? '/alerts' : '/tasks',
      resource_id: item.task_id,
      created_at: item.created_at,
      read: item.read,
      notificationKind: item.kind,
    }))
    return [...attentionItems, ...notificationItems].sort((left, right) =>
      String(right.created_at || '').localeCompare(String(left.created_at || '')),
    )
  }, [notifications, overview.attention_items])

  const visibleItems = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase()
    return items.filter((item) => {
      if (category !== 'all' && item.type !== category) return false
      if (!keyword) return true
      return `${item.title} ${item.description} ${categoryLabels[item.type] || item.type}`
        .toLocaleLowerCase()
        .includes(keyword)
    })
  }, [category, items, query])

  const unreadCount = notifications.filter((item) => !item.read).length
  const criticalCount = items.filter((item) => item.severity === 'critical' || item.severity === 'error').length
  const approvalCount = items.filter((item) => item.type === 'approval').length

  const openItem = async (item: UnifiedActionItem) => {
    if (item.type === 'notification' && !item.read) {
      setBusyId(item.id)
      try {
        await apiReadNotification(token, item.id)
        setNotifications((current) => current.map((notification) =>
          notification.id === item.id ? { ...notification, read: true } : notification,
        ))
        await onRefresh()
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : '更新通知失败')
        setBusyId(null)
        return
      }
      setBusyId(null)
    }
    navigate(item.route)
  }

  const readAll = async () => {
    if (!unreadCount) return
    setBusyId('all')
    try {
      await apiReadAllNotifications(token)
      setNotifications((current) => current.map((item) => ({ ...item, read: true })))
      await onRefresh()
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '全部已读操作失败')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-6">
      <section className="grid gap-3 sm:grid-cols-3">
        <ActionMetric icon={Inbox} label="待处理事项" value={items.filter((item) => item.type !== 'notification').length} tone="text-[var(--accent)]" />
        <ActionMetric icon={CircleAlert} label="高优先级" value={criticalCount} tone="text-red-500" />
        <ActionMetric icon={ShieldCheck} label="待审批动作" value={approvalCount} tone="text-amber-500" />
      </section>

      <section className="overflow-hidden rounded-3xl border border-[var(--border)] bg-[var(--surface)]">
        <div className="border-b border-[var(--border)] p-4 sm:p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="font-medium">统一行动中心</h2>
              <p className="mt-1 text-xs text-[var(--text-secondary)]">集中处理审批、业务预警、失败执行、知识治理与主动工作通知。</p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <label className="relative min-w-0 sm:w-72">
                <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="搜索标题或内容"
                  aria-label="搜索行动事项"
                  className="h-9 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] pl-9 pr-3 text-xs outline-none focus:border-[var(--accent)]"
                />
              </label>
              <button
                type="button"
                onClick={() => void readAll()}
                disabled={!unreadCount || busyId === 'all'}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-xl border border-[var(--border)] px-3 text-xs text-[var(--text-secondary)] hover:bg-[var(--surface-raised)] disabled:opacity-40"
              >
                <CheckCheck size={14} />全部已读{unreadCount ? `（${unreadCount}）` : ''}
              </button>
            </div>
          </div>
          <div className="mt-4 flex gap-1 overflow-x-auto pb-1" role="tablist" aria-label="行动事项分类">
            {categoryOptions.map((option) => {
              const count = option.id === 'all' ? items.length : items.filter((item) => item.type === option.id).length
              return (
                <button
                  key={option.id}
                  type="button"
                  role="tab"
                  aria-selected={category === option.id}
                  onClick={() => setCategory(option.id)}
                  className={`flex-none rounded-lg px-3 py-1.5 text-xs ${category === option.id ? 'bg-[var(--accent-dim)] font-medium text-[var(--accent)]' : 'text-[var(--text-secondary)] hover:bg-[var(--surface-raised)]'}`}
                >
                  {option.label} {count}
                </button>
              )
            })}
          </div>
        </div>

        {error && <div role="alert" className="border-b border-red-500/20 bg-red-500/5 px-5 py-3 text-xs text-red-500">{error}</div>}
        <div className="divide-y divide-[var(--border)]">
          {loading && <div className="p-10 text-center text-sm text-[var(--text-secondary)]">正在加载行动队列…</div>}
          {!loading && visibleItems.map((item) => (
            <article key={`${item.type}-${item.id}`} className={`group flex items-start gap-3 p-4 transition-colors hover:bg-[var(--surface-raised)] sm:p-5 ${item.read ? 'opacity-65' : ''}`}>
              <div className={`grid h-10 w-10 flex-none place-items-center rounded-xl border ${actionTone(item)}`}>{actionIcon(item.type)}</div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-[var(--surface-raised)] px-2 py-0.5 text-[10px] text-[var(--text-secondary)]">{categoryLabels[item.type] || item.type}</span>
                  {item.type === 'notification' && !item.read && <span className="h-2 w-2 rounded-full bg-[var(--accent)]" aria-label="未读" />}
                  <span className="ml-auto text-[10px] text-[var(--text-secondary)]">{formatTime(item.created_at)}</span>
                </div>
                <h3 className="mt-2 text-sm font-medium">{item.title}</h3>
                <p className="mt-1 text-xs leading-5 text-[var(--text-secondary)]">{item.description}</p>
              </div>
              <button
                type="button"
                disabled={busyId === item.id}
                onClick={() => void openItem(item)}
                className="mt-7 flex-none rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:opacity-50"
              >
                {item.type === 'notification' && !item.read ? '查看并已读' : '进入处理'}
              </button>
            </article>
          ))}
          {!loading && visibleItems.length === 0 && (
            <div className="p-12 text-center">
              <CheckCheck size={28} className="mx-auto text-emerald-500" />
              <h3 className="mt-3 text-sm font-medium">当前筛选下没有待处理事项</h3>
              <p className="mt-1 text-xs text-[var(--text-secondary)]">系统会持续汇总企业工作状态，新事项将在这里出现。</p>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

function ActionMetric({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Inbox
  label: string
  value: number
  tone: string
}) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className={`grid h-10 w-10 place-items-center rounded-xl bg-[var(--surface-raised)] ${tone}`}><Icon size={18} /></div>
      <div><div className="text-2xl font-semibold">{value}</div><div className="text-xs text-[var(--text-secondary)]">{label}</div></div>
    </div>
  )
}
