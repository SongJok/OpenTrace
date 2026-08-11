import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  FileSearch,
  FileText,
  Loader2,
  MessageSquareWarning,
  Plus,
  Search,
  Send,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import {
  apiCreateKnowledgeSpace,
  apiListKnowledgeSpaceAssets,
  apiListKnowledgeSpaces,
  apiListKnowledgeSpaceSources,
  apiSearchEnterpriseKnowledge,
  apiSubmitKnowledgeFeedback,
  type EnterpriseKnowledgeAssetItem,
  type EnterpriseKnowledgeEvidence,
  type EnterpriseKnowledgeSourceItem,
  type KnowledgeFeedbackType,
  type KnowledgeSpaceItem,
} from '../api/client'
import { useAuthStore } from '../store/auth'
import { useChatPreferences } from '../store/chatPreferences'

type Tab = 'assets' | 'sources'
type FeedbackTarget = { targetType: string; targetId: string }

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

const formatDate = (value?: string | null) => value ? new Date(value).toLocaleDateString() : '—'
const isReviewDue = (value?: string | null) => Boolean(value && new Date(value).getTime() <= Date.now())

function evidenceFeedbackTarget(result: EnterpriseKnowledgeEvidence): FeedbackTarget | null {
  if (result.source_type === 'knowledge_claim') {
    return { targetType: 'knowledge_claim', targetId: result.claim_id || result.id }
  }
  if (result.source_type === 'knowledge_page') {
    return { targetType: 'knowledge_page', targetId: result.knowledge_page_id || result.id }
  }
  if (result.source_id) return { targetType: 'knowledge_source', targetId: result.source_id }
  return null
}

