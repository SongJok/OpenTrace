import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChevronLeft, CircleCheck, FileText, GitBranch, Loader2, MessageSquareText, Network, Play, RefreshCw, Upload, SlidersHorizontal, Save, ShieldCheck } from 'lucide-react'
import clsx from 'clsx'
import {
  apiGetKnowledgeGraph,
  apiListKnowledgeJobs,
  apiListKnowledgePages,
  apiListKnowledgeSources,
  apiListProjects,
  apiOrchestrateKnowledge,
  apiUploadDocument,
  apiListKnowledgeRules,
  apiCreateKnowledgeRule,
  apiApproveKnowledgeRule,
  apiPublishKnowledgePage,
  type KnowledgeGraphData,
  type KnowledgeJobItem,
  type KnowledgePageItem,
  type KnowledgeSourceItem,
  type ProjectItem,
  type KnowledgeRuleItem,
} from '../api/client'
import { useAuthStore } from '../store/auth'
import { useChatPreferences } from '../store/chatPreferences'

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
  const requestPrefill = useChatPreferences((state) => state.requestPrefill)
  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [network, setNetwork] = useState<NetworkType>('entity')
  const [graph, setGraph] = useState<KnowledgeGraphData>({ network: 'entity', nodes: [], edges: [] })
  const [sources, setSources] = useState<KnowledgeSourceItem[]>([])
  const [pages, setPages] = useState<KnowledgePageItem[]>([])
  const [jobs, setJobs] = useState<KnowledgeJobItem[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [orchestrating, setOrchestrating] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [publishPolicy, setPublishPolicy] = useState<'auto' | 'review'>('auto')
  const [message, setMessage] = useState('')
  const [rules, setRules] = useState<KnowledgeRuleItem[]>([])
  const [ruleConfig, setRuleConfig] = useState({ summary_length: 420, content_limit: 16000, min_claim_length: 8, max_claims_per_page: 12 })
  const [ruleInstructions, setRuleInstructions] = useState('按标题拆分知识页面，所有事实保留原文证据；优先建立明确依赖和实体引用。')
  const [savingRule, setSavingRule] = useState(false)
  const [publishingSourceId, setPublishingSourceId] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [nextGraph, nextSources, publishedPages, reviewPages, nextJobs] = await Promise.all([
        apiGetKnowledgeGraph(token, network, selectedProjectId),
        apiListKnowledgeSources(token, selectedProjectId),
        apiListKnowledgePages(token, selectedProjectId, 'published'),
        apiListKnowledgePages(token, selectedProjectId, 'review'),
        apiListKnowledgeJobs(token, selectedProjectId),
      ])
      setGraph(nextGraph)
      setSources(nextSources)
      setPages([...publishedPages, ...reviewPages])
      setJobs(nextJobs)
      setRules(await apiListKnowledgeRules(token, selectedProjectId))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      if (!silent) setLoading(false)
    }
  }, [network, selectedProjectId, token])

  useEffect(() => { void apiListProjects(token).then(setProjects) }, [token])
  useEffect(() => { void load() }, [load])
  const hasActiveJobs = jobs.some((job) => ['pending', 'running'].includes(job.status))
  const reviewSourceIds = useMemo(
    () => new Set(pages.filter((page) => page.status === 'review').map((page) => page.source_id)),
    [pages],
  )
  useEffect(() => {
    if (!hasActiveJobs) return
    const timer = window.setInterval(() => { void load(true) }, 2000)
    return () => window.clearInterval(timer)
  }, [hasActiveJobs, load])

  async function upload(files: FileList | null) {
    if (!files?.length) return
    setUploading(true)
    setMessage('')
    try {
      for (const file of Array.from(files)) {
        await apiUploadDocument(token, file, {
          project_id: selectedProjectId,
          publish_policy: publishPolicy,
          chunk_strategy: 1,
        })
      }
      setMessage(`已上传 ${files.length} 个文件，编排任务已自动入队`)
      await load()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  async function orchestrate() {
    setOrchestrating(true)
    try {
      const result = await apiOrchestrateKnowledge(token, selectedProjectId)
      setMessage(`已扫描 ${result.documents ?? 0} 个文档，新增 ${result.jobs_queued ?? 0} 个任务和 ${result.relations_created ?? 0} 条关系`)
      await load()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setOrchestrating(false)
    }
  }

  async function saveRule() {
    setSavingRule(true)
    try {
      const draft = await apiCreateKnowledgeRule(token, {
        rule_key: 'knowledge_compiler', project_id: selectedProjectId,
        rule_type: 'orchestration', schema_json: ruleConfig,
        instructions: ruleInstructions, provenance: { editor: 'knowledge_center' },
      })
      await apiApproveKnowledgeRule(token, draft.id)
      setMessage(`编排规则 v${draft.version} 已发布；后续自动/定时编排将按此规则执行。`)
      await load()
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
    finally { setSavingRule(false) }
  }

  function verifyInChat(source: KnowledgeSourceItem) {
    requestPrefill(`/rag 请仅根据当前 Project 的知识库《${source.title}》概括核心内容，并附上可追溯来源。`)
    onBack?.()
  }

  async function publishSource(source: KnowledgeSourceItem) {
    const page = pages.find((item) => item.source_id === source.id && item.status === 'review')
    if (!page) {
      setMessage('未找到可发布的审核版本，请等待编排完成后刷新。')
      return
    }
    setPublishingSourceId(source.id)
    try {
      await apiPublishKnowledgePage(token, page.id)
      setMessage(`《${source.title}》已发布并进入治理知识检索通道。`)
      await load(true)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setPublishingSourceId(null)
    }
  }

  return (
    <div className="flex h-screen flex-col bg-[var(--bg)] text-[var(--text)]">
      <header className="flex h-14 items-center gap-3 border-b border-[var(--border)] px-5">
        <button onClick={onBack} className="rounded-lg p-2 text-[var(--text-secondary)] hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
        <Network size={18} className="text-[var(--accent)]" />
        <h1 className="text-sm font-semibold">知识编排</h1>
        <select
          value={selectedProjectId ?? ''}
          onChange={(event) => setSelectedProjectId(event.target.value || null)}
          className="ml-3 max-w-56 rounded-lg border border-[var(--border)] bg-transparent px-3 py-1.5 text-xs"
        >
          <option value="">全部工作区知识</option>
          {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
        </select>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={() => void load()} className="rounded-lg border border-[var(--border)] p-2 text-[var(--text-secondary)] hover:bg-[var(--surface)]" title="刷新"><RefreshCw size={15} /></button>
          <button onClick={() => void orchestrate()} disabled={orchestrating} className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-xs font-medium text-[var(--accent-foreground)] disabled:opacity-50">
            {orchestrating ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}立即编排
          </button>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto grid max-w-7xl gap-5 p-6 xl:grid-cols-[340px_1fr]">
          <aside className="space-y-5">
            <section
              onDragOver={(event) => { event.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(event) => { event.preventDefault(); setDragOver(false); void upload(event.dataTransfer.files) }}
              onClick={() => fileInput.current?.click()}
              className={clsx('cursor-pointer rounded-2xl border-2 border-dashed p-6 text-center transition-colors', dragOver ? 'border-[var(--accent)] bg-[var(--accent-dim)]' : 'border-[var(--border)] bg-[var(--surface)]')}
            >
              {uploading ? <Loader2 size={26} className="mx-auto animate-spin text-[var(--accent)]" /> : <Upload size={26} className="mx-auto text-[var(--text-secondary)]" />}
              <p className="mt-3 text-sm font-medium">{uploading ? '正在上传并解析…' : '拖入文件或点击上传'}</p>
              <p className="mt-1 text-xs text-[var(--text-secondary)]">PDF、DOCX、Markdown、TXT</p>
              <input ref={fileInput} type="file" multiple accept=".pdf,.docx,.md,.txt" className="hidden" onChange={(event) => void upload(event.target.files)} />
            </section>
            <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
              <h2 className="text-xs font-semibold">发布规则</h2>
              <select value={publishPolicy} onChange={(event) => setPublishPolicy(event.target.value as 'auto' | 'review')} className="mt-3 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-xs">
                <option value="auto">编排完成后自动纳入问答</option>
                <option value="review">人工审核后纳入问答</option>
              </select>
              <p className="mt-2 text-[11px] leading-5 text-[var(--text-secondary)]">系统每 5 分钟兜底扫描遗漏或变更的文件；Worker 常驻时会持续处理任务。</p>
            </section>
            <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
              <div className="flex items-center justify-between"><h2 className="inline-flex items-center gap-2 text-xs font-semibold"><SlidersHorizontal size={14} />在线编排逻辑</h2><span className="text-[10px] text-[var(--text-secondary)]">{selectedProjectId ? '项目级' : '工作区默认'}</span></div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                {([['摘要长度', 'summary_length'], ['正文上限', 'content_limit'], ['最短事实', 'min_claim_length'], ['每页事实数', 'max_claims_per_page']] as const).map(([label, key]) => <label key={key} className="text-[10px] text-[var(--text-secondary)]">{label}<input type="number" min={1} value={ruleConfig[key]} onChange={(e) => setRuleConfig((value) => ({ ...value, [key]: Number(e.target.value) }))} className="mt-1 w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs text-[var(--text)]" /></label>)}
              </div>
              <label className="mt-3 block text-[10px] text-[var(--text-secondary)]">人工指引<textarea value={ruleInstructions} onChange={(e) => setRuleInstructions(e.target.value)} rows={3} className="mt-1 w-full resize-none rounded-lg border border-[var(--border)] bg-transparent p-2 text-xs leading-5 text-[var(--text)]" /></label>
              <button onClick={() => void saveRule()} disabled={savingRule} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-xs text-[var(--accent-foreground)] disabled:opacity-50"><Save size={13} />保存并发布新版本</button>
              <div className="mt-3 space-y-1">{rules.slice(0, 3).map((rule) => <div key={rule.id} className="flex items-center justify-between rounded-lg bg-[var(--surface-raised)] px-2 py-1.5 text-[10px]"><span>v{rule.version} · {rule.status}</span>{rule.status === 'approved' && <ShieldCheck size={12} className="text-emerald-500" />}</div>)}</div>
            </section>
            <Stats sources={sources} pages={pages} jobs={jobs} />
            <MainChainStatus sources={sources} pages={pages} jobs={jobs} />
            {message && <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 text-xs leading-5">{message}</div>}
          </aside>

          <section className="min-w-0 space-y-5">
            <div className="flex gap-2">
              {(Object.keys(NETWORK_LABELS) as NetworkType[]).map((item) => (
                <button key={item} onClick={() => setNetwork(item)} className={clsx('rounded-full px-4 py-2 text-xs', network === item ? 'bg-[var(--accent)] text-[var(--accent-foreground)]' : 'border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]')}>{NETWORK_LABELS[item]}</button>
              ))}
            </div>
            <GraphPanel graph={graph} loading={loading} />
            <div className="grid gap-5 lg:grid-cols-2">
              <SourceList sources={sources} reviewSourceIds={reviewSourceIds} onVerify={verifyInChat} onPublish={publishSource} publishingSourceId={publishingSourceId} />
              <JobList jobs={jobs} />
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}

function MainChainStatus({ sources, pages, jobs }: { sources: KnowledgeSourceItem[]; pages: KnowledgePageItem[]; jobs: KnowledgeJobItem[] }) {
  const published = sources.filter((source) => source.status === 'published').length
  const review = new Set(pages.filter((page) => page.status === 'review').map((page) => page.source_id)).size
  const active = jobs.filter((job) => ['pending', 'running'].includes(job.status)).length
  const failed = jobs.filter((job) => job.status === 'failed').length
  const tone = published > 0 ? 'text-emerald-500' : active > 0 ? 'text-amber-500' : 'text-[var(--text-secondary)]'
  return <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4">
    <h2 className="flex items-center gap-2 text-xs font-semibold"><CircleCheck size={14} className={tone} />主链路状态</h2>
    <p className="mt-2 text-[11px] leading-5 text-[var(--text-secondary)]">
      {sources.length === 0 && '上传成功后，原文检索通道会立即可用，治理知识将在后台发布。'}
      {sources.length > 0 && `${sources.length} 份原文已进入 RAG 检索范围；${published} 份治理知识已发布。`}
    </p>
    {(active > 0 || review > 0 || failed > 0) && <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
      {active > 0 && <span className="rounded-full bg-amber-500/10 px-2 py-1 text-amber-500">后台编排 {active}</span>}
      {review > 0 && <span className="rounded-full bg-sky-500/10 px-2 py-1 text-sky-500">待发布 {review}</span>}
      {failed > 0 && <span className="rounded-full bg-red-500/10 px-2 py-1 text-red-500">失败 {failed}</span>}
    </div>}
  </section>
}

function Stats({ sources, pages, jobs }: { sources: KnowledgeSourceItem[]; pages: KnowledgePageItem[]; jobs: KnowledgeJobItem[] }) {
  const values = [
    ['知识源', sources.length],
    ['实体/页面', pages.length],
    ['运行中', jobs.filter((job) => ['pending', 'running'].includes(job.status)).length],
    ['失败', jobs.filter((job) => job.status === 'failed').length],
  ]
  return <section className="grid grid-cols-2 gap-2">{values.map(([label, value]) => <div key={label} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3"><div className="text-lg font-semibold">{value}</div><div className="text-[11px] text-[var(--text-secondary)]">{label}</div></div>)}</section>
}

function GraphPanel({ graph, loading }: { graph: KnowledgeGraphData; loading: boolean }) {
  const visibleNodes = graph.nodes.slice(0, 90)
  const positions = useMemo(() => {
    const width = 900; const height = 500; const radius = Math.min(width, height) * 0.38
    return new Map(visibleNodes.map((node, index) => {
      const angle = (index / Math.max(1, visibleNodes.length)) * Math.PI * 2
      const ring = 0.55 + (index % 3) * 0.2
      return [node.id, { x: width / 2 + Math.cos(angle) * radius * ring, y: height / 2 + Math.sin(angle) * radius * ring }]
    }))
  }, [graph.nodes])
  const ids = new Set(visibleNodes.map((node) => node.id))
  const edges = graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)).slice(0, 240)
  return <div className="relative h-[520px] overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)]">
    {loading && <div className="absolute inset-0 z-10 grid place-items-center bg-[var(--surface)]"><Loader2 className="animate-spin text-[var(--accent)]" /></div>}
    {!loading && visibleNodes.length === 0 && <div className="grid h-full place-items-center text-sm text-[var(--text-secondary)]">上传文件后，这里会显示{NETWORK_LABELS[graph.network]}</div>}
    <svg viewBox="0 0 900 500" className="h-full w-full">
      {edges.map((edge) => { const a = positions.get(edge.source); const b = positions.get(edge.target); return a && b ? <g key={edge.id}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="var(--border)" strokeWidth="1.5" /><title>{edge.type}</title></g> : null })}
      {visibleNodes.map((node) => { const point = positions.get(node.id)!; const color = node.type === 'source' ? '#f59e0b' : node.type === 'claim' ? '#10b981' : '#6366f1'; return <g key={node.id}><circle cx={point.x} cy={point.y} r={node.type === 'source' ? 11 : 8} fill={color} opacity=".9"><title>{node.label}</title></circle><text x={point.x} y={point.y + 20} textAnchor="middle" fontSize="10" fill="var(--text-secondary)">{node.label.slice(0, 14)}</text></g> })}
    </svg>
    <div className="absolute bottom-3 right-4 text-[11px] text-[var(--text-secondary)]">{graph.nodes.length} 节点 · {graph.edges.length} 关系</div>
  </div>
}

function SourceList({ sources, reviewSourceIds, onVerify, onPublish, publishingSourceId }: { sources: KnowledgeSourceItem[]; reviewSourceIds: Set<string>; onVerify: (source: KnowledgeSourceItem) => void; onPublish: (source: KnowledgeSourceItem) => void; publishingSourceId: string | null }) {
  return <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><h2 className="flex items-center gap-2 text-xs font-semibold"><FileText size={14} />知识源</h2><div className="mt-3 max-h-72 space-y-2 overflow-auto">{sources.length === 0 ? <p className="text-xs text-[var(--text-secondary)]">暂无知识源</p> : sources.map((source) => <div key={source.id} className="rounded-xl border border-[var(--border)] p-3"><div className="flex items-center gap-3"><div className="min-w-0 flex-1"><div className="truncate text-xs font-medium">{source.title}</div><div className="mt-1 text-[11px] text-[var(--text-secondary)]">{source.authority} · {source.source_type}</div></div><Status value={source.status} /></div><div className="mt-2 flex gap-3"><button type="button" onClick={() => onVerify(source)} className="inline-flex items-center gap-1 text-[11px] text-[var(--accent)] hover:underline"><MessageSquareText size={12} />回主问答验证</button>{reviewSourceIds.has(source.id) && <button type="button" disabled={publishingSourceId === source.id} onClick={() => onPublish(source)} className="inline-flex items-center gap-1 text-[11px] text-sky-500 hover:underline disabled:opacity-50"><ShieldCheck size={12} />审核并发布</button>}</div></div>)}</div></section>
}

function JobList({ jobs }: { jobs: KnowledgeJobItem[] }) {
  return <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><h2 className="flex items-center gap-2 text-xs font-semibold"><GitBranch size={14} />最近任务</h2><div className="mt-3 max-h-72 space-y-2 overflow-auto">{jobs.length === 0 ? <p className="text-xs text-[var(--text-secondary)]">暂无编排任务</p> : jobs.slice(0, 20).map((job) => <div key={job.id} className="rounded-xl border border-[var(--border)] p-3"><div className="flex items-center justify-between"><span className="font-mono text-[11px] text-[var(--text-secondary)]">{job.id.slice(0, 8)}</span><Status value={job.status} /></div>{job.error && <p className="mt-2 text-[11px] text-red-500">{job.error}</p>}</div>)}</div></section>
}

function Status({ value }: { value: string }) {
  const good = ['published', 'succeeded', 'ready'].includes(value)
  const working = ['pending', 'running', 'compiling'].includes(value)
  return <span className={clsx('rounded-full px-2 py-1 text-[10px]', good ? 'bg-emerald-500/10 text-emerald-500' : working ? 'bg-amber-500/10 text-amber-500' : 'bg-slate-500/10 text-slate-500')}>{value}</span>
}
