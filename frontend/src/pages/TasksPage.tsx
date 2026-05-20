import { useEffect, useState } from 'react'
import { ChevronLeft, Play, Pause, Ban, Bell, Plus } from 'lucide-react'
import { t } from '../i18n'
import { useAuthStore } from '../store/auth'
import {
  apiCancelTask,
  apiCreateTask,
  apiGetTask,
  apiListTaskNotifications,
  apiListTasks,
  apiMarkTaskNotificationRead,
  apiPauseTask,
  apiResumeTask,
  type TaskItem,
  type TaskNotificationItem,
  type TaskRunItem,
} from '../api/client'

export default function TasksPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((s) => s.token)!
  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [runs, setRuns] = useState<TaskRunItem[]>([])
  const [notifications, setNotifications] = useState<TaskNotificationItem[]>([])
  const [description, setDescription] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const [ts, ns] = await Promise.all([apiListTasks(token), apiListTaskNotifications(token)])
      setTasks(ts)
      setNotifications(ns)
      if (!selectedId && ts.length > 0) setSelectedId(ts[0].id)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  useEffect(() => {
    const loadRuns = async () => {
      if (!selectedId) {
        setRuns([])
        return
      }
      const detail = await apiGetTask(token, selectedId)
      setRuns(detail.runs)
    }
    void loadRuns()
  }, [selectedId, token])

  const createTask = async () => {
    if (!description.trim()) return
    await apiCreateTask(token, description.trim())
    setDescription('')
    await load()
  }

  const pause = async (taskId: string) => {
    await apiPauseTask(token, taskId)
    await load()
  }

  const resume = async (taskId: string) => {
    await apiResumeTask(token, taskId)
    await load()
  }

  const cancel = async (taskId: string) => {
    await apiCancelTask(token, taskId)
    await load()
  }

  const markRead = async (id: string) => {
    await apiMarkTaskNotificationRead(token, id)
    await load()
  }

  return (
    <div className="flex flex-col h-screen bg-[var(--bg)] text-[var(--text)]">
      <div className="flex items-center gap-3 px-6 h-14 border-b border-[var(--border)]">
        <button onClick={onBack} className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[var(--surface)]">
          <ChevronLeft size={18} />
        </button>
        <h1 className="text-sm font-semibold">{t('nav.tasks')}</h1>
      </div>

      <div className="grid grid-cols-12 gap-4 p-4 flex-1 overflow-hidden">
        <div className="col-span-4 space-y-3 overflow-y-auto">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 space-y-2">
            <p className="text-sm font-semibold">委托新任务</p>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="例如：每小时检查 HackerNews 的 AI 文章并给我摘要"
              className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-sm"
            />
            <button onClick={() => void createTask()} className="px-3 py-1.5 rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-xs inline-flex items-center gap-1">
              <Plus size={12} /> 创建
            </button>
          </div>

          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 space-y-2">
            <p className="text-sm font-semibold">任务列表</p>
            {loading ? <p className="text-xs text-[var(--text-secondary)]">加载中...</p> : tasks.length === 0 ? <p className="text-xs text-[var(--text-secondary)]">暂无任务</p> : tasks.map((t) => (
              <div key={t.id} className={`rounded border p-2 ${selectedId === t.id ? 'border-[var(--accent)]' : 'border-[var(--border)]'}`}>
                <button onClick={() => setSelectedId(t.id)} className="w-full text-left">
                  <p className="text-sm font-medium truncate">{t.title}</p>
                  <p className="text-[11px] text-[var(--text-secondary)]">{t.trigger_type} · {t.status}</p>
                </button>
                <div className="mt-2 flex gap-1">
                  {t.status === 'active' ? (
                    <button onClick={() => void pause(t.id)} className="px-2 py-1 rounded text-xs border inline-flex items-center gap-1"><Pause size={11} /> 暂停</button>
                  ) : t.status === 'paused' ? (
                    <button onClick={() => void resume(t.id)} className="px-2 py-1 rounded text-xs border inline-flex items-center gap-1"><Play size={11} /> 恢复</button>
                  ) : null}
                  {t.status !== 'cancelled' && (
                    <button onClick={() => void cancel(t.id)} className="px-2 py-1 rounded text-xs border border-red-300 text-red-500 inline-flex items-center gap-1"><Ban size={11} /> 取消</button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="col-span-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 overflow-y-auto">
          <p className="text-sm font-semibold mb-2">运行历史</p>
          {runs.length === 0 ? <p className="text-xs text-[var(--text-secondary)]">暂无运行记录</p> : runs.map((r) => (
            <div key={r.id} className="rounded border border-[var(--border)] p-2 mb-2">
              <p className="text-xs">{r.status}</p>
              {r.output && <p className="text-xs whitespace-pre-wrap">{r.output}</p>}
              {r.error && <p className="text-xs text-red-500 whitespace-pre-wrap">{r.error}</p>}
            </div>
          ))}
        </div>

        <div className="col-span-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 overflow-y-auto">
          <p className="text-sm font-semibold mb-2 inline-flex items-center gap-1"><Bell size={14} /> 通知</p>
          {notifications.length === 0 ? <p className="text-xs text-[var(--text-secondary)]">暂无通知</p> : notifications.map((n) => (
            <div key={n.id} className={`rounded border p-2 mb-2 ${n.read ? 'border-[var(--border)]' : 'border-[var(--accent)]'}`}>
              <p className="text-xs font-medium">{n.title}</p>
              {n.body && <p className="text-xs whitespace-pre-wrap">{n.body}</p>}
              <div className="mt-1 flex justify-end">
                {!n.read && <button onClick={() => void markRead(n.id)} className="text-[11px] px-2 py-1 border rounded">标记已读</button>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
