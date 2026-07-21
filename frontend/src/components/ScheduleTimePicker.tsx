import { useMemo, useState } from 'react'
import { CalendarDays, Check, ChevronDown, Clock3, X } from 'lucide-react'

export type ScheduleFrequency = 'minute' | 'hour' | 'day' | 'week' | 'month'

export interface ScheduleEditorState {
  frequency: ScheduleFrequency
  interval: number
  minute: number
  hour: number
  weekdays: string[]
  monthDay: number
}

export interface ScheduleWindowValue {
  rrule: string
  timezone: string
  startsAt: string
  endsAt: string | null
}

const WEEKDAYS = [
  ['MO', '一'], ['TU', '二'], ['WE', '三'], ['TH', '四'],
  ['FR', '五'], ['SA', '六'], ['SU', '日'],
] as const

const COMMON_TIMEZONES = [
  'Asia/Shanghai', 'Asia/Hong_Kong', 'Asia/Tokyo', 'Asia/Singapore',
  'Europe/London', 'Europe/Paris', 'America/New_York', 'America/Los_Angeles', 'UTC',
]

export const DEFAULT_SCHEDULE_EDITOR: ScheduleEditorState = {
  frequency: 'day',
  interval: 1,
  minute: 0,
  hour: 9,
  weekdays: ['MO', 'TU', 'WE', 'TH', 'FR'],
  monthDay: 1,
}

export function buildScheduleRRule(editor: ScheduleEditorState): string {
  const interval = clamp(editor.interval, 1, 999)
  const minute = clamp(editor.minute, 0, 59)
  const hour = clamp(editor.hour, 0, 23)
  if (editor.frequency === 'minute') return `FREQ=MINUTELY;INTERVAL=${interval};BYSECOND=0`
  if (editor.frequency === 'hour') return `FREQ=HOURLY;INTERVAL=${interval};BYMINUTE=${minute};BYSECOND=0`
  if (editor.frequency === 'week') {
    const days = editor.weekdays.length > 0 ? editor.weekdays.join(',') : 'MO'
    return `FREQ=WEEKLY;INTERVAL=${interval};BYDAY=${days};BYHOUR=${hour};BYMINUTE=${minute};BYSECOND=0`
  }
  if (editor.frequency === 'month') {
    return `FREQ=MONTHLY;INTERVAL=${interval};BYMONTHDAY=${clamp(editor.monthDay, 1, 31)};BYHOUR=${hour};BYMINUTE=${minute};BYSECOND=0`
  }
  return `FREQ=DAILY;INTERVAL=${interval};BYHOUR=${hour};BYMINUTE=${minute};BYSECOND=0`
}

export function createDefaultScheduleWindow(timezone: string): ScheduleWindowValue {
  const start = new Date()
  start.setSeconds(0, 0)
  start.setMinutes(start.getMinutes() + 1)
  const end = new Date(start)
  end.setFullYear(end.getFullYear() + 1)
  return {
    rrule: buildScheduleRRule(DEFAULT_SCHEDULE_EDITOR),
    timezone,
    startsAt: toLocalDateTimeInput(start),
    endsAt: toLocalDateTimeInput(end),
  }
}

