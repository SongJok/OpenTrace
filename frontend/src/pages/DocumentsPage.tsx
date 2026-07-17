import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Upload, Trash2, FileText, Search, CheckCircle2,
  Clock, AlertCircle, Loader2, X, ChevronLeft, Eye, Save, RefreshCw, Settings2
} from 'lucide-react'
import clsx from 'clsx'
import { useAuthStore } from '../store/auth'
import {
  apiListDocuments,
  apiUploadDocument,
  apiDeleteDocument,
  apiSearchDocuments,
  apiGetDocument,
  apiUpdateDocument,
  CHUNK_STRATEGY_LABELS,
  type DocumentOut,
  type DocumentDetail,
  type SearchResult,
} from '../api/client'

export default function DocumentsPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((s) => s.token)!
  const [docs, setDocs] = useState<DocumentOut[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
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
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    loadDocs()
  }, [])

  async function loadDocs() {
    setLoading(true)
    try {
      const list = await apiListDocuments(token)
      setDocs(list)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        const doc = await apiUploadDocument(token, file, { chunk_strategy: chunkStrategy })
        setDocs((prev) => [doc, ...prev])
      }
    } catch (e: any) {
      alert(e.message)
    } finally {
      setUploading(false)
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this document and all its chunks?')) return
    try {
      await apiDeleteDocument(token, id)
      setDocs((prev) => prev.filter((d) => d.id !== id))
      setSearchResults((prev) => prev?.filter((r) => r.document_id !== id) ?? null)
      if (selectedDoc?.id === id) {
        closeDetail()
      }
    } catch (e: any) {
      alert(e.message)
    }
  }

  async function handleSearch() {
    if (!searchQuery.trim()) return
    setSearching(true)
    setSearchResults(null)
    try {
      const results = await apiSearchDocuments(token, searchQuery.trim())
      setSearchResults(results)
    } catch (e: any) {
      alert(e.message)
    } finally {
      setSearching(false)
    }
  }

  async function openDetail(id: string) {
    setDetailLoading(true)
    try {
      const doc = await apiGetDocument(token, id)
      setSelectedDoc(doc)
      setEditTitle(doc.title)
    } catch (e: any) {
      alert(e.message)
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
      setDocs((prev) => prev.map((d) => (d.id === updated.id ? { ...d, ...updated } : d)))
      setSelectedDoc((prev) => (prev ? { ...prev, ...updated } : prev))
    } catch (e: any) {
      alert(e.message)
    } finally {
      setSaving(false)
    }
  }

  const selectedPreview = useMemo(() => {
    if (!selectedDoc) return ''
    return selectedDoc.content_preview || ''
  }, [selectedDoc])

  function formatSize(bytes: number) {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  function StatusBadge({ status }: { status: DocumentOut['status'] }) {
    const map = {
      ready: { icon: <CheckCircle2 size={12} />, label: 'Ready', cls: 'text-emerald-400 bg-emerald-400/10' },
      processing: { icon: <Loader2 size={12} className="animate-spin" />, label: 'Processing', cls: 'text-amber-400 bg-amber-400/10' },
      pending: { icon: <Clock size={12} />, label: 'Pending', cls: 'text-slate-400 bg-slate-400/10' },
      error: { icon: <AlertCircle size={12} />, label: 'Error', cls: 'text-red-400 bg-red-400/10' },
    }
    const s = map[status] ?? map.pending
    return (
      <span className={clsx('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium', s.cls)}>
        {s.icon}{s.label}
      </span>
    )
  }

  return (
    <div className="flex flex-col h-screen bg-[var(--bg)] text-[var(--text)]">
      <div className="flex items-center gap-3 px-6 h-14 border-b border-[var(--border)] flex-shrink-0">
        <button
          onClick={onBack}
          className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[var(--surface)] text-[var(--text-secondary)] hover:text-[var(--text)] transition-colors"
        >
          <ChevronLeft size={18} />
        </button>
        <h1 className="text-sm font-semibold">Documents</h1>
        <span className="ml-auto text-xs text-[var(--text-secondary)]">{docs.length} file{docs.length !== 1 ? 's' : ''}</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-6 py-6 space-y-6">
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files) }}
            onClick={() => fileInputRef.current?.click()}
            className={clsx(
              'border-2 border-dashed rounded-2xl p-10 flex flex-col items-center gap-3 cursor-pointer transition-all',
              dragOver ? 'border-[var(--accent)] bg-[var(--accent-dim)]' : 'border-[var(--border)] hover:border-[var(--accent-border)] hover:bg-[var(--surface)]'
            )}
          >
            {uploading ? <Loader2 size={28} className="animate-spin text-[var(--accent)]" /> : <Upload size={28} className="text-[var(--text-secondary)]" />}
            <div className="text-center">
              <p className="text-sm font-medium">{uploading ? 'Uploading…' : 'Drop files here or click to upload'}</p>
              <p className="text-xs text-[var(--text-secondary)] mt-1">PDF, TXT, MD, DOCX supported</p>
            </div>
            <div className="flex items-center gap-2 mt-2" onClick={(e) => e.stopPropagation()}>
              <Settings2 size={14} className="text-[var(--text-secondary)]" />
              <label className="text-xs text-[var(--text-secondary)]">分块策略：</label>
              <select
                value={chunkStrategy}
                onChange={(e) => setChunkStrategy(Number(e.target.value))}
                className="text-xs bg-[var(--surface)] border border-[var(--border)] rounded-lg px-2 py-1 focus:outline-none focus:border-[var(--accent)]"
              >
                {Object.entries(CHUNK_STRATEGY_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>{key}: {label}</option>
                ))}
              </select>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.txt,.md,.docx"
              className="hidden"
              onChange={(e) => handleFiles(e.target.files)}
            />
          </div>

          <div className="flex gap-2">
            <div className="flex-1 relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                placeholder="Semantic search across your documents…"
                className="w-full pl-9 pr-4 py-2.5 bg-[var(--surface)] border border-[var(--border)] rounded-xl text-sm focus:outline-none focus:border-[var(--accent)] transition-colors"
              />
            </div>
            <button
              onClick={handleSearch}
              disabled={searching || !searchQuery.trim()}
              className="px-4 py-2.5 bg-[var(--accent)] text-[var(--accent-foreground)] rounded-xl text-sm font-medium hover:opacity-90 disabled:opacity-40 transition-opacity"
            >
              {searching ? <Loader2 size={16} className="animate-spin" /> : 'Search'}
            </button>
            {searchResults !== null && (
              <button
                onClick={() => { setSearchResults(null); setSearchQuery('') }}
                className="px-3 py-2.5 bg-[var(--surface)] border border-[var(--border)] rounded-xl text-sm hover:bg-[var(--border)] transition-colors"
              >
                <X size={16} />
              </button>
            )}
          </div>

          {searchResults !== null && (
            <div className="space-y-2">
              <p className="text-xs text-[var(--text-secondary)] font-medium uppercase tracking-wider">
                {searchResults.length} result{searchResults.length !== 1 ? 's' : ''} for &ldquo;{searchQuery}&rdquo;
              </p>
              {searchResults.length === 0 ? (
                <p className="text-sm text-[var(--text-secondary)] py-4 text-center">No matching chunks found.</p>
              ) : (
                searchResults.map((r, i) => (
                  <div key={i} className="bg-[var(--surface)] rounded-xl p-4 border border-[var(--border)] space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-[var(--accent)]">{r.title}</span>
                      <span className="text-[11px] text-[var(--text-secondary)]">score {r.score.toFixed(3)} · chunk #{r.chunk_index}</span>
                    </div>
                    <p className="text-sm leading-relaxed text-[var(--text)]">{r.content}</p>
                  </div>
                ))
              )}
            </div>
          )}

          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 size={24} className="animate-spin text-[var(--text-secondary)]" />
            </div>
          ) : docs.length === 0 ? (
            <div className="text-center py-16">
              <FileText size={40} className="mx-auto text-[var(--text-secondary)] mb-3 opacity-40" />
              <p className="text-sm text-[var(--text-secondary)]">No documents yet. Upload one above.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {docs.map((doc) => (
                <div
                  key={doc.id}
                  className="group flex items-center gap-4 bg-[var(--surface)] border border-[var(--border)] rounded-xl px-4 py-3 hover:border-[var(--accent-border)] transition-colors"
                >
                  <FileText size={18} className="text-[var(--accent)] flex-shrink-0" />
                  <button className="flex-1 min-w-0 text-left" onClick={() => openDetail(doc.id)}>
                    <p className="text-sm font-medium truncate flex items-center gap-2">
                      {doc.title}
                      <Eye size={14} className="text-[var(--text-secondary)] opacity-0 group-hover:opacity-100 transition-opacity" />
                    </p>
                    <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                      {doc.file_type.toUpperCase()} · {formatSize(doc.file_size)} · {doc.chunk_count} chunks · 策略{doc.chunk_strategy}
                    </p>
                  </button>
                  <StatusBadge status={doc.status} />
                  <button
                    onClick={() => handleDelete(doc.id)}
                    className="opacity-0 group-hover:opacity-100 w-7 h-7 flex items-center justify-center rounded-lg hover:bg-red-500/10 text-[var(--text-secondary)] hover:text-red-400 transition-all"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {selectedDoc && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex justify-end" onClick={closeDetail}>
          <div
            className="w-full max-w-xl h-full bg-[var(--bg)] border-l border-[var(--border)] shadow-2xl overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="sticky top-0 bg-[var(--bg)] backdrop-blur border-b border-[var(--border)] px-5 py-4 flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold">Document details</h2>
                <p className="text-xs text-[var(--text-secondary)]">{selectedDoc.id}</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => openDetail(selectedDoc.id)}
                  className="w-9 h-9 rounded-lg bg-[var(--surface)] border border-[var(--border)] flex items-center justify-center hover:border-[var(--accent-border)]"
                  title="Refresh"
                >
                  <RefreshCw size={15} />
                </button>
                <button onClick={closeDetail} className="w-9 h-9 rounded-lg hover:bg-[var(--surface)] flex items-center justify-center">
                  <X size={16} />
                </button>
              </div>
            </div>

            <div className="p-5 space-y-5">
              {detailLoading ? (
                <div className="flex justify-center py-10">
                  <Loader2 size={24} className="animate-spin text-[var(--text-secondary)]" />
                </div>
              ) : (
                <>
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">Title</label>
                    <input
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      className="w-full px-3 py-2.5 rounded-xl bg-[var(--surface)] border border-[var(--border)] focus:outline-none focus:border-[var(--accent)]"
                    />
                    <button
                      onClick={saveDetail}
                      disabled={saving || !editTitle.trim()}
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[var(--accent)] text-[var(--accent-foreground)] text-sm font-medium disabled:opacity-40"
                    >
                      {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
                      Save title
                    </button>
                  </div>

                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div className="p-3 rounded-xl bg-[var(--surface)] border border-[var(--border)]">
                      <p className="text-xs text-[var(--text-secondary)]">Status</p>
                      <div className="mt-1"><StatusBadge status={selectedDoc.status} /></div>
                    </div>
                    <div className="p-3 rounded-xl bg-[var(--surface)] border border-[var(--border)]">
                      <p className="text-xs text-[var(--text-secondary)]">Version</p>
                      <p className="mt-1 font-medium">v{selectedDoc.version}</p>
                    </div>
                    <div className="p-3 rounded-xl bg-[var(--surface)] border border-[var(--border)]">
                      <p className="text-xs text-[var(--text-secondary)]">File size</p>
                      <p className="mt-1 font-medium">{formatSize(selectedDoc.file_size)}</p>
                    </div>
                    <div className="p-3 rounded-xl bg-[var(--surface)] border border-[var(--border)]">
                      <p className="text-xs text-[var(--text-secondary)]">Chunks</p>
                      <p className="mt-1 font-medium">{selectedDoc.chunk_count}</p>
                    </div>
                    <div className="p-3 rounded-xl bg-[var(--surface)] border border-[var(--border)] col-span-2">
                      <p className="text-xs text-[var(--text-secondary)]">分块策略</p>
                      <p className="mt-1 font-medium">{selectedDoc.chunk_strategy}: {CHUNK_STRATEGY_LABELS[selectedDoc.chunk_strategy] ?? '未知'}</p>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <p className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">Content preview</p>
                    <pre className="whitespace-pre-wrap text-sm leading-6 p-4 rounded-xl bg-[var(--surface)] border border-[var(--border)] min-h-36">{selectedPreview || 'No preview available.'}</pre>
                  </div>

                  <div className="space-y-2">
                    <p className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">Metadata</p>
                    <pre className="whitespace-pre-wrap text-xs leading-6 p-4 rounded-xl bg-[var(--surface)] border border-[var(--border)] overflow-x-auto">
                      {JSON.stringify(selectedDoc.metadata ?? {}, null, 2)}
                    </pre>
                  </div>

                  <div className="flex items-center justify-between pt-2 border-t border-[var(--border)]">
                    <button
                      onClick={() => handleDelete(selectedDoc.id)}
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-red-500/10 text-red-400 text-sm font-medium hover:bg-red-500/15"
                    >
                      <Trash2 size={15} />
                      Delete document
                    </button>
                    <span className="text-xs text-[var(--text-secondary)]">{selectedDoc.file_type.toUpperCase()} · {selectedDoc.created_at}</span>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
