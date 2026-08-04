import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import {
  BarChart3,
  BarChartBig,
  Ban,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  CircleAlert,
  Database,
  LoaderCircle,
  Pause,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  Zap,
} from 'lucide-react'
import DataTableChart, { type ChartConfig } from '../components/DataTableChart'
import { createDefaultScheduleWindow, ScheduleTimePicker, type ScheduleWindowValue } from '../components/ScheduleTimePicker'
import {
  apiCreateEnterpriseReport,
  apiGetEnterpriseReport,
  apiListDatabases,
  apiListEnterpriseReports,
  apiListEnterpriseReportTemplates,
  apiListProjects,
  apiPreviewScheduledTaskRule,
  apiRunScheduledTask,
  apiScheduledTaskAction,
  type DataSourceItem,
  type EnterpriseReportArtifact,
  type EnterpriseReportDetail,
  type EnterpriseReportItem,
  type EnterpriseReportTemplate,
  type EnterpriseReportType,
  type ProjectItem,
} from '../api/client'
import { useAuthStore } from '../store/auth'
import { DEFAULT_TIMEZONE } from '../utils/timezone'

const REPORT_LABELS: Record<EnterpriseReportType, string> = {
  data_insight: '数据洞察',
  monthly_report: '经营月报',
  management_brief: '经营简报',
}

