import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  FileText,
  GitBranch,
  Loader2,
  MessageSquareWarning,
  Network,
  Play,
  Plug,
  RefreshCw,
  Save,
  ScanLine,
  ShieldCheck,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import {
  apiApproveKnowledgeRule,
  apiCreateEnterpriseKnowledgeConnector,
  apiCreateKnowledgeRule,
  apiDecideKnowledgeReview,
  apiGetKnowledgeGovernanceHealth,
  apiGetKnowledgeGraph,
  apiGrantKnowledgeSpaceMember,
  apiListEnterpriseKnowledgeConnectors,
  apiListKnowledgeFeedback,
  apiListKnowledgeJobs,
  apiListKnowledgeLintIssues,
  apiListKnowledgeMergeCases,
  apiListKnowledgePages,
  apiListKnowledgeReviews,
  apiListKnowledgeRules,
  apiListKnowledgeSources,
  apiListKnowledgeSpaceMembers,
  apiListKnowledgeSpaces,
  apiListKnowledgeSyncRunItems,
  apiListKnowledgeSyncRuns,
  apiListProjects,
  apiOrchestrateKnowledge,
  apiReconcileDueKnowledgeReviews,
  apiResolveKnowledgeFeedback,
  apiResolveKnowledgeMergeCase,
  apiRetryKnowledgeSyncRun,
  apiSyncDingTalkKnowledgeConnector,
  apiRunKnowledgeLint,
  apiRevokeKnowledgeSpaceMember,
  apiWithdrawKnowledgeSource,
  type EnterpriseKnowledgeConnectorItem,
  type KnowledgeFeedbackItem,
  type KnowledgeGovernanceHealth,
  type KnowledgeGraphData,
  type KnowledgeJobItem,
  type KnowledgeLintIssueItem,
  type KnowledgeMergeCaseItem,
  type KnowledgePageItem,
  type KnowledgeReviewItem,
  type KnowledgeRuleItem,
  type KnowledgeSourceItem,
  type KnowledgeSpaceItem,
  type KnowledgeSpaceMemberItem,
  type KnowledgeSyncItem,
  type KnowledgeSyncRunItem,
  type ProjectItem,
} from '../api/client'
import { useAuthStore } from '../store/auth'
import { useChatPreferences } from '../store/chatPreferences'

type GovernanceTab = 'pipeline' | 'reviews' | 'quality' | 'connectors' | 'access'
type NetworkType = KnowledgeGraphData['network']

const NETWORK_LABELS: Record<NetworkType, string> = {
  entity: '实体图谱',
  dependency: '依赖关系',
  provenance: '来源网络',
}

