import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Ban,
  BellRing,
  BookOpen,
  Bot,
  CheckCircle2,
  ChevronLeft,
  CircleGauge,
  Clock3,
  Database,
  FolderKanban,
  BarChartBig,
  Pause,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Target,
  Workflow,
  CalendarDays,
} from 'lucide-react'
import { useAuthStore } from '../store/auth'
import { useChatPreferences } from '../store/chatPreferences'
import { WorkbenchActionCenter } from '../components/WorkbenchActionCenter'
import { WorkbenchTodayPulse } from '../components/WorkbenchTodayPulse'
import {
  apiCreateAssistantProfile,
  apiCreateGoal,
  apiCreateProject,
  apiGetEnterpriseWorkbench,
  apiGoalAction,
  apiListAssistantProfiles,
  apiListDatabases,
  apiListGoals,
  apiListProjects,
  apiUpdateProject,
  type AssistantProfileItem,
  type DataSourceItem,
  type EnterpriseWorkbenchOverview,
  type EnterpriseWorkbenchScenario,
  type GoalItem,
  type ProjectItem,
} from '../api/client'

type WorkbenchTab = 'overview' | 'inbox' | 'projects' | 'profiles' | 'goals'
type AssistantPersonality = AssistantProfileItem['personality']

export const ASSISTANT_PERSONALITY_OPTIONS: Array<{
  value: AssistantPersonality
  label: string
}> = [
  { value: 'none', label: '中性' },
  { value: 'friendly', label: '友好' },
  { value: 'pragmatic', label: '务实' },
  { value: 'cute', label: '可爱' },
  { value: 'romantic', label: '浪漫' },
  { value: 'funny', label: '搞笑' },
]

const ASSISTANT_PERSONALITY_LABELS = Object.fromEntries(
  ASSISTANT_PERSONALITY_OPTIONS.map((item) => [item.value, item.label]),
) as Record<AssistantPersonality, string>

const statusLabel: Record<string, string> = {
  queued: '排队中',
  in_progress: '执行中',
  requires_action: '等待操作',
  paused: '已暂停',
  completed: '已完成',
  failed: '失败',
  incomplete: '未完成',
  cancelled: '已取消',
  ready: '企业级就绪',
  attention: '需要关注',
  foundation: '建设中',
}

