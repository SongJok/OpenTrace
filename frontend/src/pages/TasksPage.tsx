import { useEffect, useState } from 'react'
import { Ban, ChevronLeft, Pause, Play, Plus } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import {
  apiCreateScheduledTask,
  apiListScheduledTasks,
  apiPreviewScheduledTask,
  apiScheduledTaskAction,
  type ScheduledTaskItem,
} from '../api/client'

export default function TasksPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((state) => state.token)!
  const [tasks, setTasks] = useState<ScheduledTaskItem[]>([])
  const [title, setTitle] = useState('')
  const [prompt, setPrompt] = useState('')
  const [scheduleText, setScheduleText] = useState('每天 09:00')
  const [rrule, setRrule] = useState('')
  const [nextRunAt, setNextRunAt] = useState<string | null>(null)
  const [timezone, setTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')
  const [saving, setSaving] = useState(false)

  const load = async () => setTasks(await apiListScheduledTasks(token))
  useEffect(() => { void load() }, [])

  const create = async () => {
    if (!title.trim() || !prompt.trim() || !rrule) return
    setSaving(true)
    try {
      await apiCreateScheduledTask(token, {
        title: title.trim(), prompt: prompt.trim(), rrule: rrule.trim(), timezone,
        enabled: false, requires_confirmation: true,
      })
      setTitle('')
      setPrompt('')
      setRrule('')
      setNextRunAt(null)
      await load()
    } finally {
      setSaving(false)
    }
  }

  const preview = async () => {
    const result = await apiPreviewScheduledTask(token, scheduleText, timezone)
    setRrule(result.rrule)
    setNextRunAt(result.next_run_at ?? null)
  }

  const action = async (taskId: string, next: 'enable' | 'pause' | 'cancel') => {
    await apiScheduledTaskAction(token, taskId, next)
    await load()
  }

  return (
    <div className="flex h-screen flex-col bg-[var(--bg)] text-[var(--text)]">
      <header className="flex h-14 items-center gap-3 border-b border-[var(--border)] px-6">
        <button onClick={onBack} className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
        <div><h1 className="text-sm font-semibold">定时任务</h1><p className="text-xs text-[var(--text-secondary)]">每次运行都使用完整 Agent Loop，草稿确认后才启用。</p></div>
      </header>
      <main className="mx-auto grid w-full max-w-6xl flex-1 grid-cols-1 gap-6 overflow-auto p-6 lg:grid-cols-[360px_1fr]">
        <section className="h-fit space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <h2 className="font-medium">新建任务</h2>
          <label className="block text-xs text-[var(--text-secondary)]">名称<input value={title} onChange={(event) => setTitle(event.target.value)} className="mt-1 w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /></label>
          <label className="block text-xs text-[var(--text-secondary)]">运行提示词<textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={5} className="mt-1 w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /></label>
          <label className="block text-xs text-[var(--text-secondary)]">运行时间<input value={scheduleText} onChange={(event) => { setScheduleText(event.target.value); setRrule(''); setNextRunAt(null) }} placeholder="例如：每周一 09:30" className="mt-1 w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /></label>
          <label className="block text-xs text-[var(--text-secondary)]">时区<input value={timezone} onChange={(event) => { setTimezone(event.target.value); setRrule(''); setNextRunAt(null) }} className="mt-1 w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /></label>
          {!rrule ? <button onClick={() => void preview()} className="rounded-xl border border-[var(--border)] px-4 py-2 text-sm">预览日程</button> : <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 text-xs"><div className="font-mono">{rrule}</div><div className="mt-1 text-[var(--text-secondary)]">下次运行：{nextRunAt ? new Date(nextRunAt).toLocaleString() : '—'}</div></div>}
          <button disabled={saving || !rrule} onClick={() => void create()} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-50"><Plus size={15} />确认并保存草稿</button>
        </section>
        <section className="space-y-3">
          {tasks.length === 0 ? <div className="rounded-2xl border border-dashed border-[var(--border)] p-10 text-center text-sm text-[var(--text-secondary)]">暂无定时任务</div> : tasks.map((task) => (
            <article key={task.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <div className="flex items-start justify-between gap-4"><div><h3 className="font-medium">{task.title}</h3><p className="mt-1 text-sm text-[var(--text-secondary)]">{task.prompt}</p></div><span className="rounded-full border border-[var(--border)] px-2 py-1 text-xs">{task.status}</span></div>
              <div className="mt-4 grid gap-1 text-xs text-[var(--text-secondary)]"><span>{task.rrule}</span><span>{task.timezone} · 下次运行 {task.next_run_at ? new Date(task.next_run_at).toLocaleString() : '—'}</span><span>外部写操作：运行时逐项请求授权</span></div>
              <div className="mt-4 flex gap-2">
                {task.status !== 'active' && task.status !== 'cancelled' && <button onClick={() => void action(task.id, 'enable')} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm"><Play size={13} />启用</button>}
                {task.status === 'active' && <button onClick={() => void action(task.id, 'pause')} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm"><Pause size={13} />暂停</button>}
                {task.status !== 'cancelled' && <button onClick={() => void action(task.id, 'cancel')} className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 px-3 py-1.5 text-sm text-red-500"><Ban size={13} />取消</button>}
              </div>
            </article>
          ))}
        </section>
      </main>
    </div>
  )
}