export default function KnowledgeCenterPage({ onBack }: { onBack?: () => void }) {
  const token = useAuthStore((state) => state.token)!
  const selectedProjectId = useChatPreferences((state) => state.projectId)
  const setSelectedProjectId = useChatPreferences((state) => state.setProjectId)
  const [tab, setTab] = useState<GovernanceTab>('pipeline')
  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [spaces, setSpaces] = useState<KnowledgeSpaceItem[]>([])
  const [selectedSpaceId, setSelectedSpaceId] = useState('')
  const [network, setNetwork] = useState<NetworkType>('entity')
  const [graph, setGraph] = useState<KnowledgeGraphData>({ network: 'entity', nodes: [], edges: [] })
  const [sources, setSources] = useState<KnowledgeSourceItem[]>([])
  const [pages, setPages] = useState<KnowledgePageItem[]>([])
  const [jobs, setJobs] = useState<KnowledgeJobItem[]>([])
  const [rules, setRules] = useState<KnowledgeRuleItem[]>([])
  const [reviews, setReviews] = useState<KnowledgeReviewItem[]>([])
  const [health, setHealth] = useState<KnowledgeGovernanceHealth | null>(null)
  const [feedback, setFeedback] = useState<KnowledgeFeedbackItem[]>([])
  const [lintIssues, setLintIssues] = useState<KnowledgeLintIssueItem[]>([])
  const [mergeCases, setMergeCases] = useState<KnowledgeMergeCaseItem[]>([])
  const [members, setMembers] = useState<KnowledgeSpaceMemberItem[]>([])
  const [connectors, setConnectors] = useState<EnterpriseKnowledgeConnectorItem[]>([])
  const [syncRuns, setSyncRuns] = useState<KnowledgeSyncRunItem[]>([])
  const [syncItems, setSyncItems] = useState<Record<string, KnowledgeSyncItem[]>>({})
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [message, setMessage] = useState('')
  const [ruleConfig, setRuleConfig] = useState({ summary_length: 420, content_limit: 16000, min_claim_length: 8, max_claims_per_page: 12 })
  const [ruleInstructions, setRuleInstructions] = useState('按标题拆分知识页面，所有事实保留原文证据；优先建立明确依赖和实体引用。')
  const [connectorName, setConnectorName] = useState('')
  const [connectorType, setConnectorType] = useState('push')
  const [memberType, setMemberType] = useState<KnowledgeSpaceMemberItem['subject_type']>('user')
  const [memberId, setMemberId] = useState('')
  const [memberRole, setMemberRole] = useState<KnowledgeSpaceMemberItem['role']>('viewer')

  const selectedSpace = useMemo(
    () => spaces.find((space) => space.id === selectedSpaceId) ?? null,
    [selectedSpaceId, spaces],
  )
  const canReview = selectedSpace
    ? ['reviewer', 'publisher', 'admin'].includes(selectedSpace.role)
    : reviews.length > 0
  const canAdmin = selectedSpace?.role === 'admin'
  const hasActiveJobs = jobs.some((job) => ['pending', 'running'].includes(job.status))
  const hasActiveSync = syncRuns.some((run) => ['pending', 'running'].includes(run.status))

  const loadPipeline = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [nextGraph, nextSources, publishedPages, reviewPages, nextJobs, nextRules] = await Promise.all([
        apiGetKnowledgeGraph(token, network, selectedProjectId),
        apiListKnowledgeSources(token, { projectId: selectedProjectId, spaceId: selectedSpaceId || null }),
        apiListKnowledgePages(token, selectedProjectId, 'published'),
        apiListKnowledgePages(token, selectedProjectId, 'review'),
        apiListKnowledgeJobs(token, selectedProjectId),
        apiListKnowledgeRules(token, selectedProjectId),
      ])
      setGraph(nextGraph)
      setSources(nextSources)
      setPages([...publishedPages, ...reviewPages])
      setJobs(nextJobs)
      setRules(nextRules)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      if (!silent) setLoading(false)
    }
  }, [network, selectedProjectId, selectedSpaceId, token])

  const loadGovernance = useCallback(async () => {
    try {
      const nextReviews = await apiListKnowledgeReviews(token, 'pending', selectedSpaceId || null)
      setReviews(nextReviews)
      if (!selectedSpaceId) {
        setMembers([])
        setConnectors([])
        setSyncRuns([])
        return
      }
      const space = spaces.find((item) => item.id === selectedSpaceId)
      const tasks: Promise<unknown>[] = [
        apiListEnterpriseKnowledgeConnectors(token, selectedSpaceId).then(setConnectors),
        apiListKnowledgeSyncRuns(token, undefined, selectedSpaceId).then(setSyncRuns),
      ]
      if (space?.role === 'admin') {
        tasks.push(apiListKnowledgeSpaceMembers(token, selectedSpaceId).then(setMembers))
      } else {
        setMembers([])
      }
      await Promise.all(tasks)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }, [selectedSpaceId, spaces, token])

  const loadQuality = useCallback(async () => {
    const space = spaces.find((item) => item.id === selectedSpaceId)
    if (!space || !['reviewer', 'publisher', 'admin'].includes(space.role)) {
      setHealth(null)
      setFeedback([])
      setLintIssues([])
      setMergeCases([])
      return
    }
    try {
      const [nextHealth, nextFeedback, nextLintIssues, nextMergeCases] = await Promise.all([
        apiGetKnowledgeGovernanceHealth(token, selectedSpaceId),
        apiListKnowledgeFeedback(token, selectedSpaceId, false),
        apiListKnowledgeLintIssues(token, 'open', selectedSpaceId),
        apiListKnowledgeMergeCases(token, 'open', selectedSpaceId),
      ])
      setHealth(nextHealth)
      setFeedback(nextFeedback)
      setLintIssues(nextLintIssues)
      setMergeCases(nextMergeCases)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }, [selectedSpaceId, spaces, token])

  useEffect(() => {
    void Promise.all([apiListProjects(token), apiListKnowledgeSpaces(token)]).then(([nextProjects, nextSpaces]) => {
      setProjects(nextProjects)
      setSpaces(nextSpaces)
      setSelectedSpaceId((current) => current || nextSpaces.find((space) => ['reviewer', 'publisher', 'admin'].includes(space.role))?.id || nextSpaces[0]?.id || '')
    })
  }, [token])
  useEffect(() => { void loadPipeline() }, [loadPipeline])
  useEffect(() => { void loadGovernance() }, [loadGovernance])
  useEffect(() => { void loadQuality() }, [loadQuality])
  useEffect(() => {
    if (!hasActiveJobs && !hasActiveSync) return
    const timer = window.setInterval(() => {
      if (hasActiveJobs) void loadPipeline(true)
      if (hasActiveSync) void loadGovernance()
    }, 2500)
    return () => window.clearInterval(timer)
  }, [hasActiveJobs, hasActiveSync, loadGovernance, loadPipeline])

  async function orchestrate() {
    setWorking(true)
    setMessage('')
    try {
      const result = await apiOrchestrateKnowledge(token, selectedProjectId)
      setMessage(`已提交知识编排：${String(result.queued ?? 0)} 个任务进入队列`)
      await loadPipeline(true)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setWorking(false)
    }
  }

  async function saveRule() {
    setWorking(true)
    try {
      const created = await apiCreateKnowledgeRule(token, {
        rule_key: 'knowledge_page_compiler',
        project_id: selectedProjectId || null,
        rule_type: 'schema',
        schema_json: ruleConfig,
        instructions: ruleInstructions,
        provenance: { source: 'governance_ui' },
      })
      await apiApproveKnowledgeRule(token, created.id)
      setMessage('编排规则新版本已发布')
      await loadPipeline(true)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setWorking(false)
    }
  }

  async function decide(review: KnowledgeReviewItem, decision: 'approve' | 'reject') {
    const comment = decision === 'reject' ? window.prompt('请输入驳回原因') : ''
    if (decision === 'reject' && !comment?.trim()) return
    setWorking(true)
    try {
      await apiDecideKnowledgeReview(token, review.id, decision, comment || '')
      setMessage(decision === 'approve' ? '知识版本已审核发布' : '知识版本已驳回')
      await Promise.all([loadGovernance(), loadPipeline(true)])
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setWorking(false)
    }
  }

  async function withdrawSource(source: KnowledgeSourceItem) {
    const reason = window.prompt('请输入撤回原因。撤回后已发布版本和派生知识将立即归档。')
    if (!reason?.trim()) return
    setWorking(true)
    try {
      await apiWithdrawKnowledgeSource(token, source.id, reason.trim())
      setMessage('知识来源已撤回，原始资料和历史版本继续保留用于审计。')
      await loadPipeline(true)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setWorking(false)
    }
  }

  async function reconcileDueReviews() {
    if (!selectedSpace) return
    setWorking(true)
    try {
      const result = await apiReconcileDueKnowledgeReviews(token, selectedSpace.id)
      setMessage(`复审扫描完成：扫描 ${result.scanned}，重新进入队列 ${result.reopened}`)
      await Promise.all([loadGovernance(), loadQuality(), loadPipeline(true)])
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setWorking(false)
    }
  }

  async function runLint() {
    setWorking(true)
    try {
      const result = await apiRunKnowledgeLint(token, selectedSpace?.id)
      setMessage(`知识质量检查完成，发现 ${result.open_count} 个开放问题`)
      await loadQuality()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setWorking(false)
    }
  }

  async function resolveFeedback(item: KnowledgeFeedbackItem, resolution: 'acknowledged' | 'needs_revision' | 'dismissed') {
    const comment = window.prompt('处理说明（可选）') || ''
    setWorking(true)
    try {
      await apiResolveKnowledgeFeedback(token, item.id, resolution, comment)
      setMessage('知识反馈已处理并记录治理审计信息')
      await loadQuality()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setWorking(false)
    }
  }

  async function keepMergeCaseSeparate(item: KnowledgeMergeCaseItem) {
    setWorking(true)
    try {
      await apiResolveKnowledgeMergeCase(token, item.id, { action: 'keep_separate' }, selectedSpace?.id)
      setMessage('知识冲突已人工确认保持独立')
      await loadQuality()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setWorking(false)
    }
  }

  async function mergeKnowledgeCase(item: KnowledgeMergeCaseItem) {
    if (!item.candidates.length) {
      setMessage('当前冲突缺少可合并的候选事实')
      return
    }
    const options = item.candidates.map((candidate, index) => `${index + 1}. ${candidate.text.slice(0, 80)}`).join('\n')
    const selected = Number(window.prompt(`请选择要保留的候选序号：\n${options}`, '1'))
    if (!Number.isInteger(selected) || selected < 1 || selected > item.candidates.length) return
    const candidate = item.candidates[selected - 1]
    const mergedText = window.prompt('可输入合并后的事实文本；留空则沿用所选候选', candidate.text)?.trim() || ''
    setWorking(true)
    try {
      await apiResolveKnowledgeMergeCase(token, item.id, {
        action: 'merge',
        keep_claim_id: candidate.id,
        merged_text: mergedText,
      }, selectedSpace?.id)
      setMessage('知识冲突已合并，未保留候选已归档并保留审计链路')
      await Promise.all([loadQuality(), loadPipeline(true)])
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setWorking(false)
    }
  }

  async function createConnector() {
    if (!selectedSpace || !connectorName.trim()) return
    setWorking(true)
    try {
      await apiCreateEnterpriseKnowledgeConnector(token, {
        space_id: selectedSpace.id,
        name: connectorName.trim(),
        connector_type: connectorType,
        config: connectorType === 'dingtalk' ? {
          root_department_id: '1',
          chat_since_days: 30,
          directory_authoritative: false,
        } : {},
      })
      setConnectorName('')
      setMessage('连接器已创建')
      await loadGovernance()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setWorking(false)
    }
  }

  async function syncDingTalk(connector: EnterpriseKnowledgeConnectorItem) {
    setWorking(true)
    setMessage('')
    try {
      const result = await apiSyncDingTalkKnowledgeConnector(token, connector.id)
      setMessage(`钉钉同步已接入治理链：文档 ${result.documents}、群聊 ${result.chats}、部门 ${result.departments}、成员关系 ${result.memberships}`)
      await loadGovernance()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setWorking(false)
    }
  }

  async function toggleRun(run: KnowledgeSyncRunItem) {
    if (expandedRunId === run.id) {
      setExpandedRunId(null)
      return
    }
    setExpandedRunId(run.id)
    if (!syncItems[run.id]) {
      try {
        const nextItems = await apiListKnowledgeSyncRunItems(token, run.id)
        setSyncItems((current) => ({ ...current, [run.id]: nextItems }))
      } catch (error) {
        setMessage(error instanceof Error ? error.message : String(error))
      }
    }
  }

  async function retryRun(run: KnowledgeSyncRunItem) {
    setWorking(true)
    try {
      const result = await apiRetryKnowledgeSyncRun(token, run.id)
      setMessage(`已重新入队 ${result.requeued} 个失败项`)
      setSyncItems((current) => { const next = { ...current }; delete next[run.id]; return next })
      await loadGovernance()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setWorking(false)
    }
  }

  async function grantMember() {
    if (!selectedSpace || !memberId.trim()) return
    setWorking(true)
    try {
      await apiGrantKnowledgeSpaceMember(token, selectedSpace.id, {
        subject_type: memberType,
        subject_id: memberId.trim(),
        role: memberRole,
      })
      setMemberId('')
      setMessage('知识空间授权已更新')
      await loadGovernance()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setWorking(false)
    }
  }

  async function revokeMember(member: KnowledgeSpaceMemberItem) {
    if (!selectedSpace || !confirm(`确认撤销 ${member.subject_type}:${member.subject_id} 的访问权限？`)) return
    try {
      await apiRevokeKnowledgeSpaceMember(token, selectedSpace.id, member.id)
      await loadGovernance()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  return (
    <div className="min-h-full bg-[var(--bg)] text-[var(--text)]">
      <header className="sticky top-0 z-10 flex flex-wrap items-center gap-3 border-b border-[var(--border)] bg-[var(--bg)]/95 px-6 py-4 backdrop-blur">
        <button onClick={onBack} className="rounded-lg p-2 hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
        <div className="min-w-52 flex-1"><h1 className="text-lg font-semibold">知识库质量中心</h1><p className="text-xs text-[var(--text-secondary)]">编排、审核、连接器、质量与访问控制的管理员控制面</p></div>
        <select value={selectedProjectId || ''} onChange={(event) => setSelectedProjectId(event.target.value || null)} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs"><option value="">工作区默认</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select>
        <select value={selectedSpaceId} onChange={(event) => setSelectedSpaceId(event.target.value)} className="max-w-56 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs"><option value="">我的非空间知识</option>{spaces.map((space) => <option key={space.id} value={space.id}>{space.name} · {space.role}</option>)}</select>
        <button onClick={() => { void loadPipeline(); void loadGovernance(); void loadQuality() }} className="rounded-xl border border-[var(--border)] p-2" title="刷新"><RefreshCw size={15} /></button>
      </header>

      <main className="mx-auto max-w-7xl space-y-5 p-6">
        {message && <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm">{message}</div>}
        <nav className="grid gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-1 sm:grid-cols-5">
          <TabButton active={tab === 'pipeline'} onClick={() => setTab('pipeline')} icon={<Network size={14} />} label="知识编排" />
          <TabButton active={tab === 'reviews'} onClick={() => setTab('reviews')} icon={<ShieldCheck size={14} />} label={`审核队列 ${reviews.length}`} />
          <TabButton active={tab === 'quality'} onClick={() => setTab('quality')} icon={<Activity size={14} />} label={`质量与反馈 ${feedback.length}`} />
          <TabButton active={tab === 'connectors'} onClick={() => setTab('connectors')} icon={<Plug size={14} />} label="连接器与同步" />
          <TabButton active={tab === 'access'} onClick={() => setTab('access')} icon={<Users size={14} />} label="空间访问控制" />
        </nav>

        {tab === 'pipeline' && (
          <div className="space-y-5">
            <section className="grid gap-3 md:grid-cols-5"><Metric label="知识来源" value={sources.length} /><Metric label="已发布页面" value={pages.filter((page) => page.status === 'published').length} /><Metric label="待审核页面" value={pages.filter((page) => page.status === 'review').length} /><Metric label="活跃任务" value={jobs.filter((job) => ['pending', 'running'].includes(job.status)).length} /><Metric label="规则版本" value={rules.length} /></section>
            <section className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div><h2 className="font-semibold">编排控制</h2><p className="mt-1 text-xs text-[var(--text-secondary)]">资料上传统一在“我的资料”完成；治理中心只处理已登记来源。</p></div><button onClick={() => void orchestrate()} disabled={working} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-40">{working ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}立即编排</button></section>
            <div className="grid gap-5 xl:grid-cols-[1.4fr_0.8fr]">
              <GraphPanel graph={graph} network={network} onNetwork={setNetwork} loading={loading} />
              <div className="space-y-5"><SourceList sources={sources} canWithdraw={Boolean(selectedSpace && ['publisher', 'admin'].includes(selectedSpace.role))} working={working} onWithdraw={withdrawSource} /><JobList jobs={jobs} /></div>
            </div>
            <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-center justify-between"><div><h2 className="font-semibold">版本化编排规则</h2><p className="mt-1 text-xs text-[var(--text-secondary)]">保存后生成并批准新规则版本，不直接修改历史版本。</p></div><Save size={17} className="text-[var(--accent)]" /></div><textarea value={ruleInstructions} onChange={(event) => setRuleInstructions(event.target.value)} className="mt-4 min-h-24 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 text-sm" /><div className="mt-3 grid gap-2 sm:grid-cols-4">{Object.entries(ruleConfig).map(([key, value]) => <label key={key} className="text-[11px] text-[var(--text-secondary)]">{key}<input type="number" value={value} onChange={(event) => setRuleConfig((current) => ({ ...current, [key]: Number(event.target.value) }))} className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-2 text-sm text-[var(--text)]" /></label>)}</div><button onClick={() => void saveRule()} disabled={working} className="mt-4 inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-40"><Save size={14} />保存并发布新版本</button></section>
          </div>
        )}

        {tab === 'reviews' && <ReviewPanel reviews={reviews} canReview={canReview} working={working} onDecision={decide} />}
        {tab === 'quality' && <QualityPanel selectedSpace={selectedSpace} health={health} feedback={feedback} lintIssues={lintIssues} mergeCases={mergeCases} working={working} onReconcile={reconcileDueReviews} onLint={runLint} onResolveFeedback={resolveFeedback} onKeepSeparate={keepMergeCaseSeparate} onMerge={mergeKnowledgeCase} />}
        {tab === 'connectors' && <ConnectorPanel selectedSpace={selectedSpace} connectors={connectors} runs={syncRuns} items={syncItems} expandedRunId={expandedRunId} working={working} name={connectorName} type={connectorType} onName={setConnectorName} onType={setConnectorType} onCreate={createConnector} onSyncDingTalk={syncDingTalk} onToggle={toggleRun} onRetry={retryRun} />}
        {tab === 'access' && <AccessPanel selectedSpace={selectedSpace} canAdmin={canAdmin} members={members} subjectType={memberType} subjectId={memberId} role={memberRole} working={working} onSubjectType={setMemberType} onSubjectId={setMemberId} onRole={setMemberRole} onGrant={grantMember} onRevoke={revokeMember} />}
      </main>
    </div>
  )
}

function QualityPanel({ selectedSpace, health, feedback, lintIssues, mergeCases, working, onReconcile, onLint, onResolveFeedback, onKeepSeparate, onMerge }: { selectedSpace: KnowledgeSpaceItem | null; health: KnowledgeGovernanceHealth | null; feedback: KnowledgeFeedbackItem[]; lintIssues: KnowledgeLintIssueItem[]; mergeCases: KnowledgeMergeCaseItem[]; working: boolean; onReconcile: () => Promise<void>; onLint: () => Promise<void>; onResolveFeedback: (item: KnowledgeFeedbackItem, resolution: 'acknowledged' | 'needs_revision' | 'dismissed') => Promise<void>; onKeepSeparate: (item: KnowledgeMergeCaseItem) => Promise<void>; onMerge: (item: KnowledgeMergeCaseItem) => Promise<void> }) {
  if (!selectedSpace || !['reviewer', 'publisher', 'admin'].includes(selectedSpace.role)) {
    return <section className="rounded-2xl border border-dashed border-[var(--border)] p-12 text-center text-sm text-[var(--text-secondary)]">请选择具有 Reviewer 及以上角色的知识空间</section>
  }
  const metrics = health?.metrics || {}
  return <div className="space-y-5">
    <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5"><div className="flex flex-wrap items-center justify-between gap-4"><div><div className="flex items-center gap-3"><div className={clsx('grid h-16 w-16 place-items-center rounded-2xl text-2xl font-semibold', health?.status === 'critical' ? 'bg-red-500/10 text-red-500' : health?.status === 'attention' ? 'bg-amber-500/10 text-amber-500' : 'bg-emerald-500/10 text-emerald-500')}>{health?.score ?? '—'}</div><div><h2 className="font-semibold">治理健康分</h2><p className="mt-1 text-xs text-[var(--text-secondary)]">综合复审、有效期、质量问题、员工反馈、冲突与连接器状态</p></div></div></div><div className="flex gap-2"><button onClick={() => void onReconcile()} disabled={working} className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] px-3 py-2 text-xs disabled:opacity-40"><ScanLine size={14} />扫描到期复审</button><button onClick={() => void onLint()} disabled={working} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-3 py-2 text-xs text-[var(--accent-foreground)] disabled:opacity-40">{working ? <Loader2 size={14} className="animate-spin" /> : <Activity size={14} />}执行质量检查</button></div></div><div className="mt-5 grid gap-3 sm:grid-cols-4 xl:grid-cols-8"><Metric label="已发布来源" value={metrics.published_sources ?? 0} /><Metric label="到期复审" value={metrics.due_reviews ?? 0} /><Metric label="复审阻塞" value={metrics.blocked_reviews ?? 0} /><Metric label="已过期来源" value={metrics.expired_sources ?? 0} /><Metric label="来源不同步" value={metrics.stale_sources ?? 0} /><Metric label="失败任务" value={metrics.failed_jobs ?? 0} /><Metric label="开放质量问题" value={metrics.open_lint_issues ?? 0} /><Metric label="连接器异常/滞后" value={(metrics.failed_connectors ?? 0) + (metrics.stale_connectors ?? 0)} /></div></section>
    <div className="grid gap-5 xl:grid-cols-2">
      <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><h2 className="flex items-center gap-2 font-semibold"><MessageSquareWarning size={16} />员工反馈 · {feedback.length}</h2><div className="mt-3 max-h-[520px] space-y-2 overflow-auto">{feedback.map((item) => <article key={item.id} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3"><div className="flex items-start justify-between gap-2"><div><h3 className="text-sm font-medium">{item.source_title}</h3><p className="mt-1 text-xs text-[var(--text-secondary)]">{item.feedback_type} · {item.target_type} · {item.created_at ? new Date(item.created_at).toLocaleString() : '—'}</p></div>{['incorrect', 'outdated', 'correction'].includes(item.feedback_type) && <AlertTriangle size={15} className="text-amber-500" />}</div>{item.correction && <p className="mt-2 rounded-lg bg-[var(--surface)] p-2 text-xs leading-5">{item.correction}</p>}<div className="mt-3 flex flex-wrap gap-1.5"><button disabled={working} onClick={() => void onResolveFeedback(item, 'acknowledged')} className="rounded-lg border border-[var(--border)] px-2 py-1 text-[11px]">已确认</button><button disabled={working} onClick={() => void onResolveFeedback(item, 'needs_revision')} className="rounded-lg bg-amber-500/10 px-2 py-1 text-[11px] text-amber-500">需要修订</button><button disabled={working} onClick={() => void onResolveFeedback(item, 'dismissed')} className="rounded-lg px-2 py-1 text-[11px] text-[var(--text-secondary)]">忽略</button></div></article>)}{!feedback.length && <p className="py-10 text-center text-xs text-[var(--text-secondary)]">暂无未处理员工反馈</p>}</div></section>
      <div className="space-y-5"><section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><h2 className="flex items-center gap-2 font-semibold"><AlertTriangle size={16} />质量问题 · {lintIssues.length}</h2><div className="mt-3 max-h-64 space-y-2 overflow-auto">{lintIssues.map((issue) => <article key={issue.id} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3"><div className="flex items-center justify-between gap-2"><span className="text-sm font-medium">{issue.code}</span><span className={clsx('rounded-full px-2 py-0.5 text-[10px]', issue.severity === 'error' ? 'bg-red-500/10 text-red-500' : 'bg-amber-500/10 text-amber-500')}>{issue.severity}</span></div><p className="mt-1 text-xs leading-5 text-[var(--text-secondary)]">{issue.message}</p></article>)}{!lintIssues.length && <p className="py-8 text-center text-xs text-[var(--text-secondary)]">暂无开放质量问题</p>}</div></section><section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><h2 className="flex items-center gap-2 font-semibold"><GitBranch size={16} />知识冲突 · {mergeCases.length}</h2><div className="mt-3 max-h-64 space-y-2 overflow-auto">{mergeCases.map((item) => <article key={item.id} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3"><p className="text-sm font-medium">{item.entity_key}</p><p className="mt-1 text-xs text-[var(--text-secondary)]">{item.conflict_type} · {item.candidate_ids.length} 个候选</p><div className="mt-2 space-y-1.5">{item.candidates.map((candidate, index) => <div key={candidate.id} className="rounded-lg bg-[var(--surface)] p-2"><p className="line-clamp-2 text-xs leading-5">{index + 1}. {candidate.text}</p><p className="mt-1 text-[10px] text-[var(--text-secondary)]">{candidate.source_title} / {candidate.page_title} · {candidate.authority} · {candidate.confidence.toFixed(2)}</p></div>)}</div><div className="mt-2 flex flex-wrap gap-1.5"><button disabled={working || !item.candidates.length} onClick={() => void onMerge(item)} className="rounded-lg bg-[var(--accent)] px-2 py-1 text-[11px] text-[var(--accent-foreground)] disabled:opacity-40">选择并合并</button><button disabled={working} onClick={() => void onKeepSeparate(item)} className="rounded-lg border border-[var(--border)] px-2 py-1 text-[11px]">保持独立</button></div></article>)}{!mergeCases.length && <p className="py-8 text-center text-xs text-[var(--text-secondary)]">暂无待处理知识冲突</p>}</div></section></div>
    </div>
  </div>
}

function TabButton({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return <button onClick={onClick} className={clsx('flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm', active ? 'bg-[var(--accent-dim)] text-[var(--accent)]' : 'text-[var(--text-secondary)] hover:bg-[var(--bg)]')}>{icon}{label}</button>
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="text-2xl font-semibold">{value}</div><div className="mt-1 text-xs text-[var(--text-secondary)]">{label}</div></div>
}

function GraphPanel({ graph, network, onNetwork, loading }: { graph: KnowledgeGraphData; network: NetworkType; onNetwork: (value: NetworkType) => void; loading: boolean }) {
  const nodes = graph.nodes.slice(0, 100)
  const positions = useMemo(() => new Map(nodes.map((node, index) => { const angle = index / Math.max(1, nodes.length) * Math.PI * 2; const ring = 150 + index % 3 * 35; return [node.id, { x: 450 + Math.cos(angle) * ring, y: 250 + Math.sin(angle) * ring }] })), [nodes])
  const ids = new Set(nodes.map((node) => node.id))
  const edges = graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)).slice(0, 240)
  return <section className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)]"><header className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] p-4"><div><h2 className="font-semibold">知识关系图</h2><p className="mt-1 text-xs text-[var(--text-secondary)]">Page、Claim、Relation 与来源的可追溯结构</p></div><select value={network} onChange={(event) => onNetwork(event.target.value as NetworkType)} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-xs">{Object.entries(NETWORK_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></header><div className="relative h-[500px]">{loading && <div className="absolute inset-0 z-10 grid place-items-center bg-[var(--surface)]"><Loader2 className="animate-spin" /></div>}{!loading && !nodes.length && <div className="grid h-full place-items-center text-sm text-[var(--text-secondary)]">暂无{NETWORK_LABELS[network]}数据</div>}<svg viewBox="0 0 900 500" className="h-full w-full">{edges.map((edge) => { const a = positions.get(edge.source); const b = positions.get(edge.target); return a && b ? <line key={edge.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="var(--border)" strokeWidth="1.5" /> : null })}{nodes.map((node) => { const point = positions.get(node.id)!; const color = node.type === 'source' ? '#f59e0b' : node.type === 'claim' ? '#10b981' : '#6366f1'; return <g key={node.id}><circle cx={point.x} cy={point.y} r={node.type === 'source' ? 10 : 7} fill={color}><title>{node.label}</title></circle><text x={point.x} y={point.y + 18} textAnchor="middle" fontSize="9" fill="var(--text-secondary)">{node.label.slice(0, 12)}</text></g> })}</svg><div className="absolute bottom-3 right-4 text-[11px] text-[var(--text-secondary)]">{graph.nodes.length} 节点 · {graph.edges.length} 关系</div></div></section>
}

function SourceList({ sources, canWithdraw, working, onWithdraw }: { sources: KnowledgeSourceItem[]; canWithdraw: boolean; working: boolean; onWithdraw: (source: KnowledgeSourceItem) => Promise<void> }) {
  return <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><h2 className="flex items-center gap-2 font-semibold"><FileText size={15} />知识来源</h2><div className="mt-3 max-h-72 space-y-2 overflow-auto">{sources.map((source) => <article key={source.id} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3"><div className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate text-sm font-medium">{source.title}</span><Status value={source.status} />{canWithdraw && source.status !== 'deprecated' && <button onClick={() => void onWithdraw(source)} disabled={working} className="rounded-lg px-2 py-1 text-[11px] text-red-500 hover:bg-red-500/10 disabled:opacity-40">撤回</button>}</div><p className="mt-1 text-[11px] text-[var(--text-secondary)]">{source.source_system || source.source_type} · {source.classification || 'internal'} · {source.sync_status || 'current'}</p></article>)}{!sources.length && <p className="py-6 text-center text-xs text-[var(--text-secondary)]">当前范围暂无知识来源</p>}</div></section>
}

export function formatKnowledgeJobError(error: string): string {
  const normalized = error.toLowerCase()
  if (normalized.includes('transaction has been rolled back') || normalized.includes('stringdatarighttruncation')) {
    return '历史编排任务失败：治理校验未完成，请清理失败任务后重新编排。'
  }
  if (error.startsWith('knowledge_compilation_failed:')) {
    return `知识编排失败（${error.split(':', 2)[1] || 'unknown'}），请重新编排或联系管理员查看服务日志。`
  }
  return '知识编排失败，请重新编排；如仍失败，请联系管理员查看服务日志。'
}


function JobList({ jobs }: { jobs: KnowledgeJobItem[] }) {
  return <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><h2 className="flex items-center gap-2 font-semibold"><GitBranch size={15} />最近编排任务</h2><div className="mt-3 max-h-72 space-y-2 overflow-auto">{jobs.slice(0, 20).map((job) => <article key={job.id} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3"><div className="flex items-center justify-between"><span className="font-mono text-[11px]">{job.id.slice(0, 10)}</span><Status value={job.status} /></div>{job.error && <p className="mt-2 text-xs text-red-500">{formatKnowledgeJobError(job.error)}</p>}</article>)}{!jobs.length && <p className="py-6 text-center text-xs text-[var(--text-secondary)]">暂无编排任务</p>}</div></section>
}

function ReviewPanel({ reviews, canReview, working, onDecision }: { reviews: KnowledgeReviewItem[]; canReview: boolean; working: boolean; onDecision: (review: KnowledgeReviewItem, decision: 'approve' | 'reject') => Promise<void> }) {
  if (!canReview) return <Empty text="当前账号在所选空间没有 reviewer 权限" />
  const reasonLabel: Record<string, string> = { content_change: '内容变更', scheduled_recertification: '周期复审', feedback_resolution: '员工反馈触发' }
  return <section className="space-y-3">{reviews.map((review) => <article key={review.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5"><div className="flex items-start justify-between gap-4"><div><div className="flex flex-wrap items-center gap-2"><h2 className="font-semibold">{review.source_title || '待审核知识版本'}</h2><span className="rounded-full bg-amber-500/10 px-2 py-1 text-[10px] text-amber-500">{reasonLabel[review.review_reason || 'content_change'] || review.review_reason}</span></div><p className="mt-1 text-xs text-[var(--text-secondary)]">版本 v{review.version_number} · {review.source_system || '企业知识'} · {review.classification || 'internal'} · {review.authority || 'contextual'}</p><p className="mt-3 text-sm text-[var(--text-secondary)]">页面 {String(review.diff_summary.pages ?? 0)} · 事实 {String(review.diff_summary.claims ?? 0)} · 关系 {String(review.diff_summary.relations ?? 0)} · 复审日期 {review.review_due_at ? new Date(review.review_due_at).toLocaleDateString() : '—'}</p><p className="mt-2 font-mono text-[10px] text-[var(--text-secondary)]">Source {review.source_id} · Version {review.source_version_id}</p></div><ShieldCheck className="text-amber-500" /></div><div className="mt-4 flex justify-end gap-2"><button onClick={() => void onDecision(review, 'reject')} disabled={working} className="inline-flex items-center gap-1 rounded-xl border border-red-500/30 px-3 py-2 text-sm text-red-500"><X size={14} />驳回</button><button onClick={() => void onDecision(review, 'approve')} disabled={working} className="inline-flex items-center gap-1 rounded-xl bg-emerald-600 px-3 py-2 text-sm text-white"><Check size={14} />审核并发布</button></div></article>)}{!reviews.length && <Empty text="没有待审核知识版本" />}</section>
}

function ConnectorPanel({ selectedSpace, connectors, runs, items, expandedRunId, working, name, type, onName, onType, onCreate, onSyncDingTalk, onToggle, onRetry }: { selectedSpace: KnowledgeSpaceItem | null; connectors: EnterpriseKnowledgeConnectorItem[]; runs: KnowledgeSyncRunItem[]; items: Record<string, KnowledgeSyncItem[]>; expandedRunId: string | null; working: boolean; name: string; type: string; onName: (value: string) => void; onType: (value: string) => void; onCreate: () => Promise<void>; onSyncDingTalk: (connector: EnterpriseKnowledgeConnectorItem) => Promise<void>; onToggle: (run: KnowledgeSyncRunItem) => Promise<void>; onRetry: (run: KnowledgeSyncRunItem) => Promise<void> }) {
  if (!selectedSpace) return <Empty text="请选择知识空间后管理连接器" />
  return <div className="space-y-5"><section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex flex-wrap gap-2"><input value={name} onChange={(event) => onName(event.target.value)} placeholder="连接器名称" className="min-w-52 flex-1 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" /><select value={type} onChange={(event) => onType(event.target.value)} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"><option value="push">通用 Push</option><option value="confluence">Confluence</option><option value="sharepoint">SharePoint</option><option value="dingtalk">钉钉</option><option value="git">Git</option></select><button onClick={() => void onCreate()} disabled={working || !name.trim() || selectedSpace.role !== 'admin'} className="rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-40">创建连接器</button></div>{type === 'dingtalk' && <p className="mt-2 text-xs text-[var(--text-secondary)]">钉钉连接器会把文档和群聊送入当前知识空间，把部门和成员关系同步到企业目录；首次启用前需由运维配置 DWS 只读 Profile。</p>}{selectedSpace.role !== 'admin' && <p className="mt-2 text-xs text-amber-500">只有空间 admin 可以创建连接器。</p>}</section><section className="grid gap-3 md:grid-cols-2">{connectors.map((connector) => <article key={connector.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-center justify-between"><h3 className="font-medium">{connector.name}</h3><Status value={connector.status} /></div><p className="mt-2 text-xs text-[var(--text-secondary)]">{connector.connector_type} · Cursor {connector.sync_cursor || '—'}</p>{connector.last_error && <p className="mt-2 text-xs text-red-500">{connector.last_error}</p>}{connector.connector_type === 'dingtalk' && <button onClick={() => void onSyncDingTalk(connector)} disabled={working || selectedSpace.role !== 'admin'} className="mt-3 inline-flex items-center gap-1.5 rounded-xl bg-[var(--accent)] px-3 py-2 text-xs text-[var(--accent-foreground)] disabled:opacity-40"><RefreshCw size={13} />同步文档、群聊与组织架构</button>}</article>)}{!connectors.length && <Empty text="该空间暂无连接器" />}</section><section className="space-y-2">{runs.map((run) => <article key={run.id} className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)]"><button onClick={() => void onToggle(run)} className="flex w-full items-center gap-3 p-4 text-left"><Status value={run.status} /><span className="min-w-0 flex-1 truncate text-sm">{run.connector_name}</span><span className="text-xs text-[var(--text-secondary)]">成功 {run.stats.succeeded || 0} / 失败 {run.stats.failed || 0}</span><ChevronRight size={15} className={clsx('transition-transform', expandedRunId === run.id && 'rotate-90')} /></button>{expandedRunId === run.id && <div className="border-t border-[var(--border)] p-4"><div className="space-y-2">{(items[run.id] || []).map((item) => <div key={item.id} className="rounded-xl bg-[var(--bg)] p-3 text-xs"><div className="flex justify-between gap-2"><span className="truncate font-medium">{item.title || item.external_id}</span><span>{item.status} · 尝试 {item.attempts}</span></div>{item.error && <p className="mt-2 text-red-500">{item.error}</p>}</div>)}</div>{run.status === 'failed' && <button onClick={() => void onRetry(run)} disabled={working} className="mt-3 rounded-xl bg-[var(--accent)] px-3 py-2 text-xs text-[var(--accent-foreground)]">重试失败项</button>}</div>}</article>)}{!runs.length && <Empty text="暂无同步运行记录" />}</section></div>
}

function AccessPanel({ selectedSpace, canAdmin, members, subjectType, subjectId, role, working, onSubjectType, onSubjectId, onRole, onGrant, onRevoke }: { selectedSpace: KnowledgeSpaceItem | null; canAdmin: boolean; members: KnowledgeSpaceMemberItem[]; subjectType: KnowledgeSpaceMemberItem['subject_type']; subjectId: string; role: KnowledgeSpaceMemberItem['role']; working: boolean; onSubjectType: (value: KnowledgeSpaceMemberItem['subject_type']) => void; onSubjectId: (value: string) => void; onRole: (value: KnowledgeSpaceMemberItem['role']) => void; onGrant: () => Promise<void>; onRevoke: (member: KnowledgeSpaceMemberItem) => Promise<void> }) {
  if (!selectedSpace) return <Empty text="请选择知识空间后管理访问控制" />
  if (!canAdmin) return <Empty text="只有空间 admin 可以管理成员、部门、用户组、岗位和 Project 授权" />
  return <div className="space-y-3"><section className="flex flex-wrap gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><select value={subjectType} onChange={(event) => onSubjectType(event.target.value as KnowledgeSpaceMemberItem['subject_type'])} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"><option value="user">用户</option><option value="department">部门</option><option value="group">用户组</option><option value="role">岗位</option><option value="project">Project</option></select><input value={subjectId} onChange={(event) => onSubjectId(event.target.value)} placeholder="主体 ID" className="min-w-52 flex-1 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" /><select value={role} onChange={(event) => onRole(event.target.value as KnowledgeSpaceMemberItem['role'])} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm">{['viewer', 'contributor', 'reviewer', 'publisher', 'admin'].map((value) => <option key={value} value={value}>{value}</option>)}</select><button onClick={() => void onGrant()} disabled={working || !subjectId.trim()} className="rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-40">授权</button></section>{members.map((member) => <article key={member.id} className="flex items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><Users size={17} className="text-[var(--accent)]" /><div className="flex-1"><h3 className="text-sm font-medium">{member.subject_type}:{member.subject_id}</h3><p className="mt-1 text-xs text-[var(--text-secondary)]">角色 {member.role} · 到期 {member.expires_at ? new Date(member.expires_at).toLocaleDateString() : '长期'}</p></div><button onClick={() => void onRevoke(member)} className="rounded-lg p-2 text-red-500 hover:bg-red-500/10"><Trash2 size={15} /></button></article>)}{!members.length && <Empty text="该空间暂无显式成员授权" />}</div>
}

function Status({ value }: { value: string }) {
  const good = ['published', 'succeeded', 'ready', 'active'].includes(value)
  const working = ['pending', 'running', 'compiling', 'review'].includes(value)
  return <span className={clsx('rounded-full px-2 py-1 text-[10px]', good ? 'bg-emerald-500/10 text-emerald-500' : working ? 'bg-amber-500/10 text-amber-500' : 'bg-slate-500/10 text-slate-500')}>{value}</span>
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-2xl border border-dashed border-[var(--border)] py-14 text-center text-sm text-[var(--text-secondary)]"><CircleCheck size={26} className="mx-auto mb-3 opacity-40" />{text}</div>
}
