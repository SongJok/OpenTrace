import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Building2,
  CheckCircle2,
  ChevronLeft,
  CircleGauge,
  Database,
  Network,
  RefreshCw,
  ServerCog,
  ShieldCheck,
  Users,
  Workflow,
} from 'lucide-react'
import { useAuthStore } from '../store/auth'
import {
  apiGetEnterpriseOperations,
  apiListDirectoryMemberships,
  apiListDirectoryPrincipals,
  apiListDirectorySyncRuns,
  apiSyncEnterpriseDirectory,
  type DirectoryMembershipItem,
  type DirectoryPrincipalItem,
  type DirectorySyncRunItem,
  type EnterpriseOperationsOverview,
} from '../api/client'

type AdminTab = 'overview' | 'directory'

function formatTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function tone(score: number) {
  if (score >= 85) return 'text-emerald-500'
  if (score >= 60) return 'text-amber-500'
  return 'text-red-500'
}

export default function EnterpriseAdminPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((state) => state.token)!
  const navigate = useNavigate()
  const [tab, setTab] = useState<AdminTab>('overview')
  const [overview, setOverview] = useState<EnterpriseOperationsOverview | null>(null)
  const [principals, setPrincipals] = useState<DirectoryPrincipalItem[]>([])
  const [memberships, setMemberships] = useState<DirectoryMembershipItem[]>([])
  const [syncRuns, setSyncRuns] = useState<DirectorySyncRunItem[]>([])
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [provider, setProvider] = useState<'manual' | 'scim' | 'hr'>('manual')
  const [principalType, setPrincipalType] = useState<'department' | 'group' | 'role'>('department')
  const [externalId, setExternalId] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [parentId, setParentId] = useState('')
  const [userEmail, setUserEmail] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [nextOverview, nextPrincipals, nextMemberships, nextRuns] = await Promise.all([
        apiGetEnterpriseOperations(token),
        apiListDirectoryPrincipals(token),
        apiListDirectoryMemberships(token),
        apiListDirectorySyncRuns(token),
      ])
      setOverview(nextOverview)
      setPrincipals(nextPrincipals)
      setMemberships(nextMemberships)
      setSyncRuns(nextRuns)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : '企业运营中心加载失败')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { void load() }, [load])

  const syncPrincipal = async () => {
    if (!externalId.trim() || !displayName.trim()) return
    setWorking(true)
    setError('')
    try {
      await apiSyncEnterpriseDirectory(token, {
        provider,
        authoritative: false,
        principals: [{
          principal_type: principalType,
          external_id: externalId.trim(),
          display_name: displayName.trim(),
          parent_external_id: parentId.trim() || null,
          status: 'active',
          attributes: {},
        }],
        memberships: userEmail.trim() ? [{
          user_email: userEmail.trim(),
          principal_type: principalType,
          principal_external_id: externalId.trim(),
          status: 'active',
          metadata: { source: 'enterprise_admin_ui' },
        }] : [],
      })
      setExternalId('')
      setDisplayName('')
      setParentId('')
      setUserEmail('')
      await load()
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : '企业目录同步失败')
    } finally {
      setWorking(false)
    }
  }

  const groupedPrincipals = useMemo(() => ({
    department: principals.filter((item) => item.principal_type === 'department'),
    group: principals.filter((item) => item.principal_type === 'group'),
    role: principals.filter((item) => item.principal_type === 'role'),
  }), [principals])

  return <div className="flex min-h-screen flex-col bg-[var(--bg)] text-[var(--text)]">
    <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--bg)]/95 backdrop-blur">
      <div className="mx-auto flex h-16 w-full max-w-7xl items-center gap-3 px-4 sm:px-6">
        <button onClick={onBack} aria-label="返回工作台" className="grid h-9 w-9 place-items-center rounded-xl hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
        <div className="min-w-0 flex-1"><h1 className="text-sm font-semibold">企业运营中心</h1><p className="truncate text-xs text-[var(--text-secondary)]">租户采用、执行质量、知识资产、风险与组织目录的统一控制面。</p></div>
        <button onClick={() => void load()} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] px-3 py-2 text-xs disabled:opacity-50"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />刷新</button>
      </div>
      <div className="mx-auto flex w-full max-w-7xl gap-1 px-4 pb-3 sm:px-6">{([{ id: 'overview', label: '运营总览' }, { id: 'directory', label: '企业目录' }] as const).map((item) => <button key={item.id} onClick={() => setTab(item.id)} className={`rounded-lg px-3 py-1.5 text-xs ${tab === item.id ? 'bg-[var(--accent-dim)] font-medium text-[var(--accent)]' : 'text-[var(--text-secondary)] hover:bg-[var(--surface)]'}`}>{item.label}</button>)}</div>
    </header>
    <main className="mx-auto w-full max-w-7xl flex-1 p-4 sm:p-6">
      {error && <div role="alert" className="mb-5 rounded-2xl border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-500">{error}</div>}
      {loading && !overview ? <div className="grid min-h-[50vh] place-items-center text-sm text-[var(--text-secondary)]"><RefreshCw size={16} className="mr-2 animate-spin" />正在聚合企业运营状态…</div> : null}
      {tab === 'overview' && overview && <OperationsOverview data={overview} navigate={navigate} />}
      {tab === 'directory' && <div className="space-y-6">
        <section className="grid gap-4 md:grid-cols-3"><DirectoryStat icon={Building2} label="部门" value={groupedPrincipals.department.filter((item) => item.status === 'active').length} /><DirectoryStat icon={Users} label="用户组" value={groupedPrincipals.group.filter((item) => item.status === 'active').length} /><DirectoryStat icon={ShieldCheck} label="岗位" value={groupedPrincipals.role.filter((item) => item.status === 'active').length} /></section>
        <div className="grid gap-6 xl:grid-cols-[380px_1fr]">
          <section className="h-fit rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5"><div className="flex items-center gap-2"><Network size={18} /><div><h2 className="font-medium">同步目录主体</h2><p className="text-xs text-[var(--text-secondary)]">UI 支持单条维护；批量 SCIM/HR 使用同一 API。</p></div></div><div className="mt-4 space-y-3"><select value={provider} onChange={(event) => setProvider(event.target.value as typeof provider)} className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm"><option value="manual">手工维护</option><option value="scim">SCIM</option><option value="hr">HR 系统</option></select><select value={principalType} onChange={(event) => setPrincipalType(event.target.value as typeof principalType)} className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm"><option value="department">部门</option><option value="group">用户组</option><option value="role">岗位</option></select><input value={externalId} onChange={(event) => setExternalId(event.target.value)} placeholder="外部稳定 ID" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm" /><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="显示名称" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm" /><input value={parentId} onChange={(event) => setParentId(event.target.value)} placeholder="上级外部 ID（可选）" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm" /><input value={userEmail} onChange={(event) => setUserEmail(event.target.value)} placeholder="同时加入用户邮箱（可选）" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm" /><button onClick={() => void syncPrincipal()} disabled={working || !externalId.trim() || !displayName.trim()} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2.5 text-sm text-[var(--accent-foreground)] disabled:opacity-40"><Workflow size={15} />{working ? '同步中…' : '同步并投影 ACL'}</button></div></section>
          <section><div className="mb-3 flex items-center justify-between"><div><h2 className="font-medium">目录主体与成员</h2><p className="text-xs text-[var(--text-secondary)]">成员关系自动同步到企业知识空间的组织主体授权。</p></div><span className="text-xs text-[var(--text-secondary)]">{memberships.length} 条成员关系</span></div><div className="grid gap-3 md:grid-cols-2">{principals.map((principal) => { const members = memberships.filter((item) => item.principal_id === principal.id && item.status === 'active'); return <article key={principal.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-start justify-between gap-3"><div><h3 className="font-medium">{principal.display_name}</h3><p className="mt-1 text-xs text-[var(--text-secondary)]">{principal.principal_type}:{principal.external_id}</p></div><span className={`rounded-full px-2 py-1 text-[10px] ${principal.status === 'active' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-gray-500/10 text-gray-500'}`}>{principal.status}</span></div><p className="mt-3 text-xs text-[var(--text-secondary)]">来源 {principal.source} · 成员 {members.length} · 上级 {principal.parent_external_id || '—'}</p>{members.length > 0 && <div className="mt-3 flex flex-wrap gap-1.5">{members.slice(0, 6).map((member) => <span key={member.id} className="rounded-lg bg-[var(--surface-raised)] px-2 py-1 text-[10px]">{member.user_email}</span>)}</div>}</article>})}{principals.length === 0 && <Empty title="尚未同步企业目录" description="可以先创建部门、用户组或岗位，再将员工加入对应主体。" />}</div></section>
        </div>
        <section><div className="mb-3"><h2 className="font-medium">目录同步审计</h2><p className="text-xs text-[var(--text-secondary)]">记录来源、游标、权威同步模式和处理统计。</p></div><div className="overflow-x-auto rounded-2xl border border-[var(--border)] bg-[var(--surface)]"><table className="w-full min-w-[760px] text-left text-xs"><thead className="border-b border-[var(--border)] text-[var(--text-secondary)]"><tr><th className="px-4 py-3">时间</th><th className="px-4 py-3">来源</th><th className="px-4 py-3">状态</th><th className="px-4 py-3">主体</th><th className="px-4 py-3">成员</th><th className="px-4 py-3">未解析</th></tr></thead><tbody>{syncRuns.map((run) => <tr key={run.id} className="border-b border-[var(--border)] last:border-0"><td className="px-4 py-3">{formatTime(run.completed_at || run.started_at)}</td><td className="px-4 py-3">{run.provider}{run.authoritative ? ' · 权威' : ''}</td><td className="px-4 py-3">{run.status}</td><td className="px-4 py-3">+{run.stats.principals_created || 0} / 更新 {run.stats.principals_updated || 0}</td><td className="px-4 py-3">+{run.stats.memberships_created || 0} / 更新 {run.stats.memberships_updated || 0}</td><td className="px-4 py-3">用户 {run.stats.unresolved_users || 0} / 主体 {run.stats.unresolved_principals || 0}</td></tr>)}</tbody></table></div></section>
      </div>}
    </main>
  </div>
}

function OperationsOverview({ data, navigate }: { data: EnterpriseOperationsOverview; navigate: ReturnType<typeof useNavigate> }) {
  const dimensions = Object.entries(data.health.dimensions) as Array<[string, number]>
  const dimensionNames: Record<string, string> = {
    reliability: '执行可靠性', governance: '安全治理', knowledge: '知识健康', adoption: '员工采用',
  }
  const cards = [
    { label: '30 天活跃员工', value: data.adoption.active_users_30d, detail: `${data.adoption.active_goals} 个活跃 Goal`, icon: Users },
    { label: '24 小时 Responses', value: data.responses.total_24h, detail: `成功率 ${data.responses.success_rate}%`, icon: Activity },
    { label: '可信知识资产', value: data.assets.published_knowledge, detail: `${data.assets.due_reviews} 项到期复审`, icon: Database },
    { label: '组织成员关系', value: data.directory.memberships, detail: `${data.directory.principals} 个目录主体`, icon: Network },
  ]
  return (
    <div className="space-y-6">
      <section className="grid gap-5 rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 lg:grid-cols-[300px_1fr]">
        <div className="rounded-3xl bg-[var(--bg)] p-5">
          <div className="flex items-center justify-between">
            <div><p className="text-xs text-[var(--text-secondary)]">企业运行健康度</p><div className="mt-1 flex items-end gap-2"><span className={`text-5xl font-semibold ${tone(data.health.score)}`}>{data.health.score}</span><span className="mb-1 text-sm text-[var(--text-secondary)]">/100</span></div></div>
            <CircleGauge size={40} className={tone(data.health.score)} />
          </div>
          <p className="mt-2 text-xs text-[var(--text-secondary)]">{data.health.status}</p>
        </div>
        <div>
          <h2 className="text-xl font-semibold">用事实状态运营企业 AI，而不是只看服务是否在线。</h2>
          <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">当前统计限定在租户 <strong>{data.scope.tenant_id}</strong>、工作区 <strong>{data.scope.workspace_id}</strong>，覆盖采用、模型调用、知识治理、主动工作和风险积压。</p>
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            {dimensions.map(([key, value]) => <div key={key}><div className="mb-1 flex justify-between text-xs"><span>{dimensionNames[key]}</span><span>{value}</span></div><div className="h-2 overflow-hidden rounded-full bg-[var(--surface-raised)]"><div className="h-full rounded-full bg-[var(--accent)]" style={{ width: `${value}%` }} /></div></div>)}
          </div>
        </div>
      </section>
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map(({ label, value, detail, icon: Icon }) => <div key={label} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="grid h-9 w-9 place-items-center rounded-xl bg-[var(--accent-dim)] text-[var(--accent)]"><Icon size={17} /></div><div className="mt-4 text-2xl font-semibold">{value}</div><div className="text-sm">{label}</div><div className="mt-1 text-xs text-[var(--text-secondary)]">{detail}</div></div>)}
      </section>
      <div className="grid gap-6 xl:grid-cols-2">
        <section>
          <div className="mb-3"><h2 className="font-medium">风险与积压</h2><p className="text-xs text-[var(--text-secondary)]">直接跳转到对应员工面或治理控制面处理。</p></div>
          <div className="space-y-2">
            {data.risks.map((risk) => <button key={risk.code} onClick={() => navigate(risk.route)} className="flex w-full items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 text-left hover:border-[var(--accent)]/40"><div className={`grid h-9 w-9 place-items-center rounded-xl ${risk.severity === 'error' || risk.severity === 'critical' ? 'bg-red-500/10 text-red-500' : 'bg-amber-500/10 text-amber-500'}`}><AlertTriangle size={17} /></div><div className="flex-1"><h3 className="text-sm font-medium">{risk.title}</h3><p className="text-xs text-[var(--text-secondary)]">{risk.count} 项需要处理</p></div><ArrowRight size={14} /></button>)}
            {data.risks.length === 0 && <div className="rounded-2xl border border-dashed border-[var(--border)] p-8 text-center"><CheckCircle2 size={28} className="mx-auto text-emerald-500" /><p className="mt-3 text-sm font-medium">当前没有关键风险积压</p></div>}
          </div>
        </section>
        <section>
          <div className="mb-3"><h2 className="font-medium">Responses 运行质量</h2><p className="text-xs text-[var(--text-secondary)]">来自持久化 Response 与 ModelCall 账本。</p></div>
          <div className="grid grid-cols-2 gap-3"><Metric label="完成" value={data.responses.completed_24h} /><Metric label="失败" value={data.responses.failed_24h} /><Metric label="平均延迟" value={`${data.responses.avg_latency_ms}ms`} /><Metric label="P95 延迟" value={`${data.responses.p95_latency_ms}ms`} /><Metric label="输入 Tokens" value={data.responses.prompt_tokens_24h.toLocaleString()} /><Metric label="输出 Tokens" value={data.responses.completion_tokens_24h.toLocaleString()} /></div>
        </section>
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <section>
          <div className="mb-3"><h2 className="font-medium">模型使用</h2><p className="text-xs text-[var(--text-secondary)]">过去 24 小时按模型聚合调用、Token 和延迟。</p></div>
          <div className="overflow-x-auto rounded-2xl border border-[var(--border)] bg-[var(--surface)]"><table className="w-full min-w-[520px] text-left text-xs"><thead className="border-b border-[var(--border)] text-[var(--text-secondary)]"><tr><th className="px-4 py-3">模型</th><th className="px-4 py-3">调用</th><th className="px-4 py-3">输入</th><th className="px-4 py-3">输出</th><th className="px-4 py-3">平均延迟</th></tr></thead><tbody>{data.model_usage.map((item) => <tr key={item.model} className="border-b border-[var(--border)] last:border-0"><td className="px-4 py-3 font-medium">{item.model}</td><td className="px-4 py-3">{item.calls}</td><td className="px-4 py-3">{item.prompt_tokens}</td><td className="px-4 py-3">{item.completion_tokens}</td><td className="px-4 py-3">{item.avg_latency_ms}ms</td></tr>)}</tbody></table></div>
        </section>
        <section>
          <div className="mb-3"><h2 className="font-medium">企业资产与自动化</h2><p className="text-xs text-[var(--text-secondary)]">数据、知识、目录和主动工作覆盖度。</p></div>
          <div className="grid grid-cols-2 gap-3"><Metric label="有效数据源" value={`${data.assets.active_data_sources}/${data.assets.data_sources}`} /><Metric label="知识空间" value={data.assets.knowledge_spaces} /><Metric label="定时任务" value={data.adoption.scheduled_tasks} /><Metric label="主动预警" value={data.adoption.active_alerts} /><Metric label="待处理反馈" value={data.assets.unresolved_feedback} /><Metric label="未确认预警" value={data.alerts.unacknowledged} /></div>
          <button onClick={() => navigate('/work')} className="mt-3 inline-flex items-center gap-1 text-xs text-[var(--accent)]">进入员工工作台<ArrowRight size={12} /></button>
        </section>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string | number }) { return <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="text-xl font-semibold">{value}</div><div className="mt-1 text-xs text-[var(--text-secondary)]">{label}</div></div> }
function DirectoryStat({ icon: Icon, label, value }: { icon: typeof Building2; label: string; value: number }) { return <div className="flex items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="grid h-10 w-10 place-items-center rounded-xl bg-[var(--accent-dim)] text-[var(--accent)]"><Icon size={18} /></div><div><div className="text-2xl font-semibold">{value}</div><div className="text-xs text-[var(--text-secondary)]">{label}</div></div></div> }
function Empty({ title, description }: { title: string; description: string }) { return <div className="rounded-2xl border border-dashed border-[var(--border)] p-8 text-center"><ServerCog size={25} className="mx-auto text-[var(--text-secondary)]" /><p className="mt-3 text-sm font-medium">{title}</p><p className="mt-1 text-xs text-[var(--text-secondary)]">{description}</p></div> }
