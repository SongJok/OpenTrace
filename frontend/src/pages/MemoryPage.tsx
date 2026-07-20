import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, Plus, Trash2, Save, Pencil } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import {
  apiCreateMemory,
  apiDeleteMemory,
  apiGetMemorySettings,
  apiGetMemoryGraph,
  apiListMemories,
  apiSetMemorySettings,
  apiUpdateMemory,
  apiListMemoryInbox,
  apiResolveMemoryCandidate,
  type MemoryItem,
  type MemoryCandidateItem,
  type MemoryGraph,
} from '../api/client'

type MemoryType = 'semantic' | 'episodic' | 'procedural'

export default function MemoryPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((s) => s.token)!
  const [tab, setTab] = useState<MemoryType>('semantic')
  const [items, setItems] = useState<MemoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [memoryLearningEnabled, setMemoryLearningEnabled] = useState(true)
  const [preferenceLearningEnabled, setPreferenceLearningEnabled] = useState(true)
  const [draftTitle, setDraftTitle] = useState('')
  const [draftContent, setDraftContent] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const [editingContent, setEditingContent] = useState('')
  const [inbox, setInbox] = useState<MemoryCandidateItem[]>([])
  const [graph, setGraph] = useState<MemoryGraph>({ nodes: [], edges: [] })

  const filtered = useMemo(() => items.filter((i) => i.memory_type === tab), [items, tab])

  const loadAll = async () => {
    setLoading(true)
    try {
      const [semantic, episodic, procedural, settings, candidates, memoryGraph] = await Promise.all([
        apiListMemories(token, 'semantic'),
        apiListMemories(token, 'episodic'),
        apiListMemories(token, 'procedural'),
        apiGetMemorySettings(token),
        apiListMemoryInbox(token),
        apiGetMemoryGraph(token),
      ])
      setItems([...semantic, ...episodic, ...procedural])
      setMemoryLearningEnabled(settings.memory_learning_enabled)
      setPreferenceLearningEnabled(settings.preference_learning_enabled)
      setInbox(candidates)
      setGraph(memoryGraph)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadAll()
  }, [])

  const saveSettings = async () => {
    const cfg = await apiSetMemorySettings(token, {
      memory_learning_enabled: memoryLearningEnabled,
      preference_learning_enabled: preferenceLearningEnabled,
    })
    setMemoryLearningEnabled(cfg.memory_learning_enabled)
    setPreferenceLearningEnabled(cfg.preference_learning_enabled)
  }

  const createMemory = async () => {
    if (!draftContent.trim()) return
    await apiCreateMemory(token, {
      memory_type: tab,
      kind: tab === 'procedural' ? 'workflow' : 'fact',
      title: draftTitle.trim() || undefined,
      content: draftContent.trim(),
      tags: [],
      metadata: {},
      enabled: true,
      pinned: false,
    })
    setDraftTitle('')
    setDraftContent('')
    await loadAll()
  }

  const toggleEnabled = async (m: MemoryItem) => {
    await apiUpdateMemory(token, m.id, { enabled: !m.enabled })
    await loadAll()
  }

  const togglePinned = async (m: MemoryItem) => {
    await apiUpdateMemory(token, m.id, { pinned: !m.pinned })
    await loadAll()
  }

  const removeMemory = async (m: MemoryItem) => {
    if (!confirm('删除该记忆？')) return
    await apiDeleteMemory(token, m.id)
    await loadAll()
  }

  const startEdit = (m: MemoryItem) => {
    setEditingId(m.id)
    setEditingTitle(m.title || '')
    setEditingContent(m.content || '')
  }

  const saveEdit = async (m: MemoryItem) => {
    await apiUpdateMemory(token, m.id, {
      title: editingTitle.trim() || null,
      content: editingContent.trim(),
    })
    setEditingId(null)
    setEditingTitle('')
    setEditingContent('')
    await loadAll()
  }

  return (
    <div className="flex flex-col h-screen bg-[var(--bg)] text-[var(--text)]">
      <div className="flex items-center gap-3 px-6 h-14 border-b border-[var(--border)]">
        <button onClick={onBack} className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[var(--surface)]">
          <ChevronLeft size={18} />
        </button>
        <h1 className="text-sm font-semibold">Memories</h1>
      </div>

      <div className="max-w-4xl mx-auto w-full px-6 py-6 space-y-4 overflow-y-auto">
        <div className="rounded-xl border border-[var(--border)] p-4 bg-[var(--surface)] space-y-3">
          <div>
            <h2 className="text-sm font-semibold">记忆关系图</h2>
            <p className="mt-1 text-xs text-[var(--text-secondary)]">{graph.nodes.length} 个记忆节点 · {graph.edges.length} 条持久关系；相关记忆会在回答时进行一跳扩展。</p>
          </div>
          {graph.edges.length === 0 ? (
            <p className="text-sm text-[var(--text-secondary)]">随着稳定记忆增加，系统会自动建立同主题、支持与替代关系。</p>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {graph.edges.slice(0, 6).map((edge) => {
                const source = graph.nodes.find((node) => node.id === edge.source)
                const target = graph.nodes.find((node) => node.id === edge.target)
                return <div key={edge.id} className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs"><span className="font-medium">{source?.label || edge.source}</span><span className="mx-2 text-[var(--text-secondary)]">— {edge.relation} →</span><span className="font-medium">{target?.label || edge.target}</span></div>
              })}
            </div>
          )}
        </div>
        <div className="rounded-xl border border-[var(--border)] p-4 bg-[var(--surface)] space-y-3">
          <div><h2 className="text-sm font-semibold">记忆收件箱</h2><p className="mt-1 text-xs text-[var(--text-secondary)]">主动学习到但置信度不足或与旧记忆冲突的内容会在这里等待确认，并显示来源证据。</p></div>
          {inbox.length === 0 ? <p className="text-sm text-[var(--text-secondary)]">没有待确认记忆</p> : inbox.map((candidate) => (
            <div key={candidate.id} className="rounded-xl border border-[var(--border)] p-3">
              <p className="text-sm">{candidate.content}</p>
              <p className="mt-1 text-xs text-[var(--text-secondary)]">{candidate.kind} · {candidate.scope_type} · 置信度 {Math.round(candidate.confidence * 100)}%</p>
              {candidate.evidence?.excerpt && <blockquote className="mt-2 border-l-2 border-[var(--border)] pl-3 text-xs text-[var(--text-secondary)]">{candidate.evidence.excerpt}</blockquote>}
              <div className="mt-3 flex gap-2"><button onClick={() => void apiResolveMemoryCandidate(token, candidate.id, true).then(loadAll)} className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs text-[var(--accent-foreground)]">保留</button><button onClick={() => void apiResolveMemoryCandidate(token, candidate.id, false).then(loadAll)} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs">忽略</button></div>
            </div>
          ))}
        </div>
        <div className="rounded-xl border border-[var(--border)] p-4 bg-[var(--surface)] space-y-3">
          <div className="flex items-center justify-between">
            <div><h2 className="text-sm font-semibold">主动记忆设置</h2><p className="mt-1 text-xs text-[var(--text-secondary)]">对话完成后自动识别稳定偏好、身份事实、长期目标和工作流程；敏感及一次性内容不会保存。</p></div>
            <button onClick={() => void saveSettings()} className="px-3 py-1.5 text-xs rounded bg-[var(--accent)] text-[var(--accent-foreground)] inline-flex items-center gap-1">
              <Save size={12} /> 保存
            </button>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={memoryLearningEnabled} onChange={(e) => setMemoryLearningEnabled(e.target.checked)} />
            启用主动记忆学习
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={preferenceLearningEnabled} onChange={(e) => setPreferenceLearningEnabled(e.target.checked)} />
            启用偏好学习
          </label>
        </div>

        <div className="flex gap-2">
          {(['semantic', 'episodic', 'procedural'] as MemoryType[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded text-xs border ${tab === t ? 'bg-[var(--accent)] text-[var(--accent-foreground)] border-[var(--accent)]' : 'border-[var(--border)]'}`}
            >
              {t}
            </button>
          ))}
        </div>

        <div className="rounded-xl border border-[var(--border)] p-4 bg-[var(--surface)] space-y-3">
          <h3 className="text-sm font-semibold">新增记忆</h3>
          <input
            value={draftTitle}
            onChange={(e) => setDraftTitle(e.target.value)}
            placeholder="标题（可选）"
            className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
          />
          <textarea
            value={draftContent}
            onChange={(e) => setDraftContent(e.target.value)}
            placeholder="输入记忆内容"
            className="w-full rounded border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
            rows={3}
          />
          <button onClick={() => void createMemory()} className="px-3 py-1.5 rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-xs inline-flex items-center gap-1">
            <Plus size={12} /> 新增
          </button>
        </div>

        <div className="space-y-2">
          {loading ? (
            <p className="text-sm text-[var(--text-secondary)]">加载中...</p>
          ) : filtered.length === 0 ? (
            <p className="text-sm text-[var(--text-secondary)]">暂无该类型记忆</p>
          ) : (
            filtered.map((m) => (
              <div key={m.id} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-2 flex-1">
                    {editingId === m.id ? (
                      <>
                        <input
                          value={editingTitle}
                          onChange={(e) => setEditingTitle(e.target.value)}
                          className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-sm"
                          placeholder="标题（可选）"
                        />
                        <textarea
                          value={editingContent}
                          onChange={(e) => setEditingContent(e.target.value)}
                          className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-sm"
                          rows={3}
                        />
                      </>
                    ) : (
                      <>
                        <p className="text-sm font-medium">{m.title || '(无标题)'}</p>
                        <p className="text-sm whitespace-pre-wrap">{m.content}</p>
                      </>
                    )}
                    <p className="text-[11px] text-[var(--text-secondary)]">kind={m.kind} · access={m.access_count}{m.metadata?.learning_mode === 'proactive' ? ' · 主动学习' : m.metadata?.learning_mode === 'explicit' ? ' · 用户明确要求' : m.metadata?.learning_mode === 'reviewed' ? ' · 用户已确认' : ''}{m.pinned ? ' · 已置顶（每轮优先使用）' : ''}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {editingId === m.id ? (
                      <button onClick={() => void saveEdit(m)} className="px-2 py-1 rounded text-xs border border-emerald-300 text-emerald-500 inline-flex items-center gap-1">
                        <Save size={12} /> 保存
                      </button>
                    ) : (
                      <button onClick={() => startEdit(m)} className="px-2 py-1 rounded text-xs border border-[var(--border)] inline-flex items-center gap-1">
                        <Pencil size={12} /> 编辑
                      </button>
                    )}
                    <button onClick={() => void toggleEnabled(m)} className="px-2 py-1 rounded text-xs border border-[var(--border)]">
                      {m.enabled ? '禁用' : '启用'}
                    </button>
                    <button onClick={() => void togglePinned(m)} className="px-2 py-1 rounded text-xs border border-[var(--border)]">
                      {m.pinned ? '取消置顶' : '置顶'}
                    </button>
                    <button onClick={() => void removeMemory(m)} className="px-2 py-1 rounded text-xs border border-red-300 text-red-500 inline-flex items-center gap-1">
                      <Trash2 size={12} /> 删除
                    </button>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