export function ScheduleTimePicker({
  value,
  upcomingTimes,
  previewing,
  onChange,
  onPreview,
}: {
  value: ScheduleWindowValue
  upcomingTimes: string[]
  previewing: boolean
  onChange: (value: ScheduleWindowValue) => void
  onPreview: () => void
}) {
  const [open, setOpen] = useState(false)
  const [editor, setEditor] = useState<ScheduleEditorState>(DEFAULT_SCHEDULE_EDITOR)
  const timezones = useMemo(() => {
    const values = [value.timezone, ...COMMON_TIMEZONES].filter(Boolean)
    return [...new Set(values)]
  }, [value.timezone])

  const updateEditor = (patch: Partial<ScheduleEditorState>) => {
    const next = { ...editor, ...patch }
    setEditor(next)
    onChange({ ...value, rrule: buildScheduleRRule(next) })
  }

  return (
    <div className="space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--bg)] p-4">
      <div>
        <h3 className="text-sm font-medium">定时参数</h3>
        <p className="mt-1 text-[11px] text-[var(--text-secondary)]">设置任务有效期、执行规则和所在时区。</p>
      </div>

      <div>
        <label className="text-xs text-[var(--text-secondary)]">起止时间</label>
        <div className="mt-1 grid items-center gap-2 sm:grid-cols-[1fr_auto_1fr]">
          <DateTimeField value={value.startsAt} label="开始时间" onChange={(startsAt) => onChange({ ...value, startsAt })} />
          <span className="hidden text-center text-[var(--text-secondary)] sm:block">→</span>
          {value.endsAt === null ? (
            <button type="button" onClick={() => {
              const end = new Date(value.startsAt || Date.now())
              end.setFullYear(end.getFullYear() + 1)
              onChange({ ...value, endsAt: toLocalDateTimeInput(end) })
            }} className="h-10 rounded-xl border border-dashed border-[var(--border)] text-xs text-[var(--text-secondary)] hover:text-[var(--text)]">
              + 设置结束时间
            </button>
          ) : (
            <div className="relative">
              <DateTimeField value={value.endsAt} label="结束时间" onChange={(endsAt) => onChange({ ...value, endsAt })} />
              <button type="button" aria-label="取消结束时间" onClick={() => onChange({ ...value, endsAt: null })} className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]"><X size={13} /></button>
            </div>
          )}
        </div>
      </div>

      <div className="relative">
        <label className="text-xs text-[var(--text-secondary)]">执行规则</label>
        <div className="mt-1 flex">
          <input aria-label="RRULE 执行规则" value={value.rrule} onChange={(event) => onChange({ ...value, rrule: event.target.value })} className="min-w-0 flex-1 rounded-l-xl border border-r-0 border-[var(--border)] bg-transparent px-3 py-2 font-mono text-xs outline-none focus:border-[var(--accent)]" />
          <button type="button" aria-expanded={open} onClick={() => setOpen((current) => !current)} className="inline-flex shrink-0 items-center gap-1 rounded-r-xl border border-[var(--border)] px-3 text-xs text-[var(--accent)] hover:bg-[var(--accent-dim)]">
            执行时间<ChevronDown size={13} className={open ? 'rotate-180' : ''} />
          </button>
        </div>

        {open && (
          <div className="absolute left-0 right-0 z-30 mt-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-2xl">
            <div role="tablist" aria-label="执行周期" className="flex border-b border-[var(--border)]">
              {([
                ['minute', '分钟'], ['hour', '小时'], ['day', '天'], ['week', '周'], ['month', '月'],
              ] as const).map(([frequency, label]) => (
                <button key={frequency} role="tab" aria-selected={editor.frequency === frequency} type="button" onClick={() => updateEditor({ frequency })} className={`relative px-3 pb-2 text-xs ${editor.frequency === frequency ? 'text-[var(--accent)]' : 'text-[var(--text-secondary)]'}`}>
                  {label}{editor.frequency === frequency && <span className="absolute inset-x-2 bottom-0 h-0.5 bg-[var(--accent)]" />}
                </button>
              ))}
            </div>

            <div className="mt-4 space-y-4 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span>每隔</span><NumberField value={editor.interval} min={1} max={999} onChange={(interval) => updateEditor({ interval })} />
                <span>{frequencyUnit(editor.frequency)}执行</span>
              </div>

              {editor.frequency === 'hour' && <div className="flex flex-wrap items-center gap-2"><span>在第</span><NumberField value={editor.minute} min={0} max={59} onChange={(minute) => updateEditor({ minute })} /><span>分钟运行</span></div>}
              {['day', 'week', 'month'].includes(editor.frequency) && <div className="flex flex-wrap items-center gap-2"><span>执行时间</span><NumberField value={editor.hour} min={0} max={23} onChange={(hour) => updateEditor({ hour })} /><span>时</span><NumberField value={editor.minute} min={0} max={59} onChange={(minute) => updateEditor({ minute })} /><span>分</span></div>}
              {editor.frequency === 'week' && (
                <div><div className="mb-2 text-[var(--text-secondary)]">选择星期</div><div className="flex flex-wrap gap-2">{WEEKDAYS.map(([key, label]) => {
                  const selected = editor.weekdays.includes(key)
                  return <button type="button" key={key} aria-pressed={selected} onClick={() => {
                    const weekdays = selected ? editor.weekdays.filter((item) => item !== key) : [...editor.weekdays, key]
                    updateEditor({ weekdays })
                  }} className={`grid h-8 w-8 place-items-center rounded-full border ${selected ? 'border-[var(--accent)] bg-[var(--accent-dim)] text-[var(--accent)]' : 'border-[var(--border)] text-[var(--text-secondary)]'}`}>{label}</button>
                })}</div></div>
              )}
              {editor.frequency === 'month' && <div className="flex flex-wrap items-center gap-2"><span>每月第</span><NumberField value={editor.monthDay} min={1} max={31} onChange={(monthDay) => updateEditor({ monthDay })} /><span>天执行</span></div>}
            </div>

            <div className="mt-4 flex items-center justify-between border-t border-[var(--border)] pt-3">
              <span className="truncate pr-3 font-mono text-[10px] text-[var(--text-secondary)]">{value.rrule}</span>
              <button type="button" onClick={() => setOpen(false)} className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs text-[var(--accent-foreground)]"><Check size={12} />完成</button>
            </div>
          </div>
        )}
      </div>

      <label className="block text-xs text-[var(--text-secondary)]">时区
        <select value={value.timezone} onChange={(event) => onChange({ ...value, timezone: event.target.value })} className="mt-1 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]">
          {timezones.map((timezone) => <option key={timezone} value={timezone}>{timezone}</option>)}
        </select>
      </label>

      <div className="flex items-center justify-between gap-3">
        <div className="inline-flex items-center gap-1.5 text-xs text-[var(--text-secondary)]"><Clock3 size={13} />接下来五次执行时间</div>
        <button type="button" disabled={previewing || !value.rrule.trim()} onClick={onPreview} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--surface)] disabled:opacity-50">{previewing ? '计算中…' : '刷新预览'}</button>
      </div>
      {upcomingTimes.length > 0 ? (
        <ol className="grid gap-2 sm:grid-cols-2">
          {upcomingTimes.map((time, index) => <li key={time} className="flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs"><span className="grid h-5 w-5 place-items-center rounded-full bg-[var(--accent-dim)] text-[10px] text-[var(--accent)]">{index + 1}</span>{formatInTimezone(time, value.timezone)}</li>)}
        </ol>
      ) : <div className="rounded-xl border border-dashed border-[var(--border)] px-3 py-4 text-center text-xs text-[var(--text-secondary)]">设置完成后点击“刷新预览”</div>}
    </div>
  )
}

