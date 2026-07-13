import { useEffect, useMemo, useState } from 'react'
import { t } from '../i18n'
import {
  Plus,
  Trash2,
  MessageSquare,
  ChevronLeft,
  ChevronRight,
  LogOut,
  FileText,
  Settings,
  Bell,
  Brain,
  ShieldAlert,
  Archive,
  ArchiveRestore,
  Pencil,
  Search,
  Plug,
  Database,
  Wrench,
  FileCode,
  ShieldCheck,
  Network,
} from 'lucide-react'
import clsx from 'clsx'
import { useNavigate } from 'react-router-dom'
import { useChatStore, type Conversation } from '../store/chat'
import { useAuthStore } from '../store/auth'
import {
  apiListConversations,
  apiCreateConversation,
  apiDeleteConversation,
  apiGetMessages,
  apiRenameConversation,
  apiArchiveConversation,
} from '../api/client'

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const [showTools, setShowTools] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')

  const token = useAuthStore((s) => s.token)!
  const displayName = useAuthStore((s) => s.displayName)
  const role = useAuthStore((s) => s.role)
  const logout = useAuthStore((s) => s.logout)
  const store = useChatStore()
  const navigate = useNavigate()

  const filteredConversations = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return store.conversations
    return store.conversations.filter((conv) => (conv.title || '').toLowerCase().includes(q))
  }, [search, store.conversations])

  async function refreshConversations() {
    const convs = await apiListConversations(token, {
      query: search,
      archived: showArchived,
    })
    store.setConversations(convs)
    if (convs.length > 0 && !store.activeId) {
      await selectConversation(convs[0])
    }
  }

  useEffect(() => {
    void refreshConversations().catch(console.error)
  }, [showArchived])

  async function selectConversation(conv: Conversation) {
    try {
      window.dispatchEvent(new Event('opentrace:stop-stream'))
      store.setActiveId(conv.id)
      store.setStreaming(false)
      if (!store.messages[conv.id]) {
        const msgs = await apiGetMessages(token, conv.id)
        store.setMessages(conv.id, msgs)
      }
      navigate('/chat')
    } catch (e: any) {
      alert(e?.message || '加载会话失败')
    }
  }

  async function newChat() {
    try {
      window.dispatchEvent(new Event('opentrace:stop-stream'))
      const conv = await apiCreateConversation(token)
      store.addConversation(conv)
      store.setActiveId(conv.id)
      store.setMessages(conv.id, [])
      navigate('/chat')
    } catch (e: any) {
      alert(e?.message || '创建会话失败')
    }
  }

  async function deleteConv(e: React.MouseEvent, id: string) {
    e.stopPropagation()
    try {
      await apiDeleteConversation(token, id)
      store.removeConversation(id)
    } catch (e: any) {
      alert(e?.message || '删除会话失败')
    }
  }

  async function toggleArchive(e: React.MouseEvent, id: string, archived: boolean) {
    e.stopPropagation()
    try {
      await apiArchiveConversation(token, id, archived)
      await refreshConversations()
    } catch (err: any) {
      alert(err?.message || '归档操作失败')
    }
  }

  async function saveRename(id: string) {
    const title = editingTitle.trim()
    if (!title) {
      setEditingId(null)
      return
    }
    try {
      const updated = await apiRenameConversation(token, id, title)
      store.updateConversationMeta(updated)
      setEditingId(null)
      setEditingTitle('')
    } catch (err: any) {
      alert(err?.message || '重命名失败')
    }
  }

  if (collapsed) {
    return (
      <div className="flex h-full w-14 flex-col items-center gap-2 border-r border-[var(--border)] bg-[var(--bg-secondary)] py-3 text-[var(--text-secondary)] shadow-[0_20px_50px_rgba(0,0,0,0.18)]">
        <button
          onClick={() => setCollapsed(false)}
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <ChevronRight size={16} />
        </button>
        <button
          onClick={newChat}
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <Plus size={16} />
        </button>
        <div className="my-1 h-px w-8 bg-[var(--border)]" />
        <button
          onClick={() => navigate('/documents')}
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <FileText size={16} className="cartoon-icon icon-documents" />
        </button>
        <button
          onClick={() => navigate('/databases')}
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <Database size={16} className="cartoon-icon icon-database" />
        </button>
        <button
          onClick={() => navigate('/memories')}
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <Brain size={16} className="cartoon-icon icon-memory" />
        </button>
        <button
          onClick={() => navigate('/tasks')}
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <Bell size={16} className="cartoon-icon icon-task" />
        </button>
        <button
          onClick={() => navigate('/audit')}
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <ShieldAlert size={16} className="cartoon-icon icon-audit" />
        </button>
        <button
          onClick={() => navigate('/integrations')}
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <Plug size={16} className="cartoon-icon icon-integrations" />
        </button>
        <button
          onClick={() => navigate('/skills')}
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <Wrench size={16} className="cartoon-icon icon-skills" />
        </button>
        <button
          onClick={() => navigate('/knowledge')}
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <Network size={16} className="cartoon-icon" />
        </button>
        {role === 'admin' && (
          <button
            onClick={() => navigate('/permissions')}
            className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
          >
            <ShieldCheck size={16} className="cartoon-icon icon-permissions" />
          </button>
        )}
        <button
          onClick={() => navigate('/settings')}
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <Settings size={16} className="cartoon-icon icon-settings" />
        </button>
      </div>
    )
  }

  return (
    <aside aria-label="会话侧栏" className="flex h-full w-[260px] max-md:w-[220px] flex-col border-r border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--text)] animate-slide-in">
      <div className="px-3 pb-3 pt-3">
        <div className="px-2 py-1">
          <div className="flex items-center justify-between">
            <button
              onClick={() => setCollapsed(true)}
              className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              onClick={newChat}
              className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
            >
              <Plus size={16} />
            </button>
          </div>
          <div className="mt-3">
            <div className="text-sm font-semibold text-[var(--text)]">OpenTrace</div>
            <div className="mt-0.5 text-xs text-[var(--text-secondary)]">你的对话</div>
          </div>
        </div>
      </div>

      <div className="px-4 pb-3 space-y-2">
        <div className="relative rounded-2xl border border-[var(--border)] bg-[var(--surface)]">
          <Search size={14} className="absolute left-3 top-3 text-[var(--text-secondary)]" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onBlur={() => {
              void refreshConversations().catch(console.error)
            }}
            placeholder="搜索会话"
            className="w-full rounded-2xl bg-transparent py-2.5 pl-8 pr-3 text-xs text-[var(--text)] placeholder:text-[var(--text-secondary)] focus:outline-none"
          />
        </div>
        <button
          onClick={() => setShowArchived((v) => !v)}
          className="w-full rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          {showArchived ? '查看未归档' : '查看归档会话'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-1">
        {filteredConversations.length === 0 && (
          <p className="py-8 text-center text-xs text-[var(--text-secondary)]">{t('nav.noConversations')}</p>
        )}
        <div className="space-y-1">
          {filteredConversations.map((conv) => (
            <div
              key={conv.id}
              onClick={() => selectConversation(conv)}
              onMouseEnter={() => setHoveredId(conv.id)}
              onMouseLeave={() => setHoveredId(null)}
              className={clsx(
                'group flex items-center gap-2 rounded-2xl px-3 py-2.5 cursor-pointer transition-colors text-sm',
                store.activeId === conv.id ? 'bg-[var(--accent-dim)] text-[var(--text)]' : 'text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]'
              )}
            >
              <MessageSquare size={14} className="flex-shrink-0 opacity-50" />
              {editingId === conv.id ? (
                <input
                  autoFocus
                  value={editingTitle}
                  onChange={(e) => setEditingTitle(e.target.value)}
                  onBlur={() => void saveRename(conv.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void saveRename(conv.id)
                    if (e.key === 'Escape') {
                      setEditingId(null)
                      setEditingTitle('')
                    }
                  }}
                  className="flex-1 border-b border-[var(--border)] bg-transparent text-[13px] text-[var(--text)] outline-none"
                />
              ) : (
                <span className="flex-1 truncate text-[13px]">{conv.title || t('nav.newConversation')}</span>
              )}
              {hoveredId === conv.id && editingId !== conv.id && (
                <div className="flex items-center gap-1">
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      setEditingId(conv.id)
                      setEditingTitle(conv.title || '')
                    }}
                    className="flex h-5 w-5 items-center justify-center rounded hover:bg-[var(--surface-raised)] hover:text-[var(--text)] transition-all"
                    title="重命名"
                  >
                    <Pencil size={12} />
                  </button>
                  <button
                    onClick={(e) => void toggleArchive(e, conv.id, !Boolean(conv.archived_at))}
                    className="flex h-5 w-5 items-center justify-center rounded hover:bg-[var(--surface-raised)] hover:text-[var(--text)] transition-all"
                    title={conv.archived_at ? '取消归档' : '归档'}
                  >
                    {conv.archived_at ? <ArchiveRestore size={12} /> : <Archive size={12} />}
                  </button>
                  <button
                    onClick={(e) => deleteConv(e, conv.id)}
                    className="flex h-5 w-5 items-center justify-center rounded hover:bg-[var(--surface-raised)] hover:text-[var(--text)] transition-all"
                    title="删除"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="border-t border-[var(--border)] px-3 py-2">
        <button
          type="button"
          onClick={() => setShowTools((value) => !value)}
          aria-expanded={showTools}
          className="mb-1 flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-xs text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]"
        >
          <span>工具与工作区</span>
          <ChevronRight size={14} className={clsx('transition-transform', showTools && 'rotate-90')} />
        </button>
        {showTools && <div className="grid grid-cols-2 gap-2">
          <NavButton icon={<FileText size={15} className="cartoon-icon icon-documents" />} label={t('nav.documents')} onClick={() => navigate('/documents')} />
          <NavButton icon={<Database size={15} className="cartoon-icon icon-database" />} label="数据库" onClick={() => navigate('/databases')} />
          <NavButton icon={<Brain size={15} className="cartoon-icon icon-memory" />} label={t('nav.memories')} onClick={() => navigate('/memories')} />
          <NavButton icon={<Bell size={15} className="cartoon-icon icon-task" />} label={t('nav.tasks')} onClick={() => navigate('/tasks')} />
          <NavButton icon={<ShieldAlert size={15} className="cartoon-icon icon-audit" />} label={t('nav.audit')} onClick={() => navigate('/audit')} />
          <NavButton icon={<Plug size={15} className="cartoon-icon icon-integrations" />} label={t('nav.integrations')} onClick={() => navigate('/integrations')} />
          <NavButton icon={<Wrench size={15} className="cartoon-icon icon-skills" />} label="Skills" onClick={() => navigate('/skills')} />
          <NavButton icon={<Network size={15} className="cartoon-icon" />} label="知识编排" onClick={() => navigate('/knowledge')} />
          <NavButton icon={<FileCode size={15} className="cartoon-icon icon-rules" />} label="规则" onClick={() => navigate('/rules')} />
          {role === 'admin' && (
            <NavButton icon={<ShieldCheck size={15} className="cartoon-icon icon-permissions" />} label="权限" onClick={() => navigate('/permissions')} />
          )}
          <NavButton icon={<Settings size={15} className="cartoon-icon icon-settings" />} label={t('nav.settings')} onClick={() => navigate('/settings')} />
        </div>}
      </div>

      <div className="border-t border-[var(--border)] px-4 py-3">
        <button
          onClick={logout}
          className="flex w-full items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5 text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-[var(--accent-dim)] text-xs font-semibold text-[var(--accent)]">
            {(displayName ?? 'U').slice(0, 2).toUpperCase()}
          </div>
          <span className="flex-1 truncate text-left text-[13px]">{displayName}</span>
          <LogOut size={14} />
        </button>
      </div>
    </aside>
  )
}

function NavButton({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode
  label: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-[13px] transition-colors text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]"
    >
      {icon}
      {label}
    </button>
  )
}