export default function ReportsPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((state) => state.token)!
  const [searchParams] = useSearchParams()
  const requestedType = searchParams.get('type') as EnterpriseReportType | null
  const [templates, setTemplates] = useState<EnterpriseReportTemplate[]>([])
  const [reports, setReports] = useState<EnterpriseReportItem[]>([])
  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [dataSources, setDataSources] = useState<DataSourceItem[]>([])
  const [reportType, setReportType] = useState<EnterpriseReportType>(
    requestedType && REPORT_LABELS[requestedType] ? requestedType : 'data_insight',
  )
  const [title, setTitle] = useState('')
  const [objective, setObjective] = useState('')
  const [audience, setAudience] = useState('经营管理团队')
  const [projectId, setProjectId] = useState('')
  const [sourceIds, setSourceIds] = useState<string[]>([])
  const [includeKnowledge, setIncludeKnowledge] = useState(false)
  const [schedule, setSchedule] = useState<ScheduleWindowValue>(() => createDefaultScheduleWindow(DEFAULT_TIMEZONE))
  const [upcomingTimes, setUpcomingTimes] = useState<string[]>([])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [details, setDetails] = useState<Record<string, EnterpriseReportDetail>>({})
  const [busyId, setBusyId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    const [nextTemplates, nextReports, nextProjects, nextSources] = await Promise.all([
      apiListEnterpriseReportTemplates(token),
      apiListEnterpriseReports(token),
      apiListProjects(token),
      apiListDatabases(token),
    ])
    setTemplates(nextTemplates)
    setReports(nextReports)
    setProjects(nextProjects)
    setDataSources(nextSources.filter((source) => !source.status || source.status === 'active'))
  }, [token])

  useEffect(() => {
    void load().catch((reason) => setError(reason instanceof Error ? reason.message : '读取经营报告失败'))
  }, [load])

  useEffect(() => {
    const template = templates.find((item) => item.id === reportType)
    if (!template) return
    setTitle((current) => current || template.title)
    setObjective((current) => current || template.default_objective)
    setIncludeKnowledge(template.knowledge_required)
    setSchedule((current) => ({ ...current, rrule: template.default_rrule }))
    setUpcomingTimes([])
  }, [reportType, templates])

  useEffect(() => {
    if (!expandedId) return
    const timer = window.setInterval(() => {
      void apiGetEnterpriseReport(token, expandedId).then((detail) => {
        setDetails((current) => ({ ...current, [expandedId]: detail }))
      }).catch(() => undefined)
    }, 10_000)
    return () => window.clearInterval(timer)
  }, [expandedId, token])

  const selectedTemplate = templates.find((item) => item.id === reportType)
  const selectedProject = projects.find((item) => item.id === projectId)
  const availableSources = useMemo(() => {
    const allowed = new Set(selectedProject?.data_source_ids || [])
    return dataSources.filter((source) => allowed.has(source.id))
  }, [dataSources, selectedProject])

  const selectProject = (nextProjectId: string) => {
    setProjectId(nextProjectId)
    const project = projects.find((item) => item.id === nextProjectId)
    const active = new Set(dataSources.map((item) => item.id))
    setSourceIds((project?.data_source_ids || []).filter((id) => active.has(id)))
  }

  const changeType = (nextType: EnterpriseReportType) => {
    const template = templates.find((item) => item.id === nextType)
    setReportType(nextType)
    setTitle(template?.title || REPORT_LABELS[nextType])
    setObjective(template?.default_objective || '')
  }

  const toggleSource = (sourceId: string) => {
    setSourceIds((current) => current.includes(sourceId)
      ? current.filter((item) => item !== sourceId)
      : [...current, sourceId])
  }

  const preview = async () => {
    setPreviewing(true)
    setError('')
    try {
      const result = await apiPreviewScheduledTaskRule(token, {
        rrule: schedule.rrule,
        timezone: schedule.timezone,
        starts_at: schedule.startsAt || null,
        ends_at: schedule.endsAt,
        count: 5,
      })
      setUpcomingTimes(result.next_run_times)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法预览报告时间')
    } finally {
      setPreviewing(false)
    }
  }

  const create = async () => {
    if (!title.trim() || !projectId || !sourceIds.length || !schedule.rrule) return
    setSaving(true)
    setError('')
    try {
      await apiCreateEnterpriseReport(token, {
        report_type: reportType,
        title: title.trim(),
        objective: objective.trim(),
        audience: audience.trim(),
        project_id: projectId,
        data_source_ids: sourceIds,
        include_knowledge: includeKnowledge,
        rrule: schedule.rrule,
        timezone: schedule.timezone,
        starts_at: schedule.startsAt || null,
        ends_at: schedule.endsAt,
        enabled: false,
      })
      setNotice('报告草稿已保存。建议先立即运行，核对证据链后再启用周期。')
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '创建企业报告失败')
    } finally {
      setSaving(false)
    }
  }

  const action = async (reportId: string, next: 'enable' | 'pause' | 'cancel') => {
    setBusyId(reportId)
    setError('')
    try {
      await apiScheduledTaskAction(token, reportId, next)
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '更新报告失败')
    } finally {
      setBusyId(null)
    }
  }

  const runNow = async (reportId: string) => {
    setBusyId(reportId)
    setError('')
    try {
      await apiRunScheduledTask(token, reportId)
      const detail = await apiGetEnterpriseReport(token, reportId)
      setDetails((current) => ({ ...current, [reportId]: detail }))
      setExpandedId(reportId)
      setNotice('报告已进入 Responses 后台队列，可离开页面；结果会持久化到运行记录。')
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '报告入队失败')
    } finally {
      setBusyId(null)
    }
  }

  const toggleDetail = async (reportId: string) => {
    if (expandedId === reportId) {
      setExpandedId(null)
      return
    }
    setExpandedId(reportId)
    try {
      const detail = await apiGetEnterpriseReport(token, reportId)
      setDetails((current) => ({ ...current, [reportId]: detail }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取报告详情失败')
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-[var(--bg)] text-[var(--text)]">
      <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--bg)]/95 backdrop-blur">
        <div className="mx-auto flex h-16 w-full max-w-7xl items-center gap-3 px-4 sm:px-6">
          <button onClick={onBack} aria-label="返回工作台" className="grid h-9 w-9 place-items-center rounded-lg hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
          <div className="min-w-0 flex-1"><h1 className="text-sm font-semibold">经营报告</h1><p className="truncate text-xs text-[var(--text-secondary)]">数据、知识、图表与查询依据在同一条可恢复 Responses 链路中交付。</p></div>
          <button onClick={() => void load()} className="inline-flex h-9 items-center gap-2 rounded-lg border border-[var(--border)] px-3 text-xs"><RefreshCw size={14} />刷新</button>
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-7xl flex-1 gap-6 p-4 sm:p-6 xl:grid-cols-[420px_minmax(0,1fr)]">
        <section className="h-fit space-y-4 border-b border-[var(--border)] pb-6 xl:sticky xl:top-20 xl:border-b-0 xl:border-r xl:pb-0 xl:pr-6">
          <div><h2 className="font-medium">新建报告</h2><p className="mt-1 text-xs text-[var(--text-secondary)]">先试运行并核验证据，再开启周期交付。</p></div>
          <div className="grid grid-cols-3 gap-2">
            {templates.map((template) => <button key={template.id} onClick={() => changeType(template.id)} className={`min-h-16 border px-2 py-2 text-xs ${reportType === template.id ? 'border-[var(--accent)] bg-[var(--accent-dim)] text-[var(--accent)]' : 'border-[var(--border)]'}`}>{template.title}</button>)}
          </div>
          {selectedTemplate && <p className="text-xs leading-5 text-[var(--text-secondary)]">{selectedTemplate.description}</p>}
          <label className="block text-xs text-[var(--text-secondary)]">报告名称<input value={title} onChange={(event) => setTitle(event.target.value)} className="mt-1 w-full border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /></label>
          <label className="block text-xs text-[var(--text-secondary)]">分析目标<textarea value={objective} onChange={(event) => setObjective(event.target.value)} rows={4} className="mt-1 w-full border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /></label>
          <label className="block text-xs text-[var(--text-secondary)]">阅读对象<input value={audience} onChange={(event) => setAudience(event.target.value)} className="mt-1 w-full border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /></label>
          <label className="block text-xs text-[var(--text-secondary)]">业务 Project<select value={projectId} onChange={(event) => selectProject(event.target.value)} className="mt-1 w-full border border-[var(--border)] bg-transparent px-3 py-2 text-sm"><option value="">请选择</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
          <fieldset className="border border-[var(--border)] p-3"><legend className="px-1 text-xs text-[var(--text-secondary)]">授权数据源</legend>{projectId && availableSources.length ? <div className="space-y-2">{availableSources.map((source) => <label key={source.id} className="flex items-center gap-2 text-xs"><input type="checkbox" checked={sourceIds.includes(source.id)} onChange={() => toggleSource(source.id)} /><Database size={13} /><span>{source.name}</span></label>)}</div> : <p className="text-xs text-[var(--text-secondary)]">所选 Project 尚未绑定可用数据源。</p>}</fieldset>
          <label className="flex items-center justify-between gap-3 border border-[var(--border)] p-3 text-xs"><span><span className="block font-medium text-[var(--text)]">融合企业知识</span><span className="mt-0.5 block text-[var(--text-secondary)]">检索已发布知识并保留引用</span></span><input type="checkbox" checked={includeKnowledge} disabled={selectedTemplate?.knowledge_required} onChange={(event) => setIncludeKnowledge(event.target.checked)} /></label>
          <ScheduleTimePicker value={schedule} upcomingTimes={upcomingTimes} previewing={previewing} onChange={(value) => { setSchedule(value); setUpcomingTimes([]) }} onPreview={() => void preview()} />
          <button disabled={saving || !projectId || !sourceIds.length || !schedule.rrule} onClick={() => void create()} className="inline-flex w-full items-center justify-center gap-2 bg-[var(--accent)] px-4 py-2.5 text-sm text-[var(--accent-foreground)] disabled:opacity-40">{saving ? <LoaderCircle size={15} className="animate-spin" /> : <Plus size={15} />}保存报告草稿</button>
          {(error || notice) && <div role={error ? 'alert' : 'status'} className={`border p-3 text-xs ${error ? 'border-red-500/40 text-red-500' : 'border-emerald-500/40 text-emerald-500'}`}>{error || notice}</div>}
        </section>

        <section className="min-w-0 space-y-4">
          <div className="flex items-end justify-between"><div><h2 className="font-medium">报告运行</h2><p className="mt-1 text-xs text-[var(--text-secondary)]">只有 SQL、校验、引用和图表齐备时才标记为已验证。</p></div><span className="text-xs text-[var(--text-secondary)]">{reports.length} 个</span></div>
          {reports.length === 0 && <div className="border border-dashed border-[var(--border)] p-12 text-center text-sm text-[var(--text-secondary)]"><BarChartBig className="mx-auto mb-3" size={28} />还没有经营报告</div>}
          {reports.map((report) => {
            const detail = details[report.id]
            return <article key={report.id} className="border border-[var(--border)] bg-[var(--surface)]">
              <div className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><div className="flex items-center gap-2"><BarChart3 size={16} className="text-[var(--accent)]" /><h3 className="font-medium">{report.title}</h3></div><p className="mt-1 text-xs text-[var(--text-secondary)]">{REPORT_LABELS[report.report_type]} · {report.task_config.audience}</p></div><span className="border border-[var(--border)] px-2 py-1 text-xs">{statusLabel(report.status)}</span></div>
                <div className="mt-4 grid gap-2 text-xs text-[var(--text-secondary)] sm:grid-cols-2"><span>数据源 {report.task_config.data_sources.map((item) => item.name).join('、')}</span><span>{report.task_config.include_knowledge ? '数据 + 企业知识' : '数据证据'}</span><span>下次 {report.next_run_at ? new Date(report.next_run_at).toLocaleString() : '未启用'}</span><span>{report.rrule}</span></div>
                <div className="mt-4 flex flex-wrap gap-2"><ActionButton disabled={busyId === report.id || report.status === 'cancelled'} onClick={() => void runNow(report.id)} icon={busyId === report.id ? <LoaderCircle size={13} className="animate-spin" /> : <Zap size={13} />} label="立即运行" primary />{report.status !== 'active' && report.status !== 'cancelled' && <ActionButton disabled={busyId === report.id} onClick={() => void action(report.id, 'enable')} icon={<Play size={13} />} label="启用" />}{report.status === 'active' && <ActionButton disabled={busyId === report.id} onClick={() => void action(report.id, 'pause')} icon={<Pause size={13} />} label="暂停" />}{report.status !== 'cancelled' && <ActionButton disabled={busyId === report.id} onClick={() => void action(report.id, 'cancel')} icon={<Ban size={13} />} label="取消" danger />}<ActionButton onClick={() => void toggleDetail(report.id)} icon={<RefreshCw size={13} />} label="运行与证据" trailing={<ChevronDown size={13} className={expandedId === report.id ? 'rotate-180' : ''} />} /></div>
              </div>
              {expandedId === report.id && <ReportRuns detail={detail} />}
            </article>
          })}
        </section>
      </main>
    </div>
  )
}