export default function EnterpriseKnowledgePage({ onBack }: { onBack?: () => void }) {
  const token = useAuthStore((state) => state.token)!
  const platformRole = useAuthStore((state) => state.role)
  const projectId = useChatPreferences((state) => state.projectId)
  const navigate = useNavigate()
  const [spaces, setSpaces] = useState<KnowledgeSpaceItem[]>([])
  const [selectedSpaceId, setSelectedSpaceId] = useState('')
  const [assets, setAssets] = useState<EnterpriseKnowledgeAssetItem[]>([])
  const [sources, setSources] = useState<EnterpriseKnowledgeSourceItem[]>([])
  const [tab, setTab] = useState<Tab>('assets')
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<EnterpriseKnowledgeEvidence[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [searching, setSearching] = useState(false)
  const [feedbackBusy, setFeedbackBusy] = useState('')
  const [message, setMessage] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [createName, setCreateName] = useState('')
  const [createType, setCreateType] = useState<KnowledgeSpaceItem['space_type']>('project')

  const selectedSpace = useMemo(
    () => spaces.find((space) => space.id === selectedSpaceId) ?? null,
    [selectedSpaceId, spaces],
  )
  const canContribute = selectedSpace
    ? ['contributor', 'reviewer', 'publisher', 'admin'].includes(selectedSpace.role)
    : false
  const canGovern = platformRole === 'admin' || Boolean(
    selectedSpace && ['reviewer', 'publisher', 'admin'].includes(selectedSpace.role),
  )

  const loadSpaces = useCallback(async () => {
    const next = await apiListKnowledgeSpaces(token)
    setSpaces(next)
    setSelectedSpaceId((current) => current || next[0]?.id || '')
  }, [token])

  const loadSelectedSpace = useCallback(async () => {
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

  useEffect(() => {
    void loadSpaces()
      .catch((error) => setMessage(error instanceof Error ? error.message : String(error)))
      .finally(() => setLoading(false))
  }, [loadSpaces])

  useEffect(() => {
    void loadSelectedSpace().catch((error) => setMessage(error instanceof Error ? error.message : String(error)))
  }, [loadSelectedSpace])

  async function search() {
    if (!query.trim()) return
    setSearching(true)
    setMessage('')
    try {
      setResults(await apiSearchEnterpriseKnowledge(token, query.trim(), projectId, selectedSpaceId, 12))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setSearching(false)
    }
  }

  async function submitFeedback(
    target: FeedbackTarget,
    feedbackType: KnowledgeFeedbackType,
  ) {
    const key = `${target.targetType}:${target.targetId}:${feedbackType}`
    let correction: string | null = null
    if (feedbackType === 'correction') {
      correction = window.prompt('请描述正确内容、依据或建议修改方式')?.trim() || null
      if (!correction) return
    }
    setFeedbackBusy(key)
    try {
      await apiSubmitKnowledgeFeedback(token, {
        target_type: target.targetType,
        target_id: target.targetId,
        feedback_type: feedbackType,
        correction,
        score: feedbackType === 'helpful' ? 1 : feedbackType === 'unhelpful' ? 0 : null,
      })
      setMessage('反馈已提交，将进入知识治理闭环。')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setFeedbackBusy('')
    }
  }

  async function createSpace() {
    if (!createName.trim()) return
    try {
      const created = await apiCreateKnowledgeSpace(token, {
        name: createName.trim(),
        space_type: createType,
        publish_policy: createType === 'personal' ? 'auto' : 'review',
      })
      setShowCreate(false)
      setCreateName('')
      await loadSpaces()
      setSelectedSpaceId(created.id)
      setMessage('知识空间已创建')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  function contribute() {
    if (!selectedSpace) return
    navigate(`/documents?space_id=${encodeURIComponent(selectedSpace.id)}`)
  }

  return (
    <div className="min-h-full bg-[var(--bg)] text-[var(--text)]">
      <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-[var(--border)] bg-[var(--bg)]/95 px-6 py-4 backdrop-blur">
        <button onClick={onBack} className="rounded-lg p-2 hover:bg-[var(--surface)]"><ArrowLeft size={18} /></button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">企业知识库</h1>
          <p className="text-xs text-[var(--text-secondary)]">搜索、浏览和贡献经过权限、版本、有效期与发布流程治理的企业知识</p>
        </div>
        {platformRole === 'admin' && <button onClick={() => navigate('/knowledge')} className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] px-3 py-2 text-xs"><ShieldCheck size={14} />知识库质量中心</button>}
      </header>

      <div className="grid min-h-[calc(100vh-65px)] lg:grid-cols-[280px_1fr]">
        <aside className="border-r border-[var(--border)] p-4">
          <div className="flex items-center justify-between px-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">知识空间</span>
            {platformRole === 'admin' && <button onClick={() => setShowCreate(true)} className="rounded-lg p-1.5 hover:bg-[var(--surface)]" title="创建知识空间"><Plus size={15} /></button>}
          </div>
          <div className="mt-3 space-y-1">
            {spaces.map((space) => <button key={space.id} onClick={() => { setSelectedSpaceId(space.id); setResults(null) }} className={clsx('w-full rounded-xl px-3 py-3 text-left', selectedSpaceId === space.id ? 'bg-[var(--accent-dim)] text-[var(--accent)]' : 'hover:bg-[var(--surface)]')}><div className="flex items-center gap-2"><BookOpen size={15} /><span className="min-w-0 flex-1 truncate text-sm font-medium">{space.name}</span></div><div className="mt-1 pl-6 text-[11px] text-[var(--text-secondary)]">{TYPE_LABEL[space.space_type]} · {space.role}</div></button>)}
            {!loading && !spaces.length && <div className="rounded-2xl border border-dashed border-[var(--border)] p-5 text-center text-sm text-[var(--text-secondary)]">暂无可访问知识空间</div>}
          </div>
        </aside>

        <main className="min-w-0 p-6">
          {message && <div className="mb-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm">{message}</div>}
          <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <form onSubmit={(event) => { event.preventDefault(); void search() }} className="flex gap-2">
              <div className="relative flex-1"><Search size={16} className="absolute left-3 top-3 text-[var(--text-secondary)]" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索公司制度、流程、产品、指标和项目知识…" className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] py-2.5 pl-10 pr-3 text-sm" /></div>
              <button disabled={searching || !query.trim()} className="rounded-xl bg-[var(--accent)] px-5 py-2.5 text-sm text-[var(--accent-foreground)] disabled:opacity-40">{searching ? <Loader2 size={15} className="animate-spin" /> : '搜索'}</button>
            </form>
          </section>

          {results !== null ? (
            <section className="mt-5 space-y-3">
              <div className="flex items-center justify-between"><h2 className="font-semibold">检索结果 · {results.length}</h2><button onClick={() => setResults(null)} className="rounded-lg p-2 hover:bg-[var(--surface)]"><X size={16} /></button></div>
              {results.map((result) => {
                const target = evidenceFeedbackTarget(result)
                const due = isReviewDue(result.review_due_at)
                return <article key={`${result.source_type}:${result.id}`} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-start justify-between gap-3"><div><h3 className="font-medium">{result.title || '知识证据'}</h3><div className="mt-2 flex flex-wrap gap-1.5"><TrustBadge text={`权威 ${result.authority || 'contextual'}`} /><TrustBadge text={CLASS_LABEL[result.classification || 'internal'] || result.classification || '内部'} /><TrustBadge text={result.source_system || '企业知识'} /><TrustBadge text={`同步 ${result.sync_status || 'current'}`} />{due && <TrustBadge warning text="需要复审" />}</div></div><FileSearch size={17} className="text-[var(--accent)]" /></div><p className="mt-3 whitespace-pre-wrap text-sm leading-6">{result.text}</p><div className="mt-3 grid gap-1 text-xs text-[var(--text-secondary)] sm:grid-cols-2"><p>版本 {result.source_version_id || '—'} · 相关度 {result.score.toFixed(3)}</p><p>生效 {formatDate(result.effective_from)} · 失效 {formatDate(result.effective_to)} · 复审 {formatDate(result.review_due_at)}</p><p className="sm:col-span-2">Citation：来源 {result.source_id || result.document_id || '—'}{result.claim_id ? ` · Claim ${result.claim_id}` : ''}</p></div>{target && <FeedbackActions target={target} busy={feedbackBusy} onSubmit={submitFeedback} />}</article>
              })}
              {!results.length && <div className="rounded-2xl border border-dashed border-[var(--border)] py-12 text-center text-sm text-[var(--text-secondary)]">未找到当前权限范围内的有效知识</div>}
            </section>
          ) : selectedSpace ? (
            <div className="mt-5 space-y-5">
              <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
                <div className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="text-xl font-semibold">{selectedSpace.name}</h2><p className="mt-1 text-sm text-[var(--text-secondary)]">{selectedSpace.description || `${TYPE_LABEL[selectedSpace.space_type]}知识空间`}</p></div>{canContribute && <button onClick={contribute} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)]"><Send size={14} />投稿资料</button>}</div>
                <div className="mt-5 grid gap-3 sm:grid-cols-4"><Metric label="已发布知识" value={assets.length} /><Metric label="知识来源" value={sources.length} /><Metric label="默认密级" value={CLASS_LABEL[selectedSpace.classification]} /><Metric label="发布策略" value={selectedSpace.publish_policy === 'review' ? '审核发布' : '自动发布'} /></div>
              </section>

              <nav className="flex rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-1"><TabButton active={tab === 'assets'} onClick={() => setTab('assets')} icon={<BookOpen size={14} />} label="知识资产" /><TabButton active={tab === 'sources'} onClick={() => setTab('sources')} icon={<FileText size={14} />} label="来源与状态" /></nav>
              {tab === 'assets' ? <AssetGrid assets={assets} feedbackBusy={feedbackBusy} onFeedback={submitFeedback} /> : <SourceList sources={sources} />}
            </div>
          ) : <div className="mt-5 rounded-3xl border border-dashed border-[var(--border)] py-20 text-center text-sm text-[var(--text-secondary)]">请选择一个知识空间</div>}
        </main>
      </div>

      {showCreate && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4" onClick={() => setShowCreate(false)}><div className="w-full max-w-md rounded-3xl border border-[var(--border)] bg-[var(--bg)] p-5" onClick={(event) => event.stopPropagation()}><h2 className="font-semibold">创建知识空间</h2><input value={createName} onChange={(event) => setCreateName(event.target.value)} placeholder="空间名称" className="mt-4 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5" /><select value={createType} onChange={(event) => setCreateType(event.target.value as KnowledgeSpaceItem['space_type'])} className="mt-3 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5">{Object.entries(TYPE_LABEL).map(([value, label]) => <option key={value} value={value}>{label}空间</option>)}</select><div className="mt-5 flex justify-end gap-2"><button onClick={() => setShowCreate(false)} className="rounded-xl border border-[var(--border)] px-4 py-2 text-sm">取消</button><button onClick={() => void createSpace()} disabled={!createName.trim()} className="rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-40">创建</button></div></div></div>
      )}
    </div>
  )
}

function TrustBadge({ text, warning = false }: { text: string; warning?: boolean }) {
  return <span className={clsx('rounded-full px-2 py-1 text-[11px]', warning ? 'bg-amber-500/10 text-amber-500' : 'bg-[var(--bg)] text-[var(--text-secondary)]')}>{warning && <AlertTriangle size={11} className="mr-1 inline" />}{text}</span>
}

function FeedbackActions({ target, busy, onSubmit }: { target: FeedbackTarget; busy: string; onSubmit: (target: FeedbackTarget, type: KnowledgeFeedbackType) => Promise<void> }) {
  const actions: Array<{ type: KnowledgeFeedbackType; label: string; icon: React.ReactNode }> = [
    { type: 'helpful', label: '有帮助', icon: <ThumbsUp size={12} /> },
    { type: 'unhelpful', label: '无帮助', icon: <ThumbsDown size={12} /> },
    { type: 'incorrect', label: '内容错误', icon: <MessageSquareWarning size={12} /> },
    { type: 'outdated', label: '内容过期', icon: <AlertTriangle size={12} /> },
    { type: 'correction', label: '提交纠正', icon: <FileText size={12} /> },
  ]
  return <div className="mt-4 flex flex-wrap gap-1.5 border-t border-[var(--border)] pt-3">{actions.map((action) => { const key = `${target.targetType}:${target.targetId}:${action.type}`; return <button key={action.type} onClick={() => void onSubmit(target, action.type)} disabled={Boolean(busy)} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2 py-1.5 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg)] disabled:opacity-40">{busy === key ? <Loader2 size={12} className="animate-spin" /> : action.icon}{action.label}</button> })}</div>
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-2xl bg-[var(--bg)] p-3"><div className="text-lg font-semibold">{value}</div><div className="mt-1 text-xs text-[var(--text-secondary)]">{label}</div></div>
}

function TabButton({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return <button onClick={onClick} className={clsx('flex flex-1 items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm', active ? 'bg-[var(--accent-dim)] text-[var(--accent)]' : 'text-[var(--text-secondary)] hover:bg-[var(--bg)]')}>{icon}{label}</button>
}

function AssetGrid({ assets, feedbackBusy, onFeedback }: { assets: EnterpriseKnowledgeAssetItem[]; feedbackBusy: string; onFeedback: (target: FeedbackTarget, type: KnowledgeFeedbackType) => Promise<void> }) {
  if (!assets.length) return <Empty icon={<BookOpen size={28} />} text="该空间还没有已发布知识资产" />
  return <div className="grid gap-3 md:grid-cols-2">{assets.map((asset) => <article key={asset.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-start justify-between gap-3"><div><h3 className="font-medium">{asset.title}</h3><p className="mt-1 text-xs text-[var(--text-secondary)]">{asset.page_type} · {CLASS_LABEL[asset.classification] || asset.classification}</p></div><BookOpen size={16} className="text-[var(--accent)]" /></div><p className="mt-3 line-clamp-4 text-sm leading-6 text-[var(--text-secondary)]">{asset.summary || '暂无摘要'}</p><div className="mt-3 flex flex-wrap gap-1.5"><TrustBadge text={`权威 ${asset.authority}`} /><TrustBadge text={`置信度 ${asset.confidence.toFixed(2)}`} /><TrustBadge warning={isReviewDue(asset.review_due_at)} text={`${isReviewDue(asset.review_due_at) ? '需要复审' : '复审'} ${formatDate(asset.review_due_at)}`} /></div><FeedbackActions target={{ targetType: 'knowledge_page', targetId: asset.id }} busy={feedbackBusy} onSubmit={onFeedback} /></article>)}</div>
}

function SourceList({ sources }: { sources: EnterpriseKnowledgeSourceItem[] }) {
  if (!sources.length) return <Empty icon={<FileSearch size={28} />} text="该空间还没有知识来源" />
  return <div className="space-y-2">{sources.map((source) => <article key={source.id} className="flex flex-wrap items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><FileText size={17} className="text-[var(--accent)]" /><div className="min-w-0 flex-1"><h3 className="truncate text-sm font-medium">{source.title}</h3><p className="mt-1 text-xs text-[var(--text-secondary)]">{source.source_system || source.source_type} · {CLASS_LABEL[source.classification] || source.classification} · 更新 {formatDate(source.updated_at)}</p></div><span className={clsx('rounded-full px-2 py-1 text-xs', source.status === 'published' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-amber-500/10 text-amber-500')}>{source.status}</span><span className={clsx('text-xs', isReviewDue(source.review_due_at) ? 'text-amber-500' : 'text-[var(--text-secondary)]')}>{isReviewDue(source.review_due_at) ? '需要复审' : '复审'} {formatDate(source.review_due_at)}</span></article>)}</div>
}

function Empty({ icon, text }: { icon: React.ReactNode; text: string }) {
  return <div className="rounded-3xl border border-dashed border-[var(--border)] py-14 text-center text-[var(--text-secondary)]"><div className="mb-3 flex justify-center opacity-50">{icon}</div><p className="text-sm">{text}</p></div>
}
