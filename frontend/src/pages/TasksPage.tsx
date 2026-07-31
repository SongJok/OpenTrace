import { useEffect, useState } from 'react'
import { Ban, ChevronDown, ChevronLeft, Clock3, LoaderCircle, Pause, Play, Plus, RefreshCw, Zap } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import {
  apiCreateScheduledTask,
  apiGetScheduledTask,
  apiListScheduledTasks,
  apiPreviewScheduledTaskRule,
  apiRunScheduledTask,
  apiScheduledTaskAction,
  type ScheduledTaskDetail,
  type ScheduledTaskItem,
} from '../api/client'
import { createDefaultScheduleWindow, ScheduleTimePicker, type ScheduleWindowValue } from '../components/ScheduleTimePicker'
import { DEFAULT_TIMEZONE } from '../utils/timezone'

export default function TasksPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((state) => state.token)!
  const [tasks, setTasks] = useState<ScheduledTaskItem[]>([])
  const [title, setTitle] = useState('')
  const [prompt, setPrompt] = useState('')
  const [scheduleWindow, setScheduleWindow] = useState<ScheduleWindowValue>(() => createDefaultScheduleWindow(DEFAULT_TIMEZONE))
  const [upcomingTimes, setUpcomingTimes] = useState<string[]>([])
  const [previewing, setPreviewing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null)
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null)
  const [details, setDetails] = useState<Record<string, ScheduledTaskDetail>>({})
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = async () => setTasks(await apiListScheduledTasks(token))
  useEffect(() => {
    void load().catch((reason) => setError(reason?.message || '读取定时任务失败'))
    const timer = window.setInterval(() => {
      void load().catch(() => undefined)
      if (expandedTaskId) {
        void apiGetScheduledTask(token, expandedTaskId).then((detail) => {
          setDetails((current) => ({ ...current, [expandedTaskId]: detail }))
        }).catch(() => undefined)
      }
    }, 10_000)
    return () => window.clearInterval(timer)
  }, [expandedTaskId, token])

  const create = async () => {
    if (!title.trim() || !prompt.trim() || !scheduleWindow.rrule.trim()) return
    setSaving(true)
    setError('')
    try {
      await apiCreateScheduledTask(token, {
        title: title.trim(), prompt: prompt.trim(), rrule: scheduleWindow.rrule.trim(), timezone: scheduleWindow.timezone,
        starts_at: scheduleWindow.startsAt || null, ends_at: scheduleWindow.endsAt,
        enabled: false, requires_confirmation: true,
      })
      setTitle('')
      setPrompt('')
      setScheduleWindow(createDefaultScheduleWindow(scheduleWindow.timezone))
      setUpcomingTimes([])
      setNotice('任务草稿已保存，确认无误后可启用或立即试运行。')
      await load()
    } catch (reason: any) {
      setError(reason?.message || '保存任务失败')
    } finally {
      setSaving(false)
    }
  }

  const preview = async () => {
    setError('')
    setPreviewing(true)
    try {
      const result = await apiPreviewScheduledTaskRule(token, {
        rrule: scheduleWindow.rrule.trim(),
        timezone: scheduleWindow.timezone,
        starts_at: scheduleWindow.startsAt || null,
        ends_at: scheduleWindow.endsAt,
        count: 5,
      })
      setUpcomingTimes(result.next_run_times || [])
    } catch (reason: any) {
      setUpcomingTimes([])
      setError(reason?.message || '无法预览执行时间')
    } finally {
      setPreviewing(false)
    }
  }

  const updateScheduleWindow = (value: ScheduleWindowValue) => {
    setScheduleWindow(value)
    setUpcomingTimes([])
  }

  const action = async (taskId: string, next: 'enable' | 'pause' | 'cancel') => {
    setBusyTaskId(taskId)
    setError('')
    try {
      await apiScheduledTaskAction(token, taskId, next)
      await load()
    } catch (reason: any) {
      setError(reason?.message || '更新任务失败')
    } finally {
      setBusyTaskId(null)
    }
  }

  const runNow = async (taskId: string) => {
    setBusyTaskId(taskId)
    setError('')
    try {
      await apiRunScheduledTask(token, taskId)
      const detail = await apiGetScheduledTask(token, taskId)
      setDetails((current) => ({ ...current, [taskId]: detail }))
      setExpandedTaskId(taskId)
      setNotice('任务已进入后台运行，完成后会出现在通知中心。')
      await load()
    } catch (reason: any) {
      setError(reason?.message || '立即运行失败')
    } finally {
      setBusyTaskId(null)
    }
  }

  const toggleRuns = async (taskId: string) => {
    if (expandedTaskId === taskId) {
      setExpandedTaskId(null)
      return
    }
    setExpandedTaskId(taskId)
    try {
      const detail = await apiGetScheduledTask(token, taskId)
      setDetails((current) => ({ ...current, [taskId]: detail }))
    } catch (reason: any) {
      setError(reason?.message || '读取运行历史失败')
    }
  }

  return (
    <div className="flex h-screen flex-col bg-[var(--bg)] text-[var(--text)]">
      <header className="flex h-14 items-center gap-3 border-b border-[var(--border)] px-6">
        <button onClick={onBack} className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
        <div><h1 className="text-sm font-semibold">定时任务</h1><p className="text-xs text-[var(--text-secondary)]">每次运行都使用完整 Agent Loop，草稿确认后才启用。</p></div>
      </header>
      <main className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 gap-6 overflow-auto p-6 xl:grid-cols-[500px_1fr]">
        <section className="h-fit space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <div><h2 className="font-medium">新建任务</h2><p className="mt-1 text-xs text-[var(--text-secondary)]">描述要完成的工作，再设置明确、可预览的运行时间。</p></div>
          <label className="block text-xs text-[var(--text-secondary)]">名称<input value={title} onChange={(event) => setTitle(event.target.value)} className="mt-1 w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /></label>
          <label className="block text-xs text-[var(--text-secondary)]">运行提示词<textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={5} className="mt-1 w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /></label>
          <ScheduleTimePicker value={scheduleWindow} upcomingTimes={upcomingTimes} previewing={previewing} onChange={updateScheduleWindow} onPreview={() => void preview()} />
          <button disabled={saving || !scheduleWindow.rrule.trim()} onClick={() => void create()} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-50"><Plus size={15} />确认并保存草稿</button>
          {(error || notice) && <div role="status" aria-live="polite" className={`rounded-xl border p-3 text-xs ${error ? 'border-red-500/30 text-red-500' : 'border-emerald-500/30 text-emerald-500'}`}>{error || notice}</div>}
        </section>
        <section className="space-y-3">
          {tasks.length === 0 ? <div className="rounded-2xl border border-dashed border-[var(--border)] p-10 text-center text-sm text-[var(--text-secondary)]">暂无定时任务</div> : tasks.map((task) => (
            <article key={task.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <div className="flex items-start justify-between gap-4"><div><h3 className="font-medium">{task.title}</h3><p className="mt-1 text-sm text-[var(--text-secondary)]">{task.prompt}</p></div><span className="rounded-full border border-[var(--border)] px-2 py-1 text-xs">{statusLabel(task.status)}</span></div>
              <div className="mt-4 grid gap-1 text-xs text-[var(--text-secondary)]"><span className="inline-flex items-center gap-1"><Clock3 size={12} />{task.rrule}</span><span>{task.timezone} · 有效期 {formatTaskWindow(task)}</span><span>下次运行 {task.next_run_at ? new Date(task.next_run_at).toLocaleString() : '—'} · 上次运行 {task.last_run_at ? new Date(task.last_run_at).toLocaleString() : '—'}</span><span>外部写操作逐项请求授权</span></div>
              <div className="mt-4 flex flex-wrap gap-2">
                <button disabled={busyTaskId === task.id || task.status === 'cancelled'} onClick={() => void runNow(task.id)} className="inline-flex items-center gap-1 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm text-[var(--accent-foreground)] disabled:opacity-50">{busyTaskId === task.id ? <LoaderCircle className="animate-spin" size={13} /> : <Zap size={13} />}立即运行</button>
                {task.status !== 'active' && task.status !== 'cancelled' && <button disabled={busyTaskId === task.id} onClick={() => void action(task.id, 'enable')} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm"><Play size={13} />启用</button>}
                {task.status === 'active' && <button disabled={busyTaskId === task.id} onClick={() => void action(task.id, 'pause')} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm"><Pause size={13} />暂停</button>}
                {task.status !== 'cancelled' && <button disabled={busyTaskId === task.id} onClick={() => void action(task.id, 'cancel')} className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 px-3 py-1.5 text-sm text-red-500"><Ban size={13} />取消</button>}
                <button onClick={() => void toggleRuns(task.id)} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm"><RefreshCw size={13} />运行记录<ChevronDown size={13} className={expandedTaskId === task.id ? 'rotate-180' : ''} /></button>
              </div>
              {expandedTaskId === task.id && <div className="mt-4 space-y-2 border-t border-[var(--border)] pt-4">{!details[task.id] ? <div className="text-xs text-[var(--text-secondary)]">正在加载…</div> : details[task.id].runs.length === 0 ? <div className="text-xs text-[var(--text-secondary)]">还没有运行记录</div> : details[task.id].runs.map((run) => <div key={run.id} className="rounded-xl bg-[var(--bg)] p-3 text-xs"><div className="flex items-center justify-between gap-3"><span className="font-medium">{statusLabel(run.status)}</span><span className="text-[var(--text-secondary)]">{run.scheduled_for ? new Date(run.scheduled_for).toLocaleString() : '—'}</span></div>{run.error && <p className="mt-2 text-red-500">{run.error}</p>}{run.output && <p className="mt-2 line-clamp-3 whitespace-pre-wrap text-[var(--text-secondary)]">{run.output}</p>}</div>)}</div>}
            </article>
          ))}
        </section>
      </main>
    </div>
  )
}

function statusLabel(status: string) {
  return ({ active: '运行中', draft: '草稿', paused: '已暂停', cancelled: '已取消', completed: '已结束', queued: '排队中', succeeded: '已完成', failed: '失败', incomplete: '未完整完成', requires_action: '等待确认' } as Record<string, string>)[status] || status
}

function formatTaskWindow(task: ScheduledTaskItem) {
  const start = task.starts_at ? new Date(task.starts_at).toLocaleString() : '立即生效'
  const end = task.ends_at ? new Date(task.ends_at).toLocaleString() : '长期有效'
  return `${start} → ${end}`
}
