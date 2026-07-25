import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  Clock,
  Eye,
  FileText,
  FolderKanban,
  Loader2,
  RefreshCw,
  Save,
  Search,
  Settings2,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import { useAuthStore } from '../store/auth'
import { useChatPreferences } from '../store/chatPreferences'
import {
  apiDeleteDocument,
  apiGetDocument,
  apiListDocuments,
  apiListKnowledgeSpaces,
  apiSearchDocuments,
  apiUpdateDocument,
  apiUploadDocument,
  CHUNK_STRATEGY_LABELS,
  type DocumentDetail,
  type DocumentOut,
  type KnowledgeSpaceItem,
  type SearchResult,
} from '../api/client'

type UploadTarget = 'personal' | 'project' | 'space'
type Classification = 'public' | 'internal' | 'confidential' | 'restricted'

const CLASSIFICATION_LABELS: Record<Classification, string> = {
  public: '公开',
  internal: '内部',
  confidential: '机密',
  restricted: '严格受限',
}

export default function DocumentsPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((state) => state.token)!
  const projectId = useChatPreferences((state) => state.projectId)
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedSpaceId = searchParams.get('space_id') || ''
  const [docs, setDocs] = useState<DocumentOut[]>([])
  const [spaces, setSpaces] = useState<KnowledgeSpaceItem[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [selectedDoc, setSelectedDoc] = useState<DocumentDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [chunkStrategy, setChunkStrategy] = useState(1)
  const [showStrategy, setShowStrategy] = useState(false)
  const [target, setTarget] = useState<UploadTarget>(requestedSpaceId ? 'space' : 'personal')
  const [selectedSpaceId, setSelectedSpaceId] = useState(requestedSpaceId)
  const [classification, setClassification] = useState<Classification>('internal')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const contributionSpaces = useMemo(
    () => spaces.filter((space) => ['contributor', 'reviewer', 'publisher', 'admin'].includes(space.role)),
    [spaces],
  )
  const selectedSpace = useMemo(
    () => contributionSpaces.find((space) => space.id === selectedSpaceId) ?? null,
    [contributionSpaces, selectedSpaceId],
  )

  useEffect(() => {
    void Promise.all([apiListDocuments(token), apiListKnowledgeSpaces(token)])
      .then(([documents, nextSpaces]) => {
        setDocs(documents)
        setSpaces(nextSpaces)
        const requested = nextSpaces.find((space) => space.id === requestedSpaceId)
        if (requested && ['contributor', 'reviewer', 'publisher', 'admin'].includes(requested.role)) {
          setTarget('space')
          setSelectedSpaceId(requested.id)
          setClassification(requested.classification)
        }
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : String(error)))
      .finally(() => setLoading(false))
  }, [requestedSpaceId, token])

  function selectTarget(next: UploadTarget) {
    setTarget(next)
    if (next !== 'space') {
      setSearchParams({}, { replace: true })
    } else if (!selectedSpaceId && contributionSpaces[0]) {
      setSelectedSpaceId(contributionSpaces[0].id)
      setClassification(contributionSpaces[0].classification)
    }
  }

  function selectSpace(spaceId: string) {
    setSelectedSpaceId(spaceId)
    const space = contributionSpaces.find((item) => item.id === spaceId)
    if (space) setClassification(space.classification)
    setSearchParams(spaceId ? { space_id: spaceId } : {}, { replace: true })
  }

  async function handleFiles(files: FileList | null) {
    if (!files?.length) return
    if (target === 'project' && !projectId) {
      setMessage('请先在对话工作台选择 Project，再上传 Project 资料。')
      return
    }
    if (target === 'space' && !selectedSpace) {
      setMessage('请选择一个具有贡献权限的知识空间。')
      return
    }
    setUploading(true)
    setMessage('')
    try {
      const uploaded: DocumentOut[] = []
      for (const file of Array.from(files)) {
        uploaded.push(
          await apiUploadDocument(token, file, {
            chunk_strategy: chunkStrategy,
            project_id: target === 'project' ? projectId : null,
            knowledge_space_id: target === 'space' ? selectedSpace?.id : null,
            classification,
            publish_policy: target === 'space' ? selectedSpace?.publish_policy : 'auto',
          }),
        )
      }
      setDocs((current) => [...uploaded.reverse(), ...current])
      setMessage(
        target === 'space'
          ? `已投稿 ${uploaded.length} 份资料到“${selectedSpace?.name}”，将按${selectedSpace?.publish_policy === 'review' ? '审核后发布' : '自动发布'}策略处理。`
          : `已上传 ${uploaded.length} 份${target === 'project' ? ' Project' : '个人'}资料，可立即用于授权范围内的原文检索。`,
      )
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('确认删除这份原始资料及其检索分块？已进入企业知识治理的资料需要先撤回知识来源。')) return
    try {
      await apiDeleteDocument(token, id)
      setDocs((current) => current.filter((document) => document.id !== id))
      setSearchResults((current) => current?.filter((result) => result.document_id !== id) ?? null)
      if (selectedDoc?.id === id) closeDetail()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  async function handleSearch() {
    if (!searchQuery.trim()) return
    setSearching(true)
    setSearchResults(null)
    try {
      setSearchResults(await apiSearchDocuments(token, searchQuery.trim(), 8, projectId))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setSearching(false)
    }
  }

  async function openDetail(id: string) {
    setDetailLoading(true)
    try {
      const document = await apiGetDocument(token, id)
      setSelectedDoc(document)
      setEditTitle(document.title)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setDetailLoading(false)
    }
  }

  function closeDetail() {
    setSelectedDoc(null)
    setEditTitle('')
  }

  async function saveDetail() {
    if (!selectedDoc) return
    setSaving(true)
    try {
      const updated = await apiUpdateDocument(token, selectedDoc.id, { title: editTitle.trim() })
      setDocs((current) => current.map((document) => (document.id === updated.id ? { ...document, ...updated } : document)))
      setSelectedDoc((current) => (current ? { ...current, ...updated } : current))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setSaving(false)
    }
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  return (
    <div className="min-h-full bg-[var(--bg)] text-[var(--text)]">
      <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-[var(--border)] bg-[var(--bg)]/95 px-6 py-4 backdrop-blur">
        <button onClick={onBack} className="rounded-lg p-2 hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">我的资料</h1>
          <p className="text-xs text-[var(--text-secondary)]">原始文件、个人检索资料和企业知识投稿的统一入口</p>
        </div>
        <button onClick={() => void Promise.all([apiListDocuments(token), apiListKnowledgeSpaces(token)]).then(([items, nextSpaces]) => { setDocs(items); setSpaces(nextSpaces) })} className="rounded-lg p-2 hover:bg-[var(--surface)]" title="刷新"><RefreshCw size={16} /></button>
      </header>

      <main className="mx-auto max-w-6xl space-y-5 p-6">
        {message && <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm">{message}</div>}

        <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold">上传资料</h2>
              <p className="mt-1 text-xs text-[var(--text-secondary)]">上传一次，根据目标决定仅自己使用、加入 Project，或投稿到企业知识空间。</p>
            </div>
            <button onClick={() => setShowStrategy((value) => !value)} className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] px-3 py-2 text-xs"><Settings2 size={14} />分块策略 {chunkStrategy}</button>
          </div>

          <div className="mt-4 grid gap-2 md:grid-cols-3">
            <TargetCard active={target === 'personal'} icon={<FileText size={18} />} title="仅自己使用" description="个人资料和原文检索" onClick={() => selectTarget('personal')} />
            <TargetCard active={target === 'project'} icon={<FolderKanban size={18} />} title="当前 Project" description={projectId ? '加入当前 Project 范围' : '需要先选择 Project'} onClick={() => selectTarget('project')} />
            <TargetCard active={target === 'space'} icon={<ShieldCheck size={18} />} title="投稿企业知识库" description="进入编排、审核和发布流程" onClick={() => selectTarget('space')} />
          </div>

          {target === 'space' && (
            <div className="mt-4 grid gap-3 rounded-2xl bg-[var(--bg)] p-4 md:grid-cols-2">
              <label className="text-xs text-[var(--text-secondary)]">目标知识空间
                <select value={selectedSpaceId} onChange={(event) => selectSpace(event.target.value)} className="mt-2 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]">
                  <option value="">请选择知识空间</option>
                  {contributionSpaces.map((space) => <option key={space.id} value={space.id}>{space.name} · {space.role}</option>)}
                </select>
              </label>
              <label className="text-xs text-[var(--text-secondary)]">资料密级
                <select value={classification} onChange={(event) => setClassification(event.target.value as Classification)} className="mt-2 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]">
                  {Object.entries(CLASSIFICATION_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              {selectedSpace && <p className="md:col-span-2 text-xs text-[var(--text-secondary)]">空间默认密级：{CLASSIFICATION_LABELS[selectedSpace.classification]} · 发布策略：{selectedSpace.publish_policy === 'review' ? '人工审核后发布' : '自动发布'} · 复审周期：{selectedSpace.review_cycle_days} 天</p>}
            </div>
          )}

          {showStrategy && (
            <div className="mt-4 rounded-2xl bg-[var(--bg)] p-4">
              <label className="text-xs text-[var(--text-secondary)]">文档分块策略</label>
              <select value={chunkStrategy} onChange={(event) => setChunkStrategy(Number(event.target.value))} className="mt-2 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm">
                {Object.entries(CHUNK_STRATEGY_LABELS).map(([value, label]) => <option key={value} value={value}>{value}: {label}</option>)}
              </select>
            </div>
          )}

          <div
            onDragOver={(event) => { event.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(event) => { event.preventDefault(); setDragOver(false); void handleFiles(event.dataTransfer.files) }}
            onClick={() => !uploading && fileInputRef.current?.click()}
            className={clsx('mt-4 cursor-pointer rounded-2xl border-2 border-dashed p-8 text-center transition-colors', dragOver ? 'border-[var(--accent)] bg-[var(--accent-dim)]' : 'border-[var(--border)] hover:border-[var(--accent-border)]')}
          >
            <input ref={fileInputRef} type="file" multiple className="hidden" accept=".pdf,.txt,.md,.docx,.xlsx,.csv" onChange={(event) => void handleFiles(event.target.files)} />
            {uploading ? <Loader2 size={28} className="mx-auto animate-spin text-[var(--accent)]" /> : <Upload size={28} className="mx-auto text-[var(--accent)]" />}
            <p className="mt-3 text-sm font-medium">{uploading ? '正在解析、分块并入库…' : '拖入文件或点击上传'}</p>
            <p className="mt-1 text-xs text-[var(--text-secondary)]">PDF、Word、Markdown、TXT、Excel、CSV</p>
          </div>
        </section>

        <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative min-w-60 flex-1">
              <Search size={15} className="absolute left-3 top-3 text-[var(--text-secondary)]" />
              <input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && void handleSearch()} placeholder="在我的原始资料中搜索…" className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] py-2.5 pl-9 pr-3 text-sm" />
            </div>
            <button onClick={() => void handleSearch()} disabled={searching || !searchQuery.trim()} className="rounded-xl bg-[var(--accent)] px-4 py-2.5 text-sm text-[var(--accent-foreground)] disabled:opacity-40">{searching ? '搜索中…' : '搜索原文'}</button>
          </div>

          {searchResults && <div className="mt-4 space-y-2">{searchResults.length ? searchResults.map((result) => <article key={`${result.document_id}:${result.chunk_index}`} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-4"><div className="flex justify-between gap-3 text-xs"><span className="font-semibold text-[var(--accent)]">{result.title}</span><span className="text-[var(--text-secondary)]">score {result.score.toFixed(3)} · chunk #{result.chunk_index}</span></div><p className="mt-2 text-sm leading-6">{result.content}</p></article>) : <p className="py-6 text-center text-sm text-[var(--text-secondary)]">没有找到匹配的原始资料</p>}</div>}

          <div className="mt-5 border-t border-[var(--border)] pt-5">
            <h2 className="font-semibold">资料列表</h2>
            {loading ? <div className="flex justify-center py-12"><Loader2 className="animate-spin text-[var(--accent)]" /></div> : docs.length === 0 ? <div className="py-14 text-center text-sm text-[var(--text-secondary)]">暂无资料，请从上方统一入口上传。</div> : <div className="mt-3 space-y-2">{docs.map((document) => <article key={document.id} className="group flex items-center gap-4 rounded-xl border border-[var(--border)] bg-[var(--bg)] px-4 py-3"><FileText size={18} className="text-[var(--accent)]" /><button className="min-w-0 flex-1 text-left" onClick={() => void openDetail(document.id)}><div className="flex items-center gap-2 truncate text-sm font-medium">{document.title}<Eye size={13} className="opacity-0 group-hover:opacity-100" /></div><p className="mt-1 text-xs text-[var(--text-secondary)]">{document.file_type.toUpperCase()} · {formatSize(document.file_size)} · {document.chunk_count} 个分块 · v{document.version}</p></button><StatusBadge status={document.status} /><button onClick={() => void handleDelete(document.id)} className="rounded-lg p-2 text-[var(--text-secondary)] opacity-0 hover:bg-red-500/10 hover:text-red-500 group-hover:opacity-100" title="删除原始资料"><Trash2 size={14} /></button></article>)}</div>}
          </div>
        </section>
      </main>

      {selectedDoc && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm" onClick={closeDetail}>
          <aside className="h-full w-full max-w-xl overflow-y-auto border-l border-[var(--border)] bg-[var(--bg)]" onClick={(event) => event.stopPropagation()}>
            <header className="sticky top-0 flex items-center justify-between border-b border-[var(--border)] bg-[var(--bg)] px-5 py-4"><div><h2 className="font-semibold">资料详情</h2><p className="text-xs text-[var(--text-secondary)]">{selectedDoc.id}</p></div><button onClick={closeDetail} className="rounded-lg p-2 hover:bg-[var(--surface)]"><X size={17} /></button></header>
            {detailLoading ? <div className="flex justify-center py-16"><Loader2 className="animate-spin" /></div> : <div className="space-y-5 p-5">
              <div><label className="text-xs text-[var(--text-secondary)]">资料标题</label><input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} className="mt-2 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5" /><button onClick={() => void saveDetail()} disabled={saving || !editTitle.trim()} className="mt-2 inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-40">{saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}保存标题</button></div>
              <div className="grid grid-cols-2 gap-3"><Info label="状态" value={selectedDoc.status} /><Info label="版本" value={`v${selectedDoc.version}`} /><Info label="文件大小" value={formatSize(selectedDoc.file_size)} /><Info label="分块" value={String(selectedDoc.chunk_count)} /></div>
              <div><h3 className="text-xs text-[var(--text-secondary)]">内容预览</h3><pre className="mt-2 min-h-36 whitespace-pre-wrap rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 text-sm leading-6">{selectedDoc.content_preview || '暂无预览'}</pre></div>
              <div><h3 className="text-xs text-[var(--text-secondary)]">元数据</h3><pre className="mt-2 overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 text-xs leading-6">{JSON.stringify(selectedDoc.metadata ?? {}, null, 2)}</pre></div>
              <div className="flex items-center justify-between border-t border-[var(--border)] pt-4"><button onClick={() => void handleDelete(selectedDoc.id)} className="inline-flex items-center gap-2 rounded-xl bg-red-500/10 px-4 py-2 text-sm text-red-500"><Trash2 size={14} />删除原始资料</button><span className="text-xs text-[var(--text-secondary)]">{selectedDoc.file_type.toUpperCase()} · {selectedDoc.created_at}</span></div>
            </div>}
          </aside>
        </div>
      )}
    </div>
  )
}

function TargetCard({ active, icon, title, description, onClick }: { active: boolean; icon: React.ReactNode; title: string; description: string; onClick: () => void }) {
  return <button onClick={onClick} className={clsx('flex items-start gap-3 rounded-2xl border p-4 text-left transition-colors', active ? 'border-[var(--accent)] bg-[var(--accent-dim)]' : 'border-[var(--border)] bg-[var(--bg)] hover:border-[var(--accent-border)]')}><span className={active ? 'text-[var(--accent)]' : 'text-[var(--text-secondary)]'}>{icon}</span><span><strong className="block text-sm">{title}</strong><span className="mt-1 block text-xs text-[var(--text-secondary)]">{description}</span></span></button>
}

function StatusBadge({ status }: { status: string }) {
  const config = status === 'ready' ? { icon: CheckCircle2, className: 'bg-emerald-500/10 text-emerald-500', label: '就绪' } : status === 'error' ? { icon: AlertCircle, className: 'bg-red-500/10 text-red-500', label: '失败' } : { icon: Clock, className: 'bg-amber-500/10 text-amber-500', label: '处理中' }
  const Icon = config.icon
  return <span className={clsx('inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs', config.className)}><Icon size={12} />{config.label}</span>
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3"><p className="text-xs text-[var(--text-secondary)]">{label}</p><p className="mt-1 text-sm font-medium">{value}</p></div>
}
