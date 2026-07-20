import { useEffect, useMemo, useState } from 'react'
import { Activity, Ban, Check, ChevronLeft, Pause, Play, Plus, RefreshCw, TestTube } from 'lucide-react'
import {
  apiAcknowledgeAlertEvent,
  apiAlertRuleAction,
  apiCreateAlertRule,
  apiListAlertEvents,
  apiListAlertRules,
  apiListDatabases,
  apiListProjects,
  apiPreviewScheduledTask,
  apiTestAlertRule,
  type AlertEventItem,
  type AlertRuleItem,
  type DataSourceItem,
  type ProjectItem,
} from '../api/client'
import { useAuthStore } from '../store/auth'

export default function AlertsPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((state) => state.token)!
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  const [rules, setRules] = useState<AlertRuleItem[]>([])
  const [events, setEvents] = useState<AlertEventItem[]>([])
  const [sources, setSources] = useState<DataSourceItem[]>([])
  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [name, setName] = useState('')
  const [question, setQuestion] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [projectId, setProjectId] = useState('')
  const [metricColumn, setMetricColumn] = useState('')
  const [aggregation, setAggregation] = useState<AlertRuleItem['aggregation']>('first')
  const [operator, setOperator] = useState<AlertRuleItem['operator']>('gt')
  const [threshold, setThreshold] = useState('')
  const [severity, setSeverity] = useState<AlertRuleItem['severity']>('warning')
  const [scheduleText, setScheduleText] = useState('每小时')
  const [rrule, setRrule] = useState('')
  const [nextRunAt, setNextRunAt] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [eventFilter, setEventFilter] = useState<'all' | 'unread'>('unread')

  const allowedSources = useMemo(() => {
    if (!projectId) return sources
    const project = projects.find((item) => item.id === projectId)
    const allowed = new Set(project?.data_source_ids ?? [])
    return sources.filter((source) => allowed.has(source.id))
  }, [projectId, projects, sources])
  const visibleEvents = useMemo(
    () => eventFilter === 'unread' ? events.filter((event) => !event.acknowledged_at) : events,
    [eventFilter, events],
  )

  const load = async () => {
    const [nextRules, nextEvents, nextSources, nextProjects] = await Promise.all([
      apiListAlertRules(token), apiListAlertEvents(token), apiListDatabases(token), apiListProjects(token),
    ])
    setRules(nextRules)
    setEvents(nextEvents)
    setSources(nextSources.filter((source) => !source.status || source.status === 'active'))
    setProjects(nextProjects)
  }

  useEffect(() => {
    void load().catch((reason) => setError(String(reason?.message || reason)))
    const timer = window.setInterval(() => void load().catch(() => undefined), 15_000)
    return () => window.clearInterval(timer)
  }, [token])
  useEffect(() => {
    if (sourceId && !allowedSources.some((source) => source.id === sourceId)) setSourceId('')
  }, [allowedSources, sourceId])

  const preview = async () => {
    setError('')
    setNotice('')
    try {
      const result = await apiPreviewScheduledTask(token, scheduleText, timezone)
      setRrule(result.rrule)
      setNextRunAt(result.next_run_at ?? null)
    } catch (reason: any) {
      setError(reason?.message || '无法解析日程')
    }
  }

  const create = async () => {
    if (!name.trim() || !question.trim() || !sourceId || !rrule || threshold.trim() === '') return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await apiCreateAlertRule(token, {
        name: name.trim(), question: question.trim(), data_source_id: sourceId,
        project_id: projectId || null, metric_column: metricColumn.trim() || null,
        aggregation, operator, threshold: Number(threshold), severity, rrule, timezone,
        cooldown_seconds: 3600, enabled: false,
      })
      setName('')
      setQuestion('')
      setMetricColumn('')
      setThreshold('')
      setRrule('')
      setNextRunAt(null)
      setNotice('预警草稿已保存。建议先测试取数结果，再正式启用。')
      await load()
    } catch (reason: any) {
      setError(reason?.message || '创建失败')
    } finally {
      setBusy(false)
    }
  }

  const action = async (ruleId: string, next: 'enable' | 'pause' | 'cancel') => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await apiAlertRuleAction(token, ruleId, next)
      await load()
    } catch (reason: any) {
      setError(reason?.message || '更新失败')
    } finally {
      setBusy(false)
    }
  }

  const test = async (ruleId: string) => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await apiTestAlertRule(token, ruleId)
      const status = String(result.status || 'completed')
      const value = result.value === undefined ? '' : `，当前值 ${String(result.value)}`
      setNotice(`测试完成：${status}${value}`)
      await load()
    } catch (reason: any) {
      setError(reason?.message || '测试失败')
    } finally {
      setBusy(false)
    }
  }

  const acknowledge = async (eventId: string) => {
    setError('')
    try {
      await apiAcknowledgeAlertEvent(token, eventId)
      await load()
    } catch (reason: any) {
      setError(reason?.message || '确认事件失败')
    }
  }

  return <div className="flex h-screen flex-col bg-[var(--bg)] text-[var(--text)]">
    <header className="flex h-14 items-center gap-3 border-b border-[var(--border)] px-6">
      <button onClick={onBack} className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
      <Activity size={17} />
      <div className="flex-1"><h1 className="text-sm font-semibold">主动预警</h1><p className="text-xs text-[var(--text-secondary)]">用自然语言取数，以确定性条件判断；失败会自动重试并通过通知中心告知。</p></div>
      <button disabled={busy} onClick={() => void load()} className="action"><RefreshCw size={13} className={busy ? 'animate-spin' : ''} />刷新</button>
    </header>
    <main className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 gap-6 overflow-auto p-6 xl:grid-cols-[380px_1fr]">
      <section className="h-fit space-y-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
        <h2 className="font-medium">新建数据预警</h2>
        <Field label="名称"><input value={name} onChange={(event) => setName(event.target.value)} className="input" placeholder="例如：销售额异常下降" /></Field>
        <Field label="Project（可选，用于数据源隔离）"><select value={projectId} onChange={(event) => setProjectId(event.target.value)} className="input"><option value="">不关联 Project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></Field>
        <Field label="数据源"><select value={sourceId} onChange={(event) => setSourceId(event.target.value)} className="input"><option value="">选择数据源</option>{allowedSources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</select></Field>
        <Field label="取数问题"><textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} className="input" placeholder="查询最近一小时的订单总额，只返回聚合结果" /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="指标列（可选）"><input value={metricColumn} onChange={(event) => setMetricColumn(event.target.value)} className="input" placeholder="total_amount" /></Field>
          <Field label="聚合"><select value={aggregation} onChange={(event) => setAggregation(event.target.value as AlertRuleItem['aggregation'])} className="input"><option value="first">首个值</option><option value="sum">求和</option><option value="avg">平均</option><option value="min">最小</option><option value="max">最大</option><option value="count">行数</option></select></Field>
          <Field label="判断条件"><select value={operator} onChange={(event) => setOperator(event.target.value as AlertRuleItem['operator'])} className="input"><option value="gt">大于</option><option value="gte">大于等于</option><option value="lt">小于</option><option value="lte">小于等于</option><option value="eq">等于</option><option value="neq">不等于</option><option value="change_pct_gt">涨幅 % 大于</option><option value="change_pct_lt">涨幅 % 小于</option></select></Field>
          <Field label="阈值"><input type="number" value={threshold} onChange={(event) => setThreshold(event.target.value)} className="input" /></Field>
          <Field label="级别"><select value={severity} onChange={(event) => setSeverity(event.target.value as AlertRuleItem['severity'])} className="input"><option value="info">提示</option><option value="warning">警告</option><option value="critical">严重</option></select></Field>
          <Field label="执行周期"><input value={scheduleText} onChange={(event) => { setScheduleText(event.target.value); setRrule('') }} className="input" placeholder="每小时" /></Field>
        </div>
        {!rrule ? <button onClick={() => void preview()} className="rounded-xl border border-[var(--border)] px-3 py-2 text-sm">预览日程</button> : <div className="rounded-xl bg-[var(--bg)] p-3 text-xs"><div className="font-mono">{rrule}</div><div className="mt-1 text-[var(--text-secondary)]">下次：{nextRunAt ? new Date(nextRunAt).toLocaleString() : '—'}</div></div>}
        <button disabled={busy || !rrule || !sourceId || threshold === ''} onClick={() => void create()} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-50"><Plus size={14} />保存为草稿</button>
        {(error || notice) && <div role="status" aria-live="polite" className={`rounded-xl border bg-[var(--bg)] p-3 text-xs ${error ? 'border-red-500/30 text-red-500' : 'border-emerald-500/30 text-emerald-500'}`}>{error || notice}</div>}
      </section>
      <div className="space-y-6">
        <section className="space-y-3"><h2 className="font-medium">规则</h2>{rules.length === 0 ? <Empty text="暂无预警规则" /> : rules.map((rule) => <article key={rule.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <div className="flex items-start justify-between gap-3"><div><h3 className="font-medium">{rule.name}</h3><p className="mt-1 text-sm text-[var(--text-secondary)]">{rule.question}</p></div><span className="rounded-full border border-[var(--border)] px-2 py-1 text-xs">{rule.status} · {rule.last_state}</span></div>
          <div className="mt-3 grid gap-1 text-xs text-[var(--text-secondary)]"><span>{rule.aggregation}({rule.metric_column || '首个数值'}) {rule.operator} {rule.threshold} · {rule.severity}</span><span>当前值：{rule.last_value ?? '—'} · 下次：{rule.next_run_at ? new Date(rule.next_run_at).toLocaleString() : '—'}</span>{rule.last_error && <span className="rounded-lg bg-red-500/10 px-2 py-1.5 text-red-500">上次检查失败：{rule.last_error}。系统将在“下次”时间自动重试。</span>}</div>
          <div className="mt-4 flex flex-wrap gap-2"><button disabled={busy} onClick={() => void test(rule.id)} className="action"><TestTube size={13} />测试</button>{rule.status !== 'active' && rule.status !== 'cancelled' && <button onClick={() => void action(rule.id, 'enable')} className="action"><Play size={13} />启用</button>}{rule.status === 'active' && <button onClick={() => void action(rule.id, 'pause')} className="action"><Pause size={13} />暂停</button>}{rule.status !== 'cancelled' && <button onClick={() => void action(rule.id, 'cancel')} className="action text-red-500"><Ban size={13} />取消</button>}</div>
        </article>)}</section>
        <section className="space-y-3"><div className="flex items-center justify-between gap-3"><h2 className="font-medium">预警事件</h2><div className="flex rounded-lg border border-[var(--border)] p-0.5 text-xs"><button onClick={() => setEventFilter('unread')} className={`rounded-md px-2 py-1 ${eventFilter === 'unread' ? 'bg-[var(--surface)] text-[var(--text)]' : 'text-[var(--text-secondary)]'}`}>待确认 {events.filter((event) => !event.acknowledged_at).length}</button><button onClick={() => setEventFilter('all')} className={`rounded-md px-2 py-1 ${eventFilter === 'all' ? 'bg-[var(--surface)] text-[var(--text)]' : 'text-[var(--text-secondary)]'}`}>全部</button></div></div>{visibleEvents.length === 0 ? <Empty text={eventFilter === 'unread' ? '没有待确认预警' : '暂无触发或恢复事件'} /> : visibleEvents.map((event) => <article key={event.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-start justify-between gap-3"><div><div className="text-sm font-medium">{event.severity} · {event.state}</div><p className="mt-1 text-sm text-[var(--text-secondary)]">{event.summary}</p><div className="mt-2 text-xs text-[var(--text-secondary)]">{event.created_at ? new Date(event.created_at).toLocaleString() : ''}</div></div>{event.acknowledged_at ? <span className="inline-flex items-center gap-1 text-xs text-emerald-500"><Check size={12} />已确认</span> : <button disabled={busy} onClick={() => void acknowledge(event.id)} className="action"><Check size={13} />确认</button>}</div></article>)}</section>
      </div>
    </main>
  </div>
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-xs text-[var(--text-secondary)]">{label}<div className="mt-1 [&_.input]:w-full [&_.input]:rounded-xl [&_.input]:border [&_.input]:border-[var(--border)] [&_.input]:bg-transparent [&_.input]:px-3 [&_.input]:py-2 [&_.input]:text-sm [&_.input]:text-[var(--text)]">{children}</div></label>
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-2xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--text-secondary)]">{text}</div>
}
