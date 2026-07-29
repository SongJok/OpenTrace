import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bot,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Clock3,
  List,
  MapPin,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import {
  apiCancelCalendarEvent,
  apiCreateCalendarEvent,
  apiListCalendarEvents,
  apiUpdateCalendarEvent,
  type CalendarEventItem,
} from '../api/client'
import { useAuthStore } from '../store/auth'
import { useChatPreferences } from '../store/chatPreferences'

type CalendarView = 'month' | 'agenda'
type RecurrenceMode = 'none' | 'daily' | 'weekly' | 'monthly'

const weekdayLabels = ['一', '二', '三', '四', '五', '六', '日']
const eventTypeLabels: Record<CalendarEventItem['event_type'], string> = {
  event: '日程',
  meeting: '会议',
  focus: '专注',
  reminder: '提醒',
}

function startOfDay(value: Date) {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate())
}

function startOfMonth(value: Date) {
  return new Date(value.getFullYear(), value.getMonth(), 1)
}

function startOfWeek(value: Date) {
  const day = value.getDay() || 7
  const result = startOfDay(value)
  result.setDate(result.getDate() - day + 1)
  return result
}

function addDays(value: Date, amount: number) {
  const result = new Date(value)
  result.setDate(result.getDate() + amount)
  return result
}