export function ReportRuns({ detail }: { detail?: EnterpriseReportDetail }) {
  if (!detail) return <div className="border-t border-[var(--border)] p-5 text-xs text-[var(--text-secondary)]">正在加载运行记录…</div>
  if (!detail.runs.length) return <div className="border-t border-[var(--border)] p-5 text-xs text-[var(--text-secondary)]">还没有运行记录。</div>
  return <div className="border-t border-[var(--border)]">{detail.runs.map((run) => {
    const artifact = run.output_metadata && 'verification' in run.output_metadata
      ? run.output_metadata as EnterpriseReportArtifact
      : null
    return <section key={run.id} className="border-b border-[var(--border)] p-5 last:border-b-0">
      <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2">{artifact?.status === 'verified' ? <CheckCircle2 size={15} className="text-emerald-500" /> : <CircleAlert size={15} className="text-amber-500" />}<span className="text-sm font-medium">{artifact?.status === 'verified' ? '证据已验证' : statusLabel(run.status)}</span></div><span className="text-xs text-[var(--text-secondary)]">{run.scheduled_for ? new Date(run.scheduled_for).toLocaleString() : ''}</span></div>
      {run.error && <p className="mt-3 text-xs text-red-500">{run.error}</p>}
      {artifact && <div className="mt-4 space-y-5">
        <div className="grid grid-cols-3 border border-[var(--border)] text-center text-xs"><EvidenceState label="数据校验" passed={artifact.verification.data_verified} /><EvidenceState label="知识引用" passed={artifact.verification.knowledge_verified} /><EvidenceState label="图表" passed={artifact.verification.chart_verified} /></div>
        <div className="prose prose-sm max-w-none text-[var(--text)] dark:prose-invert"><ReactMarkdown>{artifact.content}</ReactMarkdown></div>
        {artifact.charts.map((chart, index) => <DataTableChart key={`${run.id}-chart-${index}`} rows={chart.rows} config={chart.config as unknown as ChartConfig} sql={artifact.data_evidence[index]?.sql} />)}
        {artifact.data_evidence.map((evidence, index) => <details key={`${run.id}-data-${index}`} className="border border-[var(--border)] p-3"><summary className="cursor-pointer text-xs font-medium"><Database className="mr-1 inline" size={13} />数据证据 {index + 1} · {evidence.row_count} 行 · {evidence.verification_status}</summary><pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap bg-[var(--bg)] p-3 text-xs">{evidence.sql || '未生成 SQL'}</pre></details>)}
        {artifact.knowledge_citations.length > 0 && <details className="border border-[var(--border)] p-3"><summary className="cursor-pointer text-xs font-medium"><ShieldCheck className="mr-1 inline" size={13} />知识引用 {artifact.knowledge_citations.length}</summary><pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap bg-[var(--bg)] p-3 text-xs">{JSON.stringify(artifact.knowledge_citations, null, 2)}</pre></details>}
      </div>}
      {!artifact && run.output && <p className="mt-3 line-clamp-5 whitespace-pre-wrap text-xs text-[var(--text-secondary)]">{run.output}</p>}
    </section>
  })}</div>
}

function EvidenceState({ label, passed }: { label: string; passed: boolean }) {
  return <div className="border-r border-[var(--border)] p-3 last:border-r-0"><span className={passed ? 'text-emerald-500' : 'text-amber-500'}>{passed ? '通过' : '需复核'}</span><span className="mt-1 block text-[var(--text-secondary)]">{label}</span></div>
}

function ActionButton({ disabled, onClick, icon, label, trailing, primary, danger }: { disabled?: boolean; onClick: () => void; icon: React.ReactNode; label: string; trailing?: React.ReactNode; primary?: boolean; danger?: boolean }) {
  return <button disabled={disabled} onClick={onClick} className={`inline-flex items-center gap-1 border px-3 py-1.5 text-xs disabled:opacity-40 ${primary ? 'border-[var(--accent)] bg-[var(--accent)] text-[var(--accent-foreground)]' : danger ? 'border-red-500/40 text-red-500' : 'border-[var(--border)]'}`}>{icon}{label}{trailing}</button>
}

function statusLabel(status: string) {
  return ({ active: '运行中', draft: '草稿', paused: '已暂停', cancelled: '已取消', queued: '排队中', succeeded: '已完成', incomplete: '需复核', failed: '失败', requires_action: '等待确认' } as Record<string, string>)[status] || status
}
