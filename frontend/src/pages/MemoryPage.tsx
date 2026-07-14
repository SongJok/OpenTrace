import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, Plus, Trash2, Save, Pencil } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import {
  apiCreateMemory,
  apiDeleteMemory,
  apiGetMemorySettings,
  apiListMemories,
  apiSetMemorySettings,
  apiUpdateMemory,
  type MemoryItem,
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

  const filtered = useMemo(() => items.filter((i) => i.memory_type === tab), [items, tab])

  const loadAll = async () => {
    setLoading(true)
    try {
      const [semantic, episodic, procedural, settings] = await Promise.all([
        apiListMemories(token, 'semantic'),
        apiListMemories(token, 'episodic'),
        apiListMemories(token, 'procedural'),
        apiGetMemorySettings(token),
      ])
      setItems([...semantic, ...episodic, ...procedural])
      setMemoryLearningEnabled(settings.memory_learning_enabled)
      setPreferenceLearningEnabled(settings.preference_learning_enabled)
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
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">记忆学习设置</h2>
            <button onClick={() => void saveSettings()} className="px-3 py-1.5 text-xs rounded bg-[var(--accent)] text-[var(--accent-foreground)] inline-flex items-center gap-1">
              <Save size={12} /> 保存
            </button>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={memoryLearningEnabled} onChange={(e) => setMemoryLearningEnabled(e.target.checked)} />
            启用记忆学习
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
                    <p className="text-[11px] text-[var(--text-secondary)]">kind={m.kind} · access={m.access_count}{m.pinned ? ' · 已置顶（每轮优先使用）' : ''}</p>
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
