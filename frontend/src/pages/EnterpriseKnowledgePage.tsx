import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeft,
  BookOpen,
  Check,
  ChevronRight,
  CircleAlert,
  FileSearch,
  FileText,
  Loader2,
  Plus,
  Plug,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  Upload,
  Users,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import {
  apiCreateEnterpriseKnowledgeConnector,
  apiCreateKnowledgeSpace,
  apiDecideKnowledgeReview,
  apiGrantKnowledgeSpaceMember,
  apiListEnterpriseKnowledgeConnectors,
  apiListKnowledgeReviews,
  apiListKnowledgeSpaceAssets,
  apiListKnowledgeSpaceMembers,
  apiListKnowledgeSpaces,
  apiListKnowledgeSpaceSources,
  apiListKnowledgeSyncRunItems,
  apiListKnowledgeSyncRuns,
  apiRetryKnowledgeSyncRun,
  apiRevokeKnowledgeSpaceMember,
  apiSearchEnterpriseKnowledge,
  apiUploadDocument,
  type EnterpriseKnowledgeAssetItem,
  type EnterpriseKnowledgeConnectorItem,
  type EnterpriseKnowledgeEvidence,
  type EnterpriseKnowledgeSourceItem,
  type KnowledgeReviewItem,
  type KnowledgeSpaceItem,
  type KnowledgeSyncItem,
  type KnowledgeSyncRunItem,
  type KnowledgeSpaceMemberItem,
} from '../api/client'
import { useAuthStore } from '../store/auth'
import { useChatPreferences } from '../store/chatPreferences'

type Tab = 'assets' | 'sources' | 'reviews' | 'connectors' | 'access'

const TYPE_LABEL: Record<string, string> = {
  company: '公司',
  department: '部门',
  role: '岗位',
  project: '项目',
  personal: '个人',
}

const CLASS_LABEL: Record<string, string> = {
  public: '公开',
  internal: '内部',
  confidential: '机密',
  restricted: '严格受限',
}

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleDateString() : '—'
}