function DateTimeField({ value, label, onChange }: { value: string; label: string; onChange: (value: string) => void }) {
  return <div className="relative"><CalendarDays size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" /><input aria-label={label} type="datetime-local" value={value} onChange={(event) => onChange(event.target.value)} className="h-10 w-full rounded-xl border border-[var(--border)] bg-transparent py-2 pl-9 pr-8 text-xs" /></div>
}

function NumberField({ value, min, max, onChange }: { value: number; min: number; max: number; onChange: (value: number) => void }) {
  return <span className="inline-flex h-8 overflow-hidden rounded-lg border border-[var(--border)]"><button type="button" aria-label="减少" onClick={() => onChange(clamp(value - 1, min, max))} className="w-7 text-[var(--text-secondary)] hover:bg-[var(--bg)]">−</button><input aria-label="数值" type="number" min={min} max={max} value={value} onChange={(event) => onChange(clamp(Number(event.target.value), min, max))} className="w-11 border-x border-[var(--border)] bg-transparent text-center outline-none" /><button type="button" aria-label="增加" onClick={() => onChange(clamp(value + 1, min, max))} className="w-7 text-[var(--text-secondary)] hover:bg-[var(--bg)]">＋</button></span>
}

function frequencyUnit(frequency: ScheduleFrequency) {
  return ({ minute: '分钟', hour: '小时', day: '天', week: '周', month: '个月' } as const)[frequency]
}

function toLocalDateTimeInput(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function formatInTimezone(value: string, timezone: string): string {
  try {
    return new Intl.DateTimeFormat('zh-CN', { timeZone: timezone, month: '2-digit', day: '2-digit', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
  } catch {
    return new Date(value).toLocaleString()
  }
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min
  return Math.min(max, Math.max(min, Math.trunc(value)))
}