function formatTime(value?: string | null) {
  if (!value) return '刚刚'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function scoreTone(score: number) {
  if (score >= 85) return 'text-emerald-500'
  if (score >= 60) return 'text-amber-500'
  return 'text-blue-500'
}

export function scenarioLaunchIntent(scenario: EnterpriseWorkbenchScenario): {
  route: string
  prefillText: string | null
} {
  const canPrefill = scenario.status !== 'setup_required'
    && scenario.launch_mode === 'chat'
    && scenario.action_route === '/chat'
    && scenario.starter_prompt.trim().length > 0
  return {
    route: scenario.action_route,
    prefillText: canPrefill ? scenario.starter_prompt : null,
  }
}

export default function WorkPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((state) => state.token)!
  const displayName = useAuthStore((state) => state.displayName)
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab') as WorkbenchTab | null
  const activeTab: WorkbenchTab = requestedTab && ['overview', 'inbox', 'projects', 'profiles', 'goals'].includes(requestedTab)
    ? requestedTab
    : 'overview'

  const [overview, setOverview] = useState<EnterpriseWorkbenchOverview | null>(null)
  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [goals, setGoals] = useState<GoalItem[]>([])
  const [profiles, setProfiles] = useState<AssistantProfileItem[]>([])
  const [dataSources, setDataSources] = useState<DataSourceItem[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [projectName, setProjectName] = useState('')
  const [projectInstructions, setProjectInstructions] = useState('')
  const [projectMemoryMode, setProjectMemoryMode] = useState<'default' | 'project_only'>('default')
  const [projectDataSourceIds, setProjectDataSourceIds] = useState<string[]>([])
  const [objective, setObjective] = useState('')
  const [successCriteria, setSuccessCriteria] = useState('')
  const [projectId, setProjectId] = useState('')
  const [profileName, setProfileName] = useState('')
  const [profileInstructions, setProfileInstructions] = useState('')
  const [personality, setPersonality] = useState<AssistantPersonality>('none')

  const load = useCallback(async (quiet = false) => {
    quiet ? setRefreshing(true) : setLoading(true)
    setError('')
    try {
      const [nextOverview, nextProjects, nextGoals, nextProfiles, nextDataSources] = await Promise.all([
        apiGetEnterpriseWorkbench(token, 12, 50),
        apiListProjects(token),
        apiListGoals(token),
        apiListAssistantProfiles(token),
        apiListDatabases(token),
      ])
      setOverview(nextOverview)
      setProjects(nextProjects)
      setGoals(nextGoals)
      setProfiles(nextProfiles)
      setDataSources(nextDataSources.filter((item) => !item.status || item.status === 'active'))
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : '工作台加载失败')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [token])

  useEffect(() => { void load() }, [load])

  const setTab = (tab: WorkbenchTab) => {
    if (tab === 'overview') setSearchParams({}, { replace: true })
    else setSearchParams({ tab }, { replace: true })
  }

  const runAction = async (action: () => Promise<unknown>) => {
    setError('')
    try {
      await action()
      await load(true)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : '操作失败')
    }
  }

  const goalAction = (goalId: string, action: 'pause' | 'resume' | 'cancel') =>
    runAction(() => apiGoalAction(token, goalId, action))

  const toggleProjectDataSource = (dataSourceId: string) => {
    setProjectDataSourceIds((items) => items.includes(dataSourceId)
      ? items.filter((item) => item !== dataSourceId)
      : [...items, dataSourceId])
  }

  const updateProjectDataSource = (project: ProjectItem, dataSourceId: string) => {
    const nextIds = project.data_source_ids.includes(dataSourceId)
      ? project.data_source_ids.filter((item) => item !== dataSourceId)
      : [...project.data_source_ids, dataSourceId]
    return runAction(() => apiUpdateProject(token, project.id, {
      name: project.name,
      description: project.description,
      instructions: project.instructions,
      memory_mode: project.memory_mode,
      assistant_profile_id: project.assistant_profile_id,
      data_source_ids: nextIds,
    }))
  }

  const createProject = () => runAction(async () => {
    await apiCreateProject(token, {
      name: projectName.trim(),
      description: '',
      instructions: projectInstructions.trim(),
      memory_mode: projectMemoryMode,
      assistant_profile_id: null,
      data_source_ids: projectDataSourceIds,
    })
    setProjectName('')
    setProjectInstructions('')
    setProjectDataSourceIds([])
  })

  const createProfile = () => runAction(async () => {
    await apiCreateAssistantProfile(token, {
      name: profileName.trim(),
      personality,
      instructions: profileInstructions.trim(),
      default_model_profile: 'auto',
      tool_policy: {},
      memory_policy: {},
      is_default: false,
    })
    setProfileName('')
    setProfileInstructions('')
  })

  const createGoal = () => runAction(async () => {
    await apiCreateGoal(token, {
      objective: objective.trim(),
      success_criteria: successCriteria.trim(),
      project_id: projectId || undefined,
      execution_profile: 'deep',
    })
    setObjective('')
    setSuccessCriteria('')
  })

  const projectNames = useMemo(() => new Map(projects.map((project) => [project.id, project.name])), [projects])
  const tabs: Array<{ id: WorkbenchTab; label: string }> = [
    { id: 'overview', label: '总览' },
    { id: 'inbox', label: overview?.summary.unread_notifications ? `行动中心 ${overview.summary.unread_notifications}` : '行动中心' },
    { id: 'projects', label: 'Projects' },
    { id: 'profiles', label: 'AI 角色' },
    { id: 'goals', label: 'Goals' },
  ]

  return (
    <div className="flex min-h-screen flex-col bg-[var(--bg)] text-[var(--text)]">
      <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--bg)]/95 backdrop-blur">
        <div className="mx-auto flex h-16 w-full max-w-7xl items-center gap-3 px-4 sm:px-6">
          <button onClick={onBack} aria-label="返回对话" className="flex h-9 w-9 items-center justify-center rounded-xl hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold">企业 AI 工作台</h1>
            <p className="truncate text-xs text-[var(--text-secondary)]">统一承接上下文、知识、数据、执行、审批与主动工作。</p>
          </div>
          <button onClick={() => void load(true)} disabled={refreshing} className="inline-flex h-9 items-center gap-2 rounded-xl border border-[var(--border)] px-3 text-xs text-[var(--text-secondary)] hover:bg-[var(--surface)] disabled:opacity-50"><RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />刷新</button>
          <button onClick={() => navigate('/chat')} className="inline-flex h-9 items-center gap-2 rounded-xl bg-[var(--accent)] px-4 text-xs font-medium text-[var(--accent-foreground)]"><Sparkles size={14} />开始工作</button>
        </div>
        <div className="mx-auto flex w-full max-w-7xl gap-1 overflow-x-auto px-4 pb-3 sm:px-6">
          {tabs.map((tab) => <button key={tab.id} onClick={() => setTab(tab.id)} className={`rounded-lg px-3 py-1.5 text-xs transition-colors ${activeTab === tab.id ? 'bg-[var(--accent-dim)] font-medium text-[var(--accent)]' : 'text-[var(--text-secondary)] hover:bg-[var(--surface)]'}`}>{tab.label}</button>)}
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 p-4 sm:p-6">
        {error && <div role="alert" className="mb-5 flex items-center justify-between gap-3 rounded-2xl border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-500"><span>{error}</span><button onClick={() => void load()} className="rounded-lg border border-red-500/30 px-3 py-1 text-xs">重试</button></div>}
        {loading && !overview ? <div className="grid min-h-[50vh] place-items-center text-sm text-[var(--text-secondary)]"><div className="flex items-center gap-2"><RefreshCw size={16} className="animate-spin" />正在汇总企业工作状态…</div></div> : null}

        {activeTab === 'overview' && overview && <OverviewPanel overview={overview} displayName={displayName} navigate={navigate} />}
        {activeTab === 'inbox' && overview && <WorkbenchActionCenter overview={overview} onRefresh={() => load(true)} />}

        {activeTab === 'projects' && <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
          <section className="h-fit rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <div className="mb-4 flex items-center gap-2"><FolderKanban size={18} /><div><h2 className="font-medium">新建 Project</h2><p className="text-xs text-[var(--text-secondary)]">隔离指令、记忆和企业数据权限。</p></div></div>
            <div className="space-y-3">
              <input value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="Project 名称" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm" />
              <textarea value={projectInstructions} onChange={(event) => setProjectInstructions(event.target.value)} rows={5} placeholder="业务背景、术语、输出规范和决策约束" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm" />
              <select value={projectMemoryMode} onChange={(event) => setProjectMemoryMode(event.target.value as 'default' | 'project_only')} className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm"><option value="default">个人记忆 + Project 记忆</option><option value="project_only">仅 Project 记忆</option></select>
              <div className="rounded-xl border border-[var(--border)] p-3"><p className="mb-2 text-xs text-[var(--text-secondary)]">授权企业数据源</p>{dataSources.length ? <div className="space-y-2">{dataSources.map((source) => <label key={source.id} className="flex items-center gap-2 text-xs"><input type="checkbox" checked={projectDataSourceIds.includes(source.id)} onChange={() => toggleProjectDataSource(source.id)} /><span>{source.name} · {source.type}</span></label>)}</div> : <button onClick={() => navigate('/databases')} className="text-xs text-[var(--accent)]">先连接企业数据源</button>}</div>
              <button disabled={!projectName.trim()} onClick={() => void createProject()} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2.5 text-sm text-[var(--accent-foreground)] disabled:opacity-40"><Plus size={15} />创建 Project</button>
            </div>
          </section>
          <section><div className="mb-3 flex items-center justify-between"><div><h2 className="font-medium">业务上下文</h2><p className="text-xs text-[var(--text-secondary)]">Project 会进入 Responses 上下文组装与资源授权链路。</p></div><span className="text-xs text-[var(--text-secondary)]">{projects.length} 个</span></div><div className="grid gap-3 md:grid-cols-2">{projects.map((project) => <article key={project.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-start justify-between gap-3"><div><h3 className="font-medium">{project.name}</h3><p className="mt-1 line-clamp-2 text-xs text-[var(--text-secondary)]">{project.instructions || '尚未设置业务指令'}</p></div><span className="rounded-full bg-[var(--accent-dim)] px-2 py-1 text-[10px] text-[var(--accent)]">{project.memory_mode === 'project_only' ? '隔离记忆' : '融合记忆'}</span></div><div className="mt-4 border-t border-[var(--border)] pt-3"><p className="mb-2 text-[11px] text-[var(--text-secondary)]">已授权数据源 {project.data_source_ids.length}</p><div className="space-y-1.5">{dataSources.map((source) => <label key={source.id} className="flex items-center gap-2 text-xs"><input type="checkbox" checked={project.data_source_ids.includes(source.id)} onChange={() => void updateProjectDataSource(project, source.id)} /><span className="truncate">{source.name}</span></label>)}</div></div></article>)}{projects.length === 0 && <EmptyState title="还没有 Project" description="先将一个真实业务场景沉淀为稳定的 AI 工作上下文。" />}</div></section>
        </div>}

        {activeTab === 'profiles' && <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
          <section className="h-fit rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5"><div className="mb-4 flex items-center gap-2"><Bot size={18} /><div><h2 className="font-medium">新建 AI 角色</h2><p className="text-xs text-[var(--text-secondary)]">定义稳定的沟通风格与执行偏好。</p></div></div><div className="space-y-3"><input value={profileName} onChange={(event) => setProfileName(event.target.value)} placeholder="角色名称" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm" /><select value={personality} onChange={(event) => setPersonality(event.target.value as typeof personality)} className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm">{ASSISTANT_PERSONALITY_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select><textarea value={profileInstructions} onChange={(event) => setProfileInstructions(event.target.value)} rows={5} placeholder="角色职责、语气和输出要求" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm" /><button disabled={!profileName.trim()} onClick={() => void createProfile()} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2.5 text-sm text-[var(--accent-foreground)] disabled:opacity-40"><Plus size={15} />创建角色</button></div></section>
          <section><div className="mb-3"><h2 className="font-medium">可用角色</h2><p className="text-xs text-[var(--text-secondary)]">角色策略由 Manager Agent Loop 在运行时应用。</p></div><div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{profiles.map((profile) => <article key={profile.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-start justify-between gap-3"><div className="grid h-10 w-10 place-items-center rounded-xl bg-[var(--accent-dim)] text-[var(--accent)]"><Bot size={18} /></div>{profile.built_in && <span className="text-[10px] text-[var(--text-secondary)]">平台内置</span>}</div><h3 className="mt-4 font-medium">{profile.name}</h3><p className="mt-1 text-xs text-[var(--text-secondary)]">{ASSISTANT_PERSONALITY_LABELS[profile.personality]} · {profile.default_model_profile}</p><p className="mt-3 line-clamp-3 text-xs text-[var(--text-secondary)]">{profile.instructions || '遵循平台默认企业助手规范。'}</p></article>)}</div></section>
        </div>}

        {activeTab === 'goals' && <div className="grid gap-6 lg:grid-cols-[400px_1fr]">
          <section className="h-fit rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5"><div className="mb-4 flex items-center gap-2"><Target size={18} /><div><h2 className="font-medium">启动长期 Goal</h2><p className="text-xs text-[var(--text-secondary)]">通过可恢复 Responses 主链路持续推进。</p></div></div><div className="space-y-3"><textarea value={objective} onChange={(event) => setObjective(event.target.value)} rows={5} placeholder="描述需要持续推进的业务目标" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm" /><textarea value={successCriteria} onChange={(event) => setSuccessCriteria(event.target.value)} rows={3} placeholder="可验证的成功标准" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm" /><select value={projectId} onChange={(event) => setProjectId(event.target.value)} className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm"><option value="">不绑定 Project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select><button disabled={objective.trim().length < 3} onClick={() => void createGoal()} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2.5 text-sm text-[var(--accent-foreground)] disabled:opacity-40"><Play size={15} />启动 Goal</button></div></section>
          <section><div className="mb-3"><h2 className="font-medium">Goal 运行态</h2><p className="text-xs text-[var(--text-secondary)]">状态、检查点和 Response 均持久化，可暂停和恢复。</p></div><div className="space-y-3">{goals.map((goal) => <article key={goal.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-start justify-between gap-4"><div className="min-w-0"><h3 className="font-medium">{goal.objective}</h3><p className="mt-1 text-xs text-[var(--text-secondary)]">{goal.project_id ? projectNames.get(goal.project_id) || 'Project' : '独立 Goal'} · 检查点 {goal.current_step}</p></div><span className="flex-none rounded-full border border-[var(--border)] px-2 py-1 text-xs">{statusLabel[goal.status] || goal.status}</span></div>{goal.success_criteria && <p className="mt-3 rounded-xl bg-[var(--surface-raised)] p-3 text-xs text-[var(--text-secondary)]">成功标准：{goal.success_criteria}</p>}<div className="mt-3 flex flex-wrap gap-2">{['queued', 'in_progress', 'requires_action'].includes(goal.status) && <button onClick={() => void goalAction(goal.id, 'pause')} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2 py-1 text-xs"><Pause size={12} />暂停</button>}{goal.status === 'paused' && <button onClick={() => void goalAction(goal.id, 'resume')} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2 py-1 text-xs"><Play size={12} />恢复</button>}{!['completed', 'cancelled'].includes(goal.status) && <button onClick={() => void goalAction(goal.id, 'cancel')} className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 px-2 py-1 text-xs text-red-500"><Ban size={12} />取消</button>}{goal.response_id && <button onClick={() => navigate('/chat')} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-[var(--accent)]">查看执行<ArrowRight size={12} /></button>}</div></article>)}{goals.length === 0 && <EmptyState title="还没有运行中的 Goal" description="将跨小时、跨天的复杂工作交给可恢复 Agent Loop。" />}</div></section>
        </div>}
      </main>
    </div>
  )
}

export function OverviewPanel({ overview, displayName, navigate }: { overview: EnterpriseWorkbenchOverview; displayName: string | null; navigate: ReturnType<typeof useNavigate> }) {
  const requestPrefill = useChatPreferences((state) => state.requestPrefill)
  const summaryCards = [
    { label: '运行中的 AI 工作', value: overview.summary.running_responses, detail: `${overview.summary.pending_approvals} 个待审批`, icon: Activity, route: '/chat' },
    { label: '长期 Goals', value: overview.summary.active_goals, detail: `${overview.summary.projects} 个 Project`, icon: Target, route: '/work?tab=goals' },
    { label: '可信企业知识', value: overview.summary.published_knowledge, detail: `${overview.summary.knowledge_spaces} 个可访问空间`, icon: BookOpen, route: '/knowledge-base' },
    { label: '企业数据连接', value: overview.summary.accessible_data_sources, detail: `${overview.summary.active_alerts} 个主动预警`, icon: Database, route: '/databases' },
  ]
  const dimensions = [
    ['业务上下文', overview.readiness.dimensions.context],
    ['企业知识', overview.readiness.dimensions.knowledge],
    ['企业数据', overview.readiness.dimensions.data],
    ['主动工作', overview.readiness.dimensions.automation],
    ['安全治理', overview.readiness.dimensions.governance],
  ] as const
  const scenarioStatusLabel: Record<EnterpriseWorkbenchScenario['status'], string> = {
    ready: '可开始',
    setup_required: '需配置',
    active: '已启用',
  }
  const memoryScopeLabel: Record<EnterpriseWorkbenchScenario['memory_scope'], string> = {
    conversation: '会话记忆',
    user: '个人记忆',
    project: 'Project 记忆',
  }
  const launchScenario = (scenario: EnterpriseWorkbenchScenario) => {
    const intent = scenarioLaunchIntent(scenario)
    if (intent.prefillText) requestPrefill(intent.prefillText)
    navigate(intent.route)
  }

  return <div className="space-y-6">
    <WorkbenchTodayPulse pulse={overview.operating_pulse} />
    <WorkbenchContinuity items={overview.recent_activity} navigate={navigate} />

    <section aria-label="工作台状态" className="grid gap-5 border-y border-[var(--border)] py-5 lg:grid-cols-[1fr_1.1fr] lg:items-center">
      <div>
        <h2 className="text-xl font-semibold">{displayName ? `${displayName}，` : ''}继续今天最重要的工作</h2>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">{overview.summary.running_responses} 项执行中 · {overview.summary.pending_approvals} 项待审批 · {overview.summary.unacknowledged_alerts} 个预警待确认</p>
        <div className="mt-4 flex flex-wrap gap-2"><button onClick={() => navigate('/chat')} className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)]"><Plus size={15} />新工作</button><button onClick={() => navigate('/knowledge-base')} className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-4 py-2 text-sm"><BookOpen size={15} />查询企业知识</button></div>
      </div>
      <div>
        <div className="flex items-center justify-between gap-4"><div className="flex items-center gap-3"><CircleGauge size={24} className={scoreTone(overview.readiness.score)} /><div><p className="text-xs text-[var(--text-secondary)]">企业 AI 就绪度</p><p className="text-sm font-medium">{statusLabel[overview.readiness.status]}</p></div></div><div className={`text-2xl font-semibold ${scoreTone(overview.readiness.score)}`}>{overview.readiness.score}<span className="text-xs font-normal text-[var(--text-secondary)]"> / 100</span></div></div>
        <div className="mt-4 grid grid-cols-5 gap-2">{dimensions.map(([label, value]) => <div key={label} className="min-w-0"><div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-raised)]"><div className="h-full rounded-full bg-[var(--accent)]" style={{ width: `${value}%` }} /></div><div className="mt-1 truncate text-[10px] text-[var(--text-secondary)]">{label}</div></div>)}</div>
      </div>
    </section>

    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{summaryCards.map(({ label, value, detail, icon: Icon, route }) => <button key={label} onClick={() => navigate(route)} className="group rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 text-left transition-transform hover:-translate-y-0.5 hover:border-[var(--accent)]/40"><div className="flex items-start justify-between"><div className="grid h-9 w-9 place-items-center rounded-xl bg-[var(--accent-dim)] text-[var(--accent)]"><Icon size={17} /></div><ArrowRight size={14} className="text-[var(--text-secondary)] transition-transform group-hover:translate-x-0.5" /></div><div className="mt-4 text-2xl font-semibold">{value}</div><div className="mt-1 text-sm">{label}</div><div className="mt-1 text-xs text-[var(--text-secondary)]">{detail}</div></button>)}</section>

    <section>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2"><Workflow size={17} className="text-[var(--accent)]" /><h2 className="font-medium">企业日常工作场景</h2></div>
          <p className="mt-1 text-xs text-[var(--text-secondary)]">按当前上下文、知识、数据、Skill 和主动工作状态生成；写操作继续走持久化审批。</p>
        </div>
        <span className="rounded-full bg-[var(--surface)] px-3 py-1 text-xs text-[var(--text-secondary)]">{overview.summary.available_work_scenarios}/{overview.scenarios.length} 可用 · {overview.summary.active_work_scenarios} 已启用</span>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {overview.scenarios.map((scenario) => (
          <button key={scenario.id} onClick={() => launchScenario(scenario)} className="group flex min-h-64 flex-col rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 text-left hover:border-[var(--accent)]/40">
            <div className="flex items-start justify-between gap-3">
              <span className="rounded-full bg-[var(--surface-raised)] px-2 py-1 text-[10px] text-[var(--text-secondary)]">{scenario.category}</span>
              <span className={`rounded-full px-2 py-1 text-[10px] ${scenario.status === 'active' ? 'bg-emerald-500/10 text-emerald-500' : scenario.status === 'setup_required' ? 'bg-amber-500/10 text-amber-500' : 'bg-[var(--accent-dim)] text-[var(--accent)]'}`}>{scenarioStatusLabel[scenario.status]}{scenario.recommended ? ' · 推荐' : ''}</span>
            </div>
            <h3 className="mt-4 text-sm font-medium">{scenario.title}</h3>
            <p className="mt-2 text-xs leading-5 text-[var(--text-secondary)]">{scenario.description}</p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {scenario.deliverables.slice(0, 3).map((item) => <span key={item} className="rounded-md border border-[var(--border)] px-1.5 py-0.5 text-[10px] text-[var(--text-secondary)]">{item}</span>)}
            </div>
            <div className="mt-auto pt-4">
              <div className="flex items-center justify-between gap-3 text-[10px] text-[var(--text-secondary)]"><span>{memoryScopeLabel[scenario.memory_scope]}</span><span>{scenario.approval_required ? '写入前审批' : scenario.approval_policy === 'inherited' ? '副作用继承审批' : '只读免审批'}</span></div>
              {scenario.blockers[0] && <p className="mt-2 line-clamp-2 text-[10px] text-amber-500">{scenario.blockers[0].title}</p>}
              <div className="mt-3 flex items-center justify-between text-xs text-[var(--accent)]"><span>{scenario.action_label}</span><ArrowRight size={13} className="transition-transform group-hover:translate-x-0.5" /></div>
            </div>
          </button>
        ))}
      </div>
    </section>

    <div className="grid gap-6 xl:grid-cols-[1.15fr_.85fr]">
      <section><div className="mb-3 flex items-center justify-between"><div><h2 className="font-medium">需要你关注</h2><p className="text-xs text-[var(--text-secondary)]">审批、预警、失败执行和知识治理集中在一个队列。</p></div><span className="rounded-full bg-[var(--surface)] px-2.5 py-1 text-xs text-[var(--text-secondary)]">{overview.attention_items.length} 项</span></div><div className="space-y-2">{overview.attention_items.map((item) => <button key={`${item.type}-${item.id}`} onClick={() => navigate(item.route)} className="flex w-full items-start gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 text-left hover:border-[var(--accent)]/40"><div className={`mt-0.5 grid h-9 w-9 flex-none place-items-center rounded-xl ${item.severity === 'error' || item.severity === 'critical' ? 'bg-red-500/10 text-red-500' : 'bg-amber-500/10 text-amber-500'}`}>{item.type === 'approval' ? <ShieldCheck size={17} /> : item.type === 'knowledge' ? <BookOpen size={17} /> : <AlertTriangle size={17} />}</div><div className="min-w-0 flex-1"><div className="flex items-start justify-between gap-3"><h3 className="text-sm font-medium">{item.title}</h3><span className="flex-none text-[10px] text-[var(--text-secondary)]">{formatTime(item.created_at)}</span></div><p className="mt-1 text-xs leading-5 text-[var(--text-secondary)]">{item.description}</p></div></button>)}{overview.attention_items.length === 0 && <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface)] p-8 text-center"><CheckCircle2 size={28} className="mx-auto text-emerald-500" /><p className="mt-3 text-sm font-medium">当前没有阻塞事项</p><p className="mt-1 text-xs text-[var(--text-secondary)]">审批、预警与治理队列均处于可控状态。</p></div>}</div></section>

      <section><div className="mb-3"><h2 className="font-medium">下一步建设建议</h2><p className="text-xs text-[var(--text-secondary)]">按企业 AI 就绪度自动生成，不是通用产品导览。</p></div><div className="space-y-2">{overview.readiness.blockers.map((blocker, index) => <button key={blocker.code} onClick={() => navigate(blocker.route)} className="flex w-full items-start gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 text-left hover:border-[var(--accent)]/40"><span className="grid h-7 w-7 flex-none place-items-center rounded-full bg-[var(--accent-dim)] text-xs font-semibold text-[var(--accent)]">{index + 1}</span><div><h3 className="text-sm font-medium">{blocker.title}</h3><p className="mt-1 text-xs leading-5 text-[var(--text-secondary)]">{blocker.description}</p></div></button>)}{overview.readiness.blockers.length === 0 && <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5"><CheckCircle2 size={22} className="text-emerald-500" /><h3 className="mt-3 text-sm font-medium">企业 AI 基础能力已就绪</h3><p className="mt-1 text-xs text-[var(--text-secondary)]">可继续通过真实业务反馈、评测和知识治理持续提升质量。</p></div>}</div>
        <div className="mt-5 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-center justify-between"><div className="flex items-center gap-2"><ShieldCheck size={16} className={scoreTone(overview.knowledge_health.score)} /><span className="text-sm font-medium">知识治理健康</span></div><span className={`text-lg font-semibold ${scoreTone(overview.knowledge_health.score)}`}>{overview.knowledge_health.score}</span></div><div className="mt-3 grid grid-cols-3 gap-2 text-center"><MiniMetric label="到期复审" value={overview.knowledge_health.metrics.due_reviews || 0} /><MiniMetric label="待处理反馈" value={overview.knowledge_health.metrics.unresolved_feedback || 0} /><MiniMetric label="失败任务" value={overview.knowledge_health.metrics.failed_jobs || 0} /></div><button onClick={() => navigate('/knowledge')} className="mt-3 inline-flex items-center gap-1 text-xs text-[var(--accent)]">进入治理中心<ArrowRight size={12} /></button></div>
      </section>
    </div>

    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"><QuickLink icon={BarChartBig} title="经营报告" description="洞察、月报与管理简报" route="/reports" navigate={navigate} /><QuickLink icon={CalendarDays} title="我的日历" description="时间型记忆与个人安排" route="/calendar" navigate={navigate} /><QuickLink icon={BellRing} title="定时任务" description={`${overview.summary.scheduled_tasks} 个正在运行`} route="/tasks" navigate={navigate} /><QuickLink icon={Activity} title="主动预警" description={`${overview.summary.unacknowledged_alerts} 个待确认`} route="/alerts" navigate={navigate} /><QuickLink icon={BookOpen} title="企业知识库" description={`${overview.summary.knowledge_spaces} 个授权空间`} route="/knowledge-base" navigate={navigate} /></section>
  </div>
}

export function WorkbenchContinuity({
  items,
  navigate,
}: {
  items: EnterpriseWorkbenchOverview['recent_activity']
  navigate: ReturnType<typeof useNavigate>
}) {
  return (
    <section aria-label="工作续接">
      <div className="mb-3 flex items-end justify-between gap-3">
        <div><div className="flex items-center gap-2"><Clock3 size={16} className="text-[var(--accent)]" /><h2 className="font-medium">工作续接</h2></div><p className="mt-1 text-xs text-[var(--text-secondary)]">按会话保留上下文，直接回到审批、执行、重试或下一轮工作。</p></div>
        <span className="text-xs text-[var(--text-secondary)]">{items.length} 项</span>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <button key={`${item.type}-${item.id}`} onClick={() => navigate(item.route)} className="group flex min-h-40 flex-col rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 text-left hover:border-[var(--accent)]/40">
            <div className="flex items-center justify-between gap-3"><span className="inline-flex min-w-0 items-center gap-1.5 text-[11px] text-[var(--text-secondary)]">{item.type === 'goal' ? <Target size={12} /> : <Workflow size={12} />}<span className="truncate">{item.project_name || (item.type === 'goal' ? '独立 Goal' : '未绑定 Project')}</span></span><span className="flex-none rounded-full border border-[var(--border)] px-2 py-0.5 text-[10px]">{statusLabel[item.status] || item.status}</span></div>
            <h3 className="mt-3 line-clamp-2 text-sm font-medium">{item.title}</h3>
            <p className="mt-2 text-xs text-[var(--text-secondary)]">{item.description} · {formatTime(item.created_at)}</p>
            <div className="mt-auto flex items-center justify-between pt-4 text-xs font-medium text-[var(--accent)]"><span>{item.action_label}</span><ArrowRight size={13} className="transition-transform group-hover:translate-x-0.5" /></div>
          </button>
        ))}
        {items.length === 0 && <EmptyState title="还没有可续接工作" description="从一次企业问答或长期 Goal 开始。" />}
      </div>
    </section>
  )
}

function EmptyState({ title, description }: { title: string; description: string }) {
  return <div className="rounded-2xl border border-dashed border-[var(--border)] p-8 text-center"><Sparkles size={24} className="mx-auto text-[var(--text-secondary)]" /><p className="mt-3 text-sm font-medium">{title}</p><p className="mt-1 text-xs text-[var(--text-secondary)]">{description}</p></div>
}

function MiniMetric({ label, value }: { label: string; value: number }) {
  return <div className="rounded-xl bg-[var(--surface-raised)] p-2"><div className="text-lg font-semibold">{value}</div><div className="text-[10px] text-[var(--text-secondary)]">{label}</div></div>
}

function QuickLink({ icon: Icon, title, description, route, navigate }: { icon: typeof Activity; title: string; description: string; route: string; navigate: ReturnType<typeof useNavigate> }) {
  return <button onClick={() => navigate(route)} className="flex items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 text-left hover:border-[var(--accent)]/40"><div className="grid h-10 w-10 place-items-center rounded-xl bg-[var(--accent-dim)] text-[var(--accent)]"><Icon size={17} /></div><div className="min-w-0 flex-1"><div className="text-sm font-medium">{title}</div><div className="text-xs text-[var(--text-secondary)]">{description}</div></div><ArrowRight size={14} className="text-[var(--text-secondary)]" /></button>
}