export default function EnterpriseKnowledgePage({ onBack }: { onBack?: () => void }) {
  const token = useAuthStore((state) => state.token)!
  const projectId = useChatPreferences((state) => state.projectId)
  const fileInput = useRef<HTMLInputElement>(null)
  const [spaces, setSpaces] = useState<KnowledgeSpaceItem[]>([])
  const [selectedSpaceId, setSelectedSpaceId] = useState<string>('')
  const [assets, setAssets] = useState<EnterpriseKnowledgeAssetItem[]>([])
  const [sources, setSources] = useState<EnterpriseKnowledgeSourceItem[]>([])
  const [reviews, setReviews] = useState<KnowledgeReviewItem[]>([])
  const [members, setMembers] = useState<KnowledgeSpaceMemberItem[]>([])
  const [connectors, setConnectors] = useState<EnterpriseKnowledgeConnectorItem[]>([])
  const [syncRuns, setSyncRuns] = useState<KnowledgeSyncRunItem[]>([])
  const [syncItems, setSyncItems] = useState<Record<string, KnowledgeSyncItem[]>>({})
  const [expandedSyncRunId, setExpandedSyncRunId] = useState<string | null>(null)
  const [syncActionRunId, setSyncActionRunId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('assets')
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<EnterpriseKnowledgeEvidence[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [searching, setSearching] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [createName, setCreateName] = useState('')
  const [createType, setCreateType] = useState<KnowledgeSpaceItem['space_type']>('project')
  const [memberType, setMemberType] = useState<KnowledgeSpaceMemberItem['subject_type']>('user')
  const [memberId, setMemberId] = useState('')
  const [memberRole, setMemberRole] = useState<KnowledgeSpaceMemberItem['role']>('viewer')
  const [connectorName, setConnectorName] = useState('')
  const [connectorType, setConnectorType] = useState('push')

  const selectedSpace = useMemo(
    () => spaces.find((item) => item.id === selectedSpaceId) ?? null,
    [selectedSpaceId, spaces],
  )
  const canContribute = selectedSpace
    ? ['contributor', 'reviewer', 'publisher', 'admin'].includes(selectedSpace.role)
    : false
  const canReview = selectedSpace
    ? ['reviewer', 'publisher', 'admin'].includes(selectedSpace.role)
    : false
  const canAdmin = selectedSpace?.role === 'admin'

  const loadSpaces = useCallback(async () => {
    const next = await apiListKnowledgeSpaces(token)
    setSpaces(next)
    setSelectedSpaceId((current) => current || next[0]?.id || '')
  }, [token])

  const loadSpace = useCallback(async () => {
    if (!selectedSpaceId) {
      setAssets([])
      setSources([])
      return
    }
    const [nextAssets, nextSources] = await Promise.all([
      apiListKnowledgeSpaceAssets(token, selectedSpaceId),
      apiListKnowledgeSpaceSources(token, selectedSpaceId),
    ])
    setAssets(nextAssets)
    setSources(nextSources)
  }, [selectedSpaceId, token])

  const loadReviews = useCallback(async () => {
    if (!canReview) {
      setReviews([])
      return
    }
    const rows = await apiListKnowledgeReviews(token)
    setReviews(rows.filter((item) => item.space_id === selectedSpaceId))
  }, [canReview, selectedSpaceId, token])

  const loadAdmin = useCallback(async () => {
    if (!canAdmin || !selectedSpaceId) {
      setMembers([])
      setConnectors([])
      setSyncRuns([])
      return
    }
    const [nextMembers, nextConnectors, nextRuns] = await Promise.all([
      apiListKnowledgeSpaceMembers(token, selectedSpaceId),
      apiListEnterpriseKnowledgeConnectors(token, selectedSpaceId),
      apiListKnowledgeSyncRuns(token, undefined, selectedSpaceId),
    ])
    const connectorIds = new Set(nextConnectors.map((item) => item.id))
    setMembers(nextMembers)
    setConnectors(nextConnectors)
    setSyncRuns(nextRuns.filter((item) => connectorIds.has(item.connector_id)))
  }, [canAdmin, selectedSpaceId, token])

  const reload = useCallback(async () => {
    setLoading(true)
    setMessage('')
    try {
      await loadSpaces()
      await loadSpace()
      await loadReviews()
      await loadAdmin()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setLoading(false)
    }
  }, [loadAdmin, loadReviews, loadSpace, loadSpaces])

  useEffect(() => { void loadSpaces().catch((error) => setMessage(String(error))).finally(() => setLoading(false)) }, [loadSpaces])
  useEffect(() => { void loadSpace().catch((error) => setMessage(String(error))) }, [loadSpace])
  useEffect(() => { void loadReviews().catch((error) => setMessage(String(error))) }, [loadReviews])
  useEffect(() => { void loadAdmin().catch((error) => setMessage(String(error))) }, [loadAdmin])
  useEffect(() => {
    setExpandedSyncRunId(null)
    setSyncItems({})
  }, [selectedSpaceId])
  useEffect(() => {
    if (tab !== 'connectors' || !canAdmin || !syncRuns.some((run) => ['pending', 'running'].includes(run.status))) return
    const timer = window.setInterval(() => {
      void (async () => {
        await loadAdmin()
        if (expandedSyncRunId) {
          const nextItems = await apiListKnowledgeSyncRunItems(token, expandedSyncRunId)
          setSyncItems((current) => ({ ...current, [expandedSyncRunId]: nextItems }))
        }
      })().catch((error) => setMessage(error instanceof Error ? error.message : String(error)))
    }, 3000)
    return () => window.clearInterval(timer)
  }, [canAdmin, expandedSyncRunId, loadAdmin, syncRuns, tab, token])

  async function searchKnowledge() {
    if (!query.trim()) return
    setSearching(true)
    setMessage('')
    try {
      setResults(await apiSearchEnterpriseKnowledge(token, query.trim(), projectId))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setSearching(false)
    }
  }

  async function upload(files: FileList | null) {
    if (!files?.length || !selectedSpace) return
    setUploading(true)
    setMessage('')
    try {
      for (const file of Array.from(files)) {
        await apiUploadDocument(token, file, {
          knowledge_space_id: selectedSpace.id,
          classification: selectedSpace.classification,
          publish_policy: selectedSpace.publish_policy,
        })
      }
      setMessage(`已提交 ${files.length} 个文件；将按“${selectedSpace.publish_policy === 'review' ? '审核后发布' : '自动发布'}”策略处理`)
      await loadSpace()
      await loadReviews()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  async function createSpace() {
    if (!createName.trim()) return
    setLoading(true)
    try {
      const created = await apiCreateKnowledgeSpace(token, {
        name: createName.trim(),
        space_type: createType,
        visibility: createType === 'personal' ? 'private' : 'members',
        publish_policy: createType === 'personal' ? 'auto' : 'review',
        default_classification: 'internal',
      })
      setShowCreate(false)
      setCreateName('')
      await loadSpaces()
      setSelectedSpaceId(created.id)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setLoading(false)
    }
  }

  async function decide(review: KnowledgeReviewItem, decision: 'approve' | 'reject') {
    const comment = decision === 'reject' ? window.prompt('请输入驳回原因') : ''
    if (decision === 'reject' && !comment) return
    try {
      await apiDecideKnowledgeReview(token, review.id, decision, comment || '')
      setMessage(decision === 'approve' ? '知识版本已发布' : '知识版本已驳回')
      await Promise.all([loadReviews(), loadSpace()])
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  async function grantMember() {
    if (!selectedSpace || !memberId.trim()) return
    try {
      await apiGrantKnowledgeSpaceMember(token, selectedSpace.id, {
        subject_type: memberType, subject_id: memberId.trim(), role: memberRole,
      })
      setMemberId('')
      await loadAdmin()
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
  }

  async function revokeMember(member: KnowledgeSpaceMemberItem) {
    if (!selectedSpace || !window.confirm(`撤销 ${member.subject_type}:${member.subject_id} 的访问权限？`)) return
    try {
      await apiRevokeKnowledgeSpaceMember(token, selectedSpace.id, member.id)
      await loadAdmin()
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
  }

  async function createConnector() {
    if (!selectedSpace || !connectorName.trim()) return
    try {
      await apiCreateEnterpriseKnowledgeConnector(token, {
        space_id: selectedSpace.id, name: connectorName.trim(), connector_type: connectorType,
      })
      setConnectorName('')
      await loadAdmin()
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
  }

  async function toggleSyncRun(run: KnowledgeSyncRunItem) {
    if (expandedSyncRunId === run.id) {
      setExpandedSyncRunId(null)
      return
    }
    setExpandedSyncRunId(run.id)
    if (syncItems[run.id]) return
    setSyncActionRunId(run.id)
    try {
      const items = await apiListKnowledgeSyncRunItems(token, run.id)
      setSyncItems((current) => ({ ...current, [run.id]: items }))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setSyncActionRunId(null)
    }
  }

  async function retrySyncRun(run: KnowledgeSyncRunItem) {
    setSyncActionRunId(run.id)
    try {
      const result = await apiRetryKnowledgeSyncRun(token, run.id)
      setMessage(`已重新入队 ${result.requeued} 个失败项`)
      const items = await apiListKnowledgeSyncRunItems(token, run.id)
      setSyncItems((current) => ({ ...current, [run.id]: items }))
      await loadAdmin()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setSyncActionRunId(null)
    }
  }

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--bg)]/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-5 py-4">
          {onBack && <button onClick={onBack} className="rounded-xl p-2 hover:bg-[var(--surface)]"><ArrowLeft size={18} /></button>}
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[var(--accent-dim)] text-[var(--accent)]"><BookOpen size={20} /></div>
          <div className="min-w-0 flex-1">
            <h1 className="text-lg font-semibold">企业知识库</h1>
            <p className="text-xs text-[var(--text-secondary)]">受权限、版本、有效期和发布流程治理的企业知识</p>
          </div>
          <button onClick={() => void reload()} className="rounded-xl border border-[var(--border)] p-2 hover:bg-[var(--surface)]"><RefreshCw size={16} /></button>
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl gap-5 px-5 py-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">知识空间</span>
            <button onClick={() => setShowCreate(true)} className="rounded-lg p-1.5 hover:bg-[var(--surface)]" title="创建知识空间"><Plus size={15} /></button>
          </div>
          {spaces.map((space) => (
            <button
              key={space.id}
              onClick={() => { setSelectedSpaceId(space.id); setResults(null) }}
              className={clsx(
                'w-full rounded-2xl border p-3 text-left transition-colors',
                selectedSpaceId === space.id
                  ? 'border-[var(--accent)] bg-[var(--accent-dim)]'
                  : 'border-[var(--border)] bg-[var(--surface)] hover:border-[var(--accent-border)]',
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium">{space.name}</span>
                <ChevronRight size={14} className="text-[var(--text-secondary)]" />
              </div>
              <div className="mt-2 flex flex-wrap gap-1 text-[10px] text-[var(--text-secondary)]">
                <span className="rounded-md bg-[var(--surface-raised)] px-1.5 py-0.5">{TYPE_LABEL[space.space_type]}</span>
                <span className="rounded-md bg-[var(--surface-raised)] px-1.5 py-0.5">{CLASS_LABEL[space.classification]}</span>
                <span className="rounded-md bg-[var(--surface-raised)] px-1.5 py-0.5">{space.role}</span>
              </div>
            </button>
          ))}
          {!loading && spaces.length === 0 && (
            <div className="rounded-2xl border border-dashed border-[var(--border)] p-5 text-center text-sm text-[var(--text-secondary)]">尚无可访问知识空间</div>
          )}
        </aside>

        <section className="min-w-0 space-y-5">
          <div className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search size={17} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={(event) => event.key === 'Enter' && void searchKnowledge()}
                  placeholder="搜索公司制度、流程、产品、指标和项目知识…"
                  className="w-full rounded-2xl border border-[var(--border)] bg-[var(--bg)] py-3 pl-10 pr-4 text-sm outline-none focus:border-[var(--accent)]"
                />
              </div>
              <button onClick={() => void searchKnowledge()} disabled={searching || !query.trim()} className="rounded-2xl bg-[var(--accent)] px-5 text-sm font-medium text-[var(--accent-foreground)] disabled:opacity-40">
                {searching ? <Loader2 size={17} className="animate-spin" /> : '检索'}
              </button>
            </div>
          </div>

          {message && <div className="flex items-start gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm"><CircleAlert size={16} className="mt-0.5 text-[var(--accent)]" /><span>{message}</span></div>}

          {results !== null ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between"><h2 className="font-semibold">检索结果 · {results.length}</h2><button onClick={() => setResults(null)} className="rounded-lg p-1.5 hover:bg-[var(--surface)]"><X size={16} /></button></div>
              {results.map((item) => (
                <article key={`${item.source_type}:${item.id}`} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div><h3 className="font-medium">{item.title || '知识证据'}</h3><div className="mt-1 text-xs text-[var(--text-secondary)]">{item.source_type} · 权威级别 {item.authority || 'contextual'} · score {item.score.toFixed(3)}</div></div>
                    <ShieldCheck size={17} className="text-emerald-500" />
                  </div>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-[var(--text-secondary)]">{item.text}</p>
                  <div className="mt-3 text-xs text-[var(--text-secondary)]">版本 {item.source_version_id || '—'} · 来源 {item.source_id || item.document_id || '—'}</div>
                </article>
              ))}
              {results.length === 0 && <div className="rounded-2xl border border-dashed border-[var(--border)] py-12 text-center text-sm text-[var(--text-secondary)]">未找到当前权限范围内的有效知识</div>}
            </div>
          ) : selectedSpace ? (
            <>
              <div className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div><h2 className="text-xl font-semibold">{selectedSpace.name}</h2><p className="mt-1 text-sm text-[var(--text-secondary)]">{selectedSpace.description || '暂无空间说明'}</p></div>
                  {canContribute && <><input ref={fileInput} type="file" multiple className="hidden" onChange={(event) => void upload(event.target.files)} /><button onClick={() => fileInput.current?.click()} disabled={uploading} className="flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-foreground)] disabled:opacity-50">{uploading ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />}上传知识</button></>}
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-5">
                  <Metric label="已发布资产" value={assets.length} />
                  <Metric label="知识源" value={sources.length} />
                  <Metric label="待审核" value={reviews.length} />
                  <Metric label="连接器" value={connectors.length} />
                  <Metric label="复审周期" value={`${selectedSpace.review_cycle_days}天`} />
                </div>
              </div>

              <div className="flex gap-1 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-1">
                <TabButton active={tab === 'assets'} onClick={() => setTab('assets')} icon={<BookOpen size={15} />} label="知识资产" />
                <TabButton active={tab === 'sources'} onClick={() => setTab('sources')} icon={<FileText size={15} />} label="来源与时效" />
                {canReview && <TabButton active={tab === 'reviews'} onClick={() => setTab('reviews')} icon={<ShieldCheck size={15} />} label={`发布审核 ${reviews.length || ''}`} />}
                {canAdmin && <TabButton active={tab === 'connectors'} onClick={() => setTab('connectors')} icon={<Plug size={15} />} label="连接器" />}
                {canAdmin && <TabButton active={tab === 'access'} onClick={() => setTab('access')} icon={<Users size={15} />} label="成员权限" />}
              </div>

              {tab === 'assets' && <AssetGrid assets={assets} />}
              {tab === 'sources' && <SourceList sources={sources} />}
              {tab === 'reviews' && canReview && <ReviewList reviews={reviews} onDecision={decide} />}
              {tab === 'connectors' && canAdmin && (
                <ConnectorPanel
                  connectors={connectors}
                  runs={syncRuns}
                  items={syncItems}
                  expandedRunId={expandedSyncRunId}
                  actionRunId={syncActionRunId}
                  name={connectorName}
                  type={connectorType}
                  onName={setConnectorName}
                  onType={setConnectorType}
                  onCreate={createConnector}
                  onToggleRun={toggleSyncRun}
                  onRetryRun={retrySyncRun}
                />
              )}
              {tab === 'access' && canAdmin && <MemberPanel members={members} subjectType={memberType} subjectId={memberId} role={memberRole} onSubjectType={setMemberType} onSubjectId={setMemberId} onRole={setMemberRole} onGrant={grantMember} onRevoke={revokeMember} />}
            </>
          ) : null}
        </section>
      </main>

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setShowCreate(false)}>
          <div className="w-full max-w-md rounded-3xl border border-[var(--border)] bg-[var(--bg)] p-6 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <h2 className="text-lg font-semibold">创建知识空间</h2>
            <input value={createName} onChange={(event) => setCreateName(event.target.value)} placeholder="例如：公司制度中心" className="mt-4 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5 text-sm outline-none focus:border-[var(--accent)]" />
            <select value={createType} onChange={(event) => setCreateType(event.target.value as KnowledgeSpaceItem['space_type'])} className="mt-3 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5 text-sm">
              {Object.entries(TYPE_LABEL).map(([value, label]) => <option key={value} value={value}>{label}知识空间</option>)}
            </select>
            <div className="mt-5 flex justify-end gap-2"><button onClick={() => setShowCreate(false)} className="rounded-xl border border-[var(--border)] px-4 py-2 text-sm">取消</button><button onClick={() => void createSpace()} disabled={!createName.trim()} className="rounded-xl bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-foreground)] disabled:opacity-40">创建</button></div>
          </div>
        </div>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-2xl bg-[var(--bg)] p-3"><div className="text-xl font-semibold">{value}</div><div className="mt-1 text-xs text-[var(--text-secondary)]">{label}</div></div>
}

function TabButton({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return <button onClick={onClick} className={clsx('flex flex-1 items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm', active ? 'bg-[var(--accent-dim)] text-[var(--accent)]' : 'text-[var(--text-secondary)] hover:bg-[var(--bg)]')}>{icon}{label}</button>
}

function AssetGrid({ assets }: { assets: EnterpriseKnowledgeAssetItem[] }) {
  if (!assets.length) return <Empty icon={<BookOpen size={28} />} text="该空间还没有已发布知识资产" />
  return <div className="grid gap-3 md:grid-cols-2">{assets.map((asset) => <article key={asset.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-start justify-between gap-3"><div><h3 className="font-medium">{asset.title}</h3><div className="mt-1 text-xs text-[var(--text-secondary)]">{asset.page_type} · {CLASS_LABEL[asset.classification] || asset.classification}</div></div><BookOpen size={16} className="text-[var(--accent)]" /></div><p className="mt-3 line-clamp-4 text-sm leading-6 text-[var(--text-secondary)]">{asset.summary || '暂无摘要'}</p><div className="mt-3 text-xs text-[var(--text-secondary)]">权威 {asset.authority} · 置信度 {asset.confidence.toFixed(2)} · 下次复审 {formatDate(asset.review_due_at)}</div></article>)}</div>
}

function SourceList({ sources }: { sources: EnterpriseKnowledgeSourceItem[] }) {
  if (!sources.length) return <Empty icon={<FileSearch size={28} />} text="该空间还没有知识来源" />
  return <div className="space-y-2">{sources.map((source) => <article key={source.id} className="flex flex-wrap items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><FileText size={17} className="text-[var(--accent)]" /><div className="min-w-0 flex-1"><h3 className="truncate text-sm font-medium">{source.title}</h3><div className="mt-1 text-xs text-[var(--text-secondary)]">{source.source_system || source.source_type} · {CLASS_LABEL[source.classification] || source.classification} · 更新 {formatDate(source.updated_at)}</div></div><span className={clsx('rounded-full px-2 py-1 text-xs', source.status === 'published' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-amber-500/10 text-amber-500')}>{source.status}</span><span className="text-xs text-[var(--text-secondary)]">复审 {formatDate(source.review_due_at)}</span></article>)}</div>
}

function ReviewList({ reviews, onDecision }: { reviews: KnowledgeReviewItem[]; onDecision: (review: KnowledgeReviewItem, decision: 'approve' | 'reject') => Promise<void> }) {
  if (!reviews.length) return <Empty icon={<ShieldCheck size={28} />} text="没有待审核知识版本" />
  return <div className="space-y-3">{reviews.map((review) => <article key={review.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-start justify-between gap-4"><div><h3 className="font-medium">待发布知识版本</h3><div className="mt-1 text-xs text-[var(--text-secondary)]">版本 {review.source_version_id} · {formatDate(review.created_at)}</div><div className="mt-3 text-sm text-[var(--text-secondary)]">页面 {String(review.diff_summary.pages ?? 0)} · 事实 {String(review.diff_summary.claims ?? 0)} · 关系 {String(review.diff_summary.relations ?? 0)}</div></div><ShieldCheck size={18} className="text-amber-500" /></div><div className="mt-4 flex justify-end gap-2"><button onClick={() => void onDecision(review, 'reject')} className="flex items-center gap-1 rounded-xl border border-red-500/30 px-3 py-2 text-sm text-red-500"><X size={14} />驳回</button><button onClick={() => void onDecision(review, 'approve')} className="flex items-center gap-1 rounded-xl bg-emerald-600 px-3 py-2 text-sm text-white"><Check size={14} />审核并发布</button></div></article>)}</div>
}

function ConnectorPanel({
  connectors,
  runs,
  items,
  expandedRunId,
  actionRunId,
  name,
  type,
  onName,
  onType,
  onCreate,
  onToggleRun,
  onRetryRun,
}: {
  connectors: EnterpriseKnowledgeConnectorItem[]
  runs: KnowledgeSyncRunItem[]
  items: Record<string, KnowledgeSyncItem[]>
  expandedRunId: string | null
  actionRunId: string | null
  name: string
  type: string
  onName: (value: string) => void
  onType: (value: string) => void
  onCreate: () => Promise<void>
  onToggleRun: (run: KnowledgeSyncRunItem) => Promise<void>
  onRetryRun: (run: KnowledgeSyncRunItem) => Promise<void>
}) {
  const statusLabel: Record<KnowledgeSyncRunItem['status'], string> = {
    pending: '等待执行',
    running: '同步中',
    succeeded: '已完成',
    failed: '失败',
  }
  const statusTone: Record<KnowledgeSyncRunItem['status'], string> = {
    pending: 'bg-slate-500/10 text-slate-500',
    running: 'bg-blue-500/10 text-blue-500',
    succeeded: 'bg-emerald-500/10 text-emerald-500',
    failed: 'bg-red-500/10 text-red-500',
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
        <input value={name} onChange={(event) => onName(event.target.value)} placeholder="连接器名称" className="min-w-48 flex-1 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" />
        <select value={type} onChange={(event) => onType(event.target.value)} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm">
          <option value="push">通用 Push</option><option value="sharepoint">SharePoint</option><option value="confluence">Confluence</option><option value="dingtalk">钉钉</option><option value="git">Git</option>
        </select>
        <button onClick={() => void onCreate()} disabled={!name.trim()} className="rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-40">注册连接器</button>
      </div>

      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">连接器</h3>
        {connectors.map((item) => (
          <article key={item.id} className="flex items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <Plug size={17} className="text-[var(--accent)]" />
            <div className="flex-1">
              <div className="text-sm font-medium">{item.name}</div>
              <div className="mt-1 text-xs text-[var(--text-secondary)]">{item.connector_type} · 上次同步 {formatDate(item.last_sync_at)} · cursor {item.sync_cursor || '—'}</div>
              {item.last_error && <div className="mt-1 text-xs text-red-500">{item.last_error}</div>}
            </div>
            <span className="text-xs text-[var(--text-secondary)]">{item.status}</span>
          </article>
        ))}
        {!connectors.length && <Empty icon={<Plug size={28} />} text="尚未注册知识连接器" />}
      </section>

      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">同步运行记录</h3>
        {runs.map((run) => {
          const runItems = items[run.id]
          const expanded = expandedRunId === run.id
          const busy = actionRunId === run.id
          return (
            <article key={run.id} className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)]">
              <button onClick={() => void onToggleRun(run)} className="flex w-full items-start gap-3 p-4 text-left hover:bg-[var(--surface-raised)]">
                {run.status === 'running' ? <Loader2 size={17} className="mt-0.5 animate-spin text-blue-500" /> : <RefreshCw size={17} className="mt-0.5 text-[var(--accent)]" />}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{run.connector_name}</span>
                    <span className={clsx('rounded-full px-2 py-0.5 text-[11px]', statusTone[run.status])}>{statusLabel[run.status]}</span>
                  </div>
                  <div className="mt-1 text-xs text-[var(--text-secondary)]">{formatDate(run.started_at)} · cursor {run.cursor_before || '—'} → {run.cursor_after || '—'}</div>
                  <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-[var(--text-secondary)]">
                    <span>排队 {run.stats.queued ?? 0}</span><span>执行中 {run.stats.running ?? 0}</span><span>成功 {run.stats.succeeded ?? 0}</span><span>失败 {run.stats.failed ?? 0}</span>
                  </div>
                </div>
                <ChevronRight size={15} className={clsx('mt-1 transition-transform', expanded && 'rotate-90')} />
              </button>
              {expanded && (
                <div className="border-t border-[var(--border)] px-4 py-3">
                  {busy && !runItems && <div className="flex items-center gap-2 py-3 text-xs text-[var(--text-secondary)]"><Loader2 size={14} className="animate-spin" />加载同步明细…</div>}
                  {run.error && <div className="mb-3 rounded-xl bg-red-500/10 p-3 text-xs text-red-500">{run.error}</div>}
                  <div className="space-y-2">
                    {(runItems ?? []).map((item) => (
                      <div key={item.id} className="rounded-xl bg-[var(--bg)] p-3 text-xs">
                        <div className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate font-medium">{item.title || item.external_id}</span><span className={item.status === 'failed' ? 'text-red-500' : 'text-[var(--text-secondary)]'}>{item.status}</span><span className="text-[var(--text-secondary)]">尝试 {item.attempts}</span></div>
                        {item.error && <div className="mt-2 break-words text-red-500">{item.error}</div>}
                      </div>
                    ))}
                    {runItems && !runItems.length && <div className="py-3 text-xs text-[var(--text-secondary)]">该批次没有同步项</div>}
                  </div>
                  {run.status === 'failed' && (
                    <div className="mt-3 flex justify-end">
                      <button onClick={() => void onRetryRun(run)} disabled={busy} className="flex items-center gap-1 rounded-xl bg-[var(--accent)] px-3 py-2 text-xs text-[var(--accent-foreground)] disabled:opacity-50">{busy ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}重试失败项</button>
                    </div>
                  )}
                </div>
              )}
            </article>
          )
        })}
        {!runs.length && <div className="rounded-2xl border border-dashed border-[var(--border)] p-6 text-center text-xs text-[var(--text-secondary)]">暂无连接器同步记录</div>}
      </section>
    </div>
  )
}

function MemberPanel({ members, subjectType, subjectId, role, onSubjectType, onSubjectId, onRole, onGrant, onRevoke }: { members: KnowledgeSpaceMemberItem[]; subjectType: KnowledgeSpaceMemberItem['subject_type']; subjectId: string; role: KnowledgeSpaceMemberItem['role']; onSubjectType: (value: KnowledgeSpaceMemberItem['subject_type']) => void; onSubjectId: (value: string) => void; onRole: (value: KnowledgeSpaceMemberItem['role']) => void; onGrant: () => Promise<void>; onRevoke: (member: KnowledgeSpaceMemberItem) => Promise<void> }) {
  return <div className="space-y-3"><div className="flex flex-wrap gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><select value={subjectType} onChange={(event) => onSubjectType(event.target.value as KnowledgeSpaceMemberItem['subject_type'])} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"><option value="user">用户</option><option value="department">部门</option><option value="group">用户组</option><option value="role">岗位</option><option value="project">Project</option></select><input value={subjectId} onChange={(event) => onSubjectId(event.target.value)} placeholder="主体 ID" className="min-w-48 flex-1 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" /><select value={role} onChange={(event) => onRole(event.target.value as KnowledgeSpaceMemberItem['role'])} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm">{['viewer','contributor','reviewer','publisher','admin'].map((item) => <option key={item} value={item}>{item}</option>)}</select><button onClick={() => void onGrant()} disabled={!subjectId.trim()} className="rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-40">授权</button></div>{members.map((member) => <article key={member.id} className="flex items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><Users size={17} className="text-[var(--accent)]" /><div className="flex-1"><div className="text-sm font-medium">{member.subject_type}:{member.subject_id}</div><div className="mt-1 text-xs text-[var(--text-secondary)]">角色 {member.role} · 到期 {formatDate(member.expires_at)}</div></div><button onClick={() => void onRevoke(member)} className="rounded-lg p-2 text-red-500 hover:bg-red-500/10"><Trash2 size={15} /></button></article>)}{!members.length && <Empty icon={<Users size={28} />} text="该空间暂无显式成员授权" />}</div>
}

function Empty({ icon, text }: { icon: React.ReactNode; text: string }) {
  return <div className="rounded-3xl border border-dashed border-[var(--border)] py-14 text-center text-[var(--text-secondary)]"><div className="mx-auto mb-3 flex justify-center opacity-50">{icon}</div><p className="text-sm">{text}</p></div>
}