function dateKey(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function sameDay(left: Date, right: Date) {
  return dateKey(left) === dateKey(right)
}

function eventLocalDate(event: CalendarEventItem) {
  return event.local_start_at.slice(0, 10)
}

function formatEventTime(event: CalendarEventItem) {
  if (event.all_day) return '全天'
  const start = new Date(event.local_start_at)
  const end = new Date(event.local_end_at)
  return `${start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} - ${end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
}

function eventTone(type: CalendarEventItem['event_type']) {
  return ({
    event: 'border-blue-500/25 bg-blue-500/10 text-blue-500',
    meeting: 'border-violet-500/25 bg-violet-500/10 text-violet-500',
    focus: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-500',
    reminder: 'border-amber-500/25 bg-amber-500/10 text-amber-500',
  } as const)[type]
}

function recurrenceRule(mode: RecurrenceMode) {
  if (mode === 'daily') return 'FREQ=DAILY'
  if (mode === 'weekly') return 'FREQ=WEEKLY'
  if (mode === 'monthly') return 'FREQ=MONTHLY'
  return null
}

function inferRecurrenceMode(rule?: string | null): RecurrenceMode {
  if (rule?.includes('FREQ=DAILY')) return 'daily'
  if (rule?.includes('FREQ=WEEKLY')) return 'weekly'
  if (rule?.includes('FREQ=MONTHLY')) return 'monthly'
  return 'none'
}

export default function CalendarPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((state) => state.token)!
  const navigate = useNavigate()
  const requestPrefill = useChatPreferences((state) => state.requestPrefill)
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai'
  const [view, setView] = useState<CalendarView>('month')
  const [anchor, setAnchor] = useState(() => startOfMonth(new Date()))
  const [selectedDate, setSelectedDate] = useState(() => startOfDay(new Date()))
  const [events, setEvents] = useState<CalendarEventItem[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [eventType, setEventType] = useState<CalendarEventItem['event_type']>('event')
  const [eventDate, setEventDate] = useState(() => dateKey(new Date()))
  const [startTime, setStartTime] = useState('09:00')
  const [endTime, setEndTime] = useState('10:00')
  const [allDay, setAllDay] = useState(false)
  const [location, setLocation] = useState('')
  const [description, setDescription] = useState('')
  const [recurrence, setRecurrence] = useState<RecurrenceMode>('none')
  const [reminder, setReminder] = useState(15)

  const gridStart = useMemo(() => startOfWeek(startOfMonth(anchor)), [anchor])
  const gridDays = useMemo(() => Array.from({ length: 42 }, (_, index) => addDays(gridStart, index)), [gridStart])
  const gridEnd = useMemo(() => addDays(gridStart, 42), [gridStart])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setEvents(await apiListCalendarEvents(token, gridStart.toISOString(), gridEnd.toISOString(), timezone))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '日历加载失败')
    } finally {
      setLoading(false)
    }
  }, [gridEnd, gridStart, timezone, token])

  useEffect(() => { void load() }, [load])

  const eventsByDay = useMemo(() => {
    const grouped = new Map<string, CalendarEventItem[]>()
    for (const event of events) {
      const key = eventLocalDate(event)
      grouped.set(key, [...(grouped.get(key) || []), event])
    }
    return grouped
  }, [events])

  const selectedEvents = useMemo(
    () => eventsByDay.get(dateKey(selectedDate)) || [],
    [eventsByDay, selectedDate],
  )

  const agendaGroups = useMemo(() => {
    const grouped = new Map<string, CalendarEventItem[]>()
    for (const event of events) {
      const key = eventLocalDate(event)
      grouped.set(key, [...(grouped.get(key) || []), event])
    }
    return [...grouped.entries()].sort(([left], [right]) => left.localeCompare(right))
  }, [events])

  const resetEditor = (date = selectedDate) => {
    setEditingId(null)
    setTitle('')
    setEventType('event')
    setEventDate(dateKey(date))
    setStartTime('09:00')
    setEndTime('10:00')
    setAllDay(false)
    setLocation('')
    setDescription('')
    setRecurrence('none')
    setReminder(15)
  }

  const openCreate = (date = selectedDate) => {
    resetEditor(date)
    setEditorOpen(true)
  }

  const openEdit = (event: CalendarEventItem) => {
    const start = new Date(event.local_start_at)
    const end = new Date(event.local_end_at)
    setEditingId(event.id)
    setTitle(event.title)
    setEventType(event.event_type)
    setEventDate(eventLocalDate(event))
    setStartTime(start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }))
    setEndTime(end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }))
    setAllDay(event.all_day)
    setLocation(event.location)
    setDescription(event.description)
    setRecurrence(inferRecurrenceMode(event.recurrence_rule))
    setReminder(event.reminder_minutes[0] ?? 15)
    setEditorOpen(true)
  }

  const save = async () => {
    if (!title.trim()) return
    setSaving(true)
    setError('')
    try {
      const start = new Date(`${eventDate}T${allDay ? '00:00' : startTime}:00`)
      const end = allDay
        ? addDays(start, 1)
        : new Date(`${eventDate}T${endTime}:00`)
      const payload = {
        title: title.trim(),
        description: description.trim(),
        location: location.trim(),
        event_type: eventType,
        start_at: start.toISOString(),
        end_at: end.toISOString(),
        timezone,
        all_day: allDay,
        recurrence_rule: recurrenceRule(recurrence),
        reminder_minutes: [reminder],
      }
      if (editingId) await apiUpdateCalendarEvent(token, editingId, payload)
      else await apiCreateCalendarEvent(token, payload)
      setEditorOpen(false)
      resetEditor()
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存日程失败')
    } finally {
      setSaving(false)
    }
  }

  const cancel = async (event: CalendarEventItem) => {
    if (!window.confirm(`确认取消“${event.title}”吗？`)) return
    setError('')
    try {
      await apiCancelCalendarEvent(token, event.id)
      setEditorOpen(false)
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '取消日程失败')
    }
  }

  const askAi = () => {
    requestPrefill('帮我添加一个日程：')
    navigate('/chat')
  }

  return (
    <div className="flex min-h-screen flex-col bg-[var(--bg)] text-[var(--text)]">
      <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--bg)]/95 backdrop-blur">
        <div className="mx-auto flex h-16 w-full max-w-[1500px] items-center gap-3 px-4 sm:px-6">
          <button onClick={onBack} aria-label="返回对话" className="grid h-9 w-9 place-items-center rounded-xl hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
          <div className="min-w-0 flex-1"><h1 className="text-sm font-semibold">我的日历</h1><p className="truncate text-xs text-[var(--text-secondary)]">日程会作为时间型记忆参与 AI 回答与规划。</p></div>
          <button onClick={askAi} className="hidden h-9 items-center gap-2 rounded-xl border border-[var(--border)] px-3 text-xs text-[var(--text-secondary)] hover:bg-[var(--surface)] sm:inline-flex"><Bot size={14} />通过 AI 添加</button>
          <button onClick={() => openCreate()} className="inline-flex h-9 items-center gap-2 rounded-xl bg-[var(--accent)] px-4 text-xs font-medium text-[var(--accent-foreground)]"><Plus size={14} />新建日程</button>
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-[1500px] flex-1 gap-5 p-4 sm:p-6 xl:grid-cols-[1fr_340px]">
        <section className="min-w-0 overflow-hidden rounded-3xl border border-[var(--border)] bg-[var(--surface)]">
          <div className="flex flex-col gap-3 border-b border-[var(--border)] p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
            <div className="flex items-center gap-2">
              <button onClick={() => { const today = new Date(); setAnchor(startOfMonth(today)); setSelectedDate(startOfDay(today)) }} className="rounded-xl border border-[var(--border)] px-3 py-2 text-xs">今天</button>
              <button onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1))} aria-label="上个月" className="grid h-9 w-9 place-items-center rounded-xl hover:bg-[var(--surface-raised)]"><ChevronLeft size={16} /></button>
              <button onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1))} aria-label="下个月" className="grid h-9 w-9 place-items-center rounded-xl hover:bg-[var(--surface-raised)]"><ChevronRight size={16} /></button>
              <h2 className="ml-1 text-lg font-semibold">{anchor.getFullYear()} 年 {anchor.getMonth() + 1} 月</h2>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => void load()} disabled={loading} className="grid h-9 w-9 place-items-center rounded-xl text-[var(--text-secondary)] hover:bg-[var(--surface-raised)]"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} /></button>
              <div className="flex rounded-xl border border-[var(--border)] p-1 text-xs">
                <button onClick={() => setView('month')} className={`inline-flex items-center gap-1 rounded-lg px-3 py-1.5 ${view === 'month' ? 'bg-[var(--accent-dim)] text-[var(--accent)]' : 'text-[var(--text-secondary)]'}`}><CalendarDays size={13} />月</button>
                <button onClick={() => setView('agenda')} className={`inline-flex items-center gap-1 rounded-lg px-3 py-1.5 ${view === 'agenda' ? 'bg-[var(--accent-dim)] text-[var(--accent)]' : 'text-[var(--text-secondary)]'}`}><List size={13} />日程</button>
              </div>
            </div>
          </div>
          {error && <div role="alert" className="border-b border-red-500/20 bg-red-500/5 px-5 py-3 text-xs text-red-500">{error}</div>}

          {view === 'month' ? (
            <div>
              <div className="grid grid-cols-7 border-b border-[var(--border)] bg-[var(--surface-raised)]/50">
                {weekdayLabels.map((label) => <div key={label} className="px-2 py-2 text-center text-[11px] text-[var(--text-secondary)]">周{label}</div>)}
              </div>
              <div className="grid grid-cols-7">
                {gridDays.map((day) => {
                  const dayEvents = eventsByDay.get(dateKey(day)) || []
                  const muted = day.getMonth() !== anchor.getMonth()
                  return (
                    <button key={dateKey(day)} onClick={() => setSelectedDate(day)} onDoubleClick={() => openCreate(day)} className={`min-h-24 border-b border-r border-[var(--border)] p-1.5 text-left transition-colors hover:bg-[var(--surface-raised)] sm:min-h-28 sm:p-2 ${sameDay(day, selectedDate) ? 'bg-[var(--accent-dim)]/40' : ''}`}>
                      <span className={`grid h-6 w-6 place-items-center rounded-full text-xs ${sameDay(day, new Date()) ? 'bg-[var(--accent)] font-semibold text-[var(--accent-foreground)]' : muted ? 'text-[var(--text-secondary)]/50' : ''}`}>{day.getDate()}</span>
                      <div className="mt-1 space-y-1">
                        {dayEvents.slice(0, 3).map((event) => <div key={event.occurrence_id} className={`truncate rounded border px-1.5 py-0.5 text-[10px] ${eventTone(event.event_type)}`}>{event.all_day ? '' : new Date(event.local_start_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' '}{event.title}</div>)}
                        {dayEvents.length > 3 && <div className="px-1 text-[10px] text-[var(--text-secondary)]">还有 {dayEvents.length - 3} 项</div>}
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          ) : (
            <div className="p-4 sm:p-5">
              {agendaGroups.map(([day, dayEvents]) => <div key={day} className="mb-6 grid gap-3 sm:grid-cols-[120px_1fr]"><div><div className="text-sm font-semibold">{new Date(`${day}T00:00:00`).toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })}</div><div className="text-xs text-[var(--text-secondary)]">{new Date(`${day}T00:00:00`).toLocaleDateString('zh-CN', { weekday: 'long' })}</div></div><div className="space-y-2">{dayEvents.map((event) => <EventCard key={event.occurrence_id} event={event} onEdit={openEdit} />)}</div></div>)}
              {!loading && agendaGroups.length === 0 && <EmptyCalendar />}
            </div>
          )}
        </section>

        <aside className="space-y-4">
          <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <div className="flex items-center justify-between"><div><h2 className="font-medium">{selectedDate.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })}</h2><p className="text-xs text-[var(--text-secondary)]">{selectedDate.toLocaleDateString('zh-CN', { weekday: 'long' })} · {selectedEvents.length} 项</p></div><button onClick={() => openCreate(selectedDate)} className="grid h-8 w-8 place-items-center rounded-xl bg-[var(--accent-dim)] text-[var(--accent)]"><Plus size={15} /></button></div>
            <div className="mt-4 space-y-2">{selectedEvents.map((event) => <EventCard key={event.occurrence_id} event={event} onEdit={openEdit} />)}{selectedEvents.length === 0 && <div className="rounded-2xl border border-dashed border-[var(--border)] p-6 text-center text-xs text-[var(--text-secondary)]">这一天还没有日程，双击日期或点击加号创建。</div>}</div>
          </section>
          <section className="rounded-3xl border border-[var(--border)] bg-gradient-to-br from-[var(--accent-dim)] to-[var(--surface)] p-5">
            <Sparkles size={20} className="text-[var(--accent)]" /><h3 className="mt-3 text-sm font-medium">日历即时间型记忆</h3><p className="mt-2 text-xs leading-5 text-[var(--text-secondary)]">你可以直接告诉 AI“明天下午三点客户复盘，帮我记录”，确认写入后，后续询问安排时 AI 会依据日历回答。</p><button onClick={askAi} className="mt-4 inline-flex items-center gap-2 text-xs font-medium text-[var(--accent)]"><Bot size={14} />去对话添加日程</button>
          </section>
        </aside>
      </main>

      {editorOpen && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 backdrop-blur-sm sm:items-center sm:p-6" onMouseDown={(event) => { if (event.target === event.currentTarget) setEditorOpen(false) }}>
          <section role="dialog" aria-modal="true" aria-label={editingId ? '编辑日程' : '新建日程'} className="max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-t-3xl border border-[var(--border)] bg-[var(--bg)] p-5 shadow-2xl sm:rounded-3xl sm:p-6">
            <div className="flex items-center justify-between"><div><h2 className="font-semibold">{editingId ? '编辑日程' : '新建日程'}</h2><p className="mt-1 text-xs text-[var(--text-secondary)]">时间按 {timezone} 保存，可由 AI 在对话中读取。</p></div><button onClick={() => setEditorOpen(false)} className="grid h-8 w-8 place-items-center rounded-xl hover:bg-[var(--surface)]"><X size={16} /></button></div>
            <div className="mt-5 space-y-4">
              <input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} placeholder="日程标题" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-3 text-sm outline-none focus:border-[var(--accent)]" />
              <div className="grid grid-cols-2 gap-3"><label className="text-xs text-[var(--text-secondary)]">类型<select value={eventType} onChange={(event) => setEventType(event.target.value as CalendarEventItem['event_type'])} className="mt-1.5 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm text-[var(--text)]">{Object.entries(eventTypeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="text-xs text-[var(--text-secondary)]">日期<input type="date" value={eventDate} onChange={(event) => setEventDate(event.target.value)} className="mt-1.5 w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm text-[var(--text)]" /></label></div>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={allDay} onChange={(event) => setAllDay(event.target.checked)} />全天</label>
              {!allDay && <div className="grid grid-cols-2 gap-3"><label className="text-xs text-[var(--text-secondary)]">开始<input type="time" value={startTime} onChange={(event) => setStartTime(event.target.value)} className="mt-1.5 w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm text-[var(--text)]" /></label><label className="text-xs text-[var(--text-secondary)]">结束<input type="time" value={endTime} onChange={(event) => setEndTime(event.target.value)} className="mt-1.5 w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm text-[var(--text)]" /></label></div>}
              <div className="grid grid-cols-2 gap-3"><label className="text-xs text-[var(--text-secondary)]">重复<select value={recurrence} onChange={(event) => setRecurrence(event.target.value as RecurrenceMode)} className="mt-1.5 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm text-[var(--text)]"><option value="none">不重复</option><option value="daily">每天</option><option value="weekly">每周</option><option value="monthly">每月</option></select></label><label className="text-xs text-[var(--text-secondary)]">提前提醒<select value={reminder} onChange={(event) => setReminder(Number(event.target.value))} className="mt-1.5 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm text-[var(--text)]"><option value={0}>开始时</option><option value={5}>5 分钟</option><option value={15}>15 分钟</option><option value={30}>30 分钟</option><option value={60}>1 小时</option><option value={1440}>1 天</option></select></label></div>
              <label className="relative block"><MapPin size={14} className="absolute left-3 top-3 text-[var(--text-secondary)]" /><input value={location} onChange={(event) => setLocation(event.target.value)} placeholder="地点（可选）" className="w-full rounded-xl border border-[var(--border)] bg-transparent py-2.5 pl-9 pr-3 text-sm" /></label>
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={4} placeholder="备注、准备事项或相关信息" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm" />
            </div>
            <div className="mt-6 flex items-center justify-between gap-3">{editingId ? <button onClick={() => { const event = events.find((item) => item.id === editingId); if (event) void cancel(event) }} className="inline-flex items-center gap-2 rounded-xl border border-red-500/30 px-3 py-2 text-xs text-red-500"><Trash2 size={14} />取消日程</button> : <span />}<button disabled={saving || !title.trim()} onClick={() => void save()} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-5 py-2.5 text-sm font-medium text-[var(--accent-foreground)] disabled:opacity-50">{saving ? <RefreshCw size={14} className="animate-spin" /> : editingId ? <Pencil size={14} /> : <Plus size={14} />}{editingId ? '保存修改' : '创建日程'}</button></div>
          </section>
        </div>
      )}
    </div>
  )
}

function EventCard({ event, onEdit }: { event: CalendarEventItem; onEdit: (event: CalendarEventItem) => void }) {
  return <button onClick={() => onEdit(event)} className={`w-full rounded-2xl border p-3 text-left transition-transform hover:-translate-y-0.5 ${eventTone(event.event_type)}`}><div className="flex items-start justify-between gap-3"><div className="min-w-0"><div className="flex items-center gap-2"><h3 className="truncate text-sm font-medium text-[var(--text)]">{event.title}</h3>{event.source === 'assistant' && <span className="flex-none rounded-full bg-[var(--accent-dim)] px-2 py-0.5 text-[9px] text-[var(--accent)]">AI 记录</span>}</div><div className="mt-1 inline-flex items-center gap-1 text-[11px]"><Clock3 size={11} />{formatEventTime(event)} · {eventTypeLabels[event.event_type]}</div>{event.location && <div className="mt-1 flex items-center gap-1 text-[11px]"><MapPin size={11} />{event.location}</div>}</div><Pencil size={13} className="mt-0.5 flex-none opacity-50" /></div></button>
}

function EmptyCalendar() {
  return <div className="p-12 text-center"><CalendarDays size={30} className="mx-auto text-[var(--text-secondary)]" /><h3 className="mt-3 text-sm font-medium">这个月还没有日程</h3><p className="mt-1 text-xs text-[var(--text-secondary)]">可以手动创建，也可以在对话中让 AI 帮你记录。</p></div>
}
