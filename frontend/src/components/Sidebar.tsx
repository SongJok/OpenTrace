import { useEffect, useMemo, useRef, useState } from 'react'
import { t } from '../i18n'
import {
  BookOpen,
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
  FolderKanban,
  Activity,
  CheckCheck,
  Building2,
  X,
  CalendarDays,
} from 'lucide-react'
import clsx from 'clsx'
import { useNavigate } from 'react-router-dom'
import { useChatStore, type Conversation } from '../store/chat'
import { getAuthSessionSnapshot, isAuthSessionCurrent, useAuthStore } from '../store/auth'
import {
  apiListConversations,
  apiCreateConversation,
  apiDeleteConversation,
  apiGetMessages,
  apiListNotifications,
  apiReadAllNotifications,
  apiReadNotification,
  apiResumeResponseWithRetry,
  apiRenameConversation,
  apiArchiveConversation,
  type NotificationItem,
} from '../api/client'

interface SidebarProps {
  mobileOpen?: boolean
  onMobileClose?: () => void
}

export default function Sidebar({ mobileOpen = false, onMobileClose }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const [showTools, setShowTools] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [showNotifications, setShowNotifications] = useState(false)
  const selectionGenerationRef = useRef(0)
  const selectionAbortRef = useRef<AbortController | null>(null)

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
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    const convs = await apiListConversations(token, {
      query: search,
      archived: showArchived,
    })
    if (!isAuthSessionCurrent(authSession)) return
    store.setConversations(convs)
    if (convs.length > 0 && !store.activeId) {
      await selectConversation(convs[0])
    }
  }

  useEffect(() => {
    void refreshConversations().catch(console.error)
  }, [showArchived, token])

  useEffect(() => {
    setNotifications([])
    setUnreadCount(0)
    setShowNotifications(false)
    const refreshNotifications = () => {
      const authSession = getAuthSessionSnapshot()
      if (authSession.token !== token) return
      void apiListNotifications(token, 30).then((result) => {
        if (!isAuthSessionCurrent(authSession)) return
        setNotifications(result.items)
        setUnreadCount(result.unread_count)
      }).catch(() => undefined)
    }
    refreshNotifications()
    const timer = window.setInterval(refreshNotifications, 20_000)
    return () => window.clearInterval(timer)
  }, [token])

  async function openNotification(notification: NotificationItem) {
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    if (!notification.read) {
      await apiReadNotification(token, notification.id)
      if (!isAuthSessionCurrent(authSession)) return
      setNotifications((items) => items.map((item) => item.id === notification.id ? { ...item, read: true } : item))
      setUnreadCount((count) => Math.max(0, count - 1))
    }
    setShowNotifications(false)
    navigate(notification.kind === 'alert' ? '/alerts' : notification.kind === 'calendar' ? '/calendar' : '/tasks')
    onMobileClose?.()
  }

  async function readAllNotifications() {
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    await apiReadAllNotifications(token)
    if (!isAuthSessionCurrent(authSession)) return
    setNotifications((items) => items.map((item) => ({ ...item, read: true })))
    setUnreadCount(0)
  }

  async function selectConversation(conv: Conversation) {
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    const selectionGeneration = selectionGenerationRef.current + 1
    selectionGenerationRef.current = selectionGeneration
    selectionAbortRef.current?.abort()
    const controller = new AbortController()
    selectionAbortRef.current = controller
    const isCurrentSelection = () => (
      isAuthSessionCurrent(authSession)
      && selectionGenerationRef.current === selectionGeneration
      && useChatStore.getState().activeId === conv.id
      && !controller.signal.aborted
    )
    try {
      store.setActiveId(conv.id)
      store.setStreaming(false)
      store.setActiveResponseId(null)
      const msgs = await apiGetMessages(token, conv.id, controller.signal)
      if (!isCurrentSelection()) return
      store.setMessages(conv.id, msgs)
      const pending = [...msgs].reverse().find((message) =>
        ['queued', 'in_progress'].includes(String(message?.status || ''))
        && typeof message?.response_id === 'string'
        && message?.role === 'assistant'
      )
      if (pending?.response_id) {
        if (!isCurrentSelection()) return
        store.setStreaming(true)
        store.setActiveResponseId(pending.response_id)
        store.resetReasoning(conv.id, String(pending.id))
        void apiResumeResponseWithRetry(token, pending.response_id, -1, {
          onDelta: (text) => {
            if (isCurrentSelection()) store.appendMessageStreamingChunk(conv.id, String(pending.id), text)
          },
          onReasoningStep: (step) => {
            if (isCurrentSelection()) store.addReasoningStep(conv.id, step)
          },
          onThinking: (payload) => {
            if (!isCurrentSelection()) return
            const stage = String(payload?.stage || payload?.intent?.task_type || '')
            if (stage) store.appendThinking(conv.id, stage)
          },
          onToolCall: (payload) => {
            if (!isCurrentSelection()) return
            store.updateToolStatus(conv.id, { tool_name: String(payload?.name || payload?.tool_name || 'tool'), status: 'running', node_id: payload?.call_id })
          },
          onToolResult: (payload) => {
            if (!isCurrentSelection()) return
            store.updateToolResult(conv.id, { tool_name: String(payload?.name || payload?.tool_name || 'tool'), node_id: payload?.call_id, preview: JSON.stringify(payload?.result ?? payload) })
          },
          onApprovalRequired: (approvals) => {
            if (isCurrentSelection()) store.setMessageApprovals(conv.id, String(pending.id), approvals)
          },
          onFinalAnswer: (envelope) => {
            if (!isCurrentSelection()) return
            store.finishAssistantMessage(conv.id, String(pending.id), envelope.content || '（空响应）')
            store.setActiveResponseId(null)
          },
          onError: (error) => {
            if (isCurrentSelection()) store.failAssistantMessage(conv.id, String(pending.id), error instanceof Error ? error.message : String(error))
          },
        }, controller.signal).catch(() => undefined)
      }
      if (!isCurrentSelection()) return
      navigate('/chat')
      onMobileClose?.()
    } catch (e: any) {
      if (!isCurrentSelection()) return
      alert(e?.message || '加载会话失败')
    }
  }

  useEffect(() => () => {
    selectionGenerationRef.current += 1
    selectionAbortRef.current?.abort()
  }, [])

  async function newChat() {
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    try {
      const conv = await apiCreateConversation(token)
      if (!isAuthSessionCurrent(authSession)) return
      store.addConversation(conv)
      store.setActiveId(conv.id)
      store.setMessages(conv.id, [])
      navigate('/chat')
      onMobileClose?.()
    } catch (e: any) {
      if (!isAuthSessionCurrent(authSession)) return
      alert(e?.message || '创建会话失败')
    }
  }

  async function newTemporaryChat() {
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    try {
      const conv = await apiCreateConversation(token, undefined, true)
      if (!isAuthSessionCurrent(authSession)) return
      store.setActiveId(conv.id)
      store.setMessages(conv.id, [])
      navigate('/chat')
      onMobileClose?.()
    } catch (e: any) {
      if (!isAuthSessionCurrent(authSession)) return
      alert(e?.message || '创建临时聊天失败')
    }
  }

  async function deleteConv(e: React.MouseEvent, id: string) {
    e.stopPropagation()
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    try {
      await apiDeleteConversation(token, id)
      if (!isAuthSessionCurrent(authSession)) return
      store.removeConversation(id)
    } catch (e: any) {
      if (!isAuthSessionCurrent(authSession)) return
      alert(e?.message || '删除会话失败')
    }
  }

  async function toggleArchive(e: React.MouseEvent, id: string, archived: boolean) {
    e.stopPropagation()
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    try {
      await apiArchiveConversation(token, id, archived)
      if (!isAuthSessionCurrent(authSession)) return
      await refreshConversations()
    } catch (err: any) {
      if (!isAuthSessionCurrent(authSession)) return
      alert(err?.message || '归档操作失败')
    }
  }

  async function saveRename(id: string) {
    const title = editingTitle.trim()
    if (!title) {
      setEditingId(null)
      return
    }
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    try {
      const updated = await apiRenameConversation(token, id, title)
      if (!isAuthSessionCurrent(authSession)) return
      store.updateConversationMeta(updated)
      setEditingId(null)
      setEditingTitle('')
    } catch (err: any) {
      if (!isAuthSessionCurrent(authSession)) return
      alert(err?.message || '重命名失败')
    }
  }

  if (collapsed) {
    return (
      <div className="hidden h-full w-14 flex-col items-center gap-2 border-r border-[var(--border)] bg-[var(--bg-secondary)] py-3 text-[var(--text-secondary)] shadow-[0_20px_50px_rgba(0,0,0,0.18)] md:flex">
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
          onClick={() => navigate('/work')}
          title="企业 AI 工作台"
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <FolderKanban size={16} />
        </button>
        <button
          onClick={() => navigate('/documents')}
          title="我的资料"
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
          onClick={() => navigate('/alerts')}
          title="主动预警"
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <Activity size={16} />
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
          onClick={() => navigate(store.activeId ? `/skills?session=${encodeURIComponent(store.activeId)}` : '/skills')}
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <Wrench size={16} className="cartoon-icon icon-skills" />
        </button>
        <button
          onClick={() => navigate('/knowledge-base')}
          title="企业知识库"
          className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
        >
          <BookOpen size={16} className="cartoon-icon" />
        </button>
        {role === 'admin' && (
          <button
            onClick={() => navigate('/knowledge')}
            title="知识治理中心"
            className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
          >
            <Network size={16} className="cartoon-icon" />
          </button>
        )}
        {role === 'admin' && (
          <button
            onClick={() => navigate('/enterprise-admin')}
            title="企业运营中心"
            className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
          >
            <Building2 size={16} className="cartoon-icon" />
          </button>
        )}
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
    <>
      {mobileOpen && (
        <button
          type="button"
          aria-label="关闭会话侧栏"
          className="fixed inset-0 z-40 bg-black/35 backdrop-blur-[1px] md:hidden"
          onClick={onMobileClose}
        />
      )}
      <aside
        aria-label="会话侧栏"
        className={clsx(
          'h-full w-[260px] flex-col border-r border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--text)] animate-slide-in md:flex',
          'max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-50 max-md:w-[min(86vw,320px)] max-md:shadow-2xl',
          mobileOpen ? 'max-md:flex' : 'max-md:hidden',
        )}
      >
      <div className="relative px-3 pb-3 pt-3">
        <div className="px-2 py-1">
          <div className="flex items-center justify-between">
            <button
              onClick={() => setCollapsed(true)}
              aria-label="收起会话侧栏"
              className="hidden h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)] md:flex"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              type="button"
              onClick={onMobileClose}
              aria-label="关闭会话侧栏"
              className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)] md:hidden"
            >
              <X size={16} />
            </button>
            <button
              type="button"
              onClick={() => setShowNotifications((value) => !value)}
              aria-label={`通知${unreadCount ? `，${unreadCount} 条未读` : ''}`}
              aria-expanded={showNotifications}
              className="relative flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
            >
              <Bell size={16} />
              {unreadCount > 0 && <span className="absolute -right-1 -top-1 min-w-4 rounded-full bg-red-500 px-1 text-center text-[10px] leading-4 text-white">{unreadCount > 99 ? '99+' : unreadCount}</span>}
            </button>
            <button
              onClick={newChat}
              className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"
            >
              <Plus size={16} />
            </button>
          </div>
          {showNotifications && <div className="absolute left-3 right-3 top-14 z-30 max-h-[420px] overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--bg)] shadow-2xl"><div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3"><div><div className="text-sm font-medium">通知</div><div className="text-[11px] text-[var(--text-secondary)]">任务完成与主动预警会显示在这里</div></div>{unreadCount > 0 && <button onClick={() => void readAllNotifications()} className="inline-flex items-center gap-1 text-xs text-[var(--accent)]"><CheckCheck size={13} />全部已读</button>}</div><div className="max-h-[340px] overflow-y-auto p-2">{notifications.length === 0 ? <div className="p-8 text-center text-xs text-[var(--text-secondary)]">暂无通知</div> : notifications.map((notification) => <button key={notification.id} onClick={() => void openNotification(notification)} className={clsx('mb-1 w-full rounded-xl px-3 py-2.5 text-left hover:bg-[var(--surface)]', !notification.read && 'bg-[var(--accent-dim)]')}><div className="flex items-start gap-2"><span className={clsx('mt-1.5 h-2 w-2 flex-none rounded-full', notification.level === 'error' ? 'bg-red-500' : notification.level === 'warning' ? 'bg-amber-500' : notification.level === 'success' ? 'bg-emerald-500' : 'bg-blue-500')} /><div className="min-w-0"><div className="truncate text-xs font-medium">{notification.title}</div>{notification.body && <div className="mt-1 line-clamp-2 text-[11px] text-[var(--text-secondary)]">{notification.body}</div>}<div className="mt-1 text-[10px] text-[var(--text-secondary)]">{notification.created_at ? new Date(notification.created_at).toLocaleString() : ''}</div></div></div></button>)}</div></div>}
          <div className="mt-3">
            <div className="text-sm font-semibold text-[var(--text)]">OpenTrace</div>
            <div className="mt-0.5 text-xs text-[var(--text-secondary)]">你的对话</div>
            <button onClick={() => void newTemporaryChat()} className="mt-2 text-xs text-[var(--accent)] hover:underline">开启临时聊天（30 天后删除）</button>
          </div>
        </div>
      </div>

      <div className="px-4 pb-3 space-y-2">
        <button onClick={() => navigate('/work')} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]"><FolderKanban size={15} /><span>企业 AI 工作台</span></button>
        <button onClick={() => navigate('/tasks')} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]"><Bell size={15} /><span>定时任务</span></button>
        <button onClick={() => navigate('/alerts')} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]"><Activity size={15} /><span>主动预警</span></button>
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
          <NavButton icon={<FileText size={15} className="cartoon-icon icon-documents" />} label="我的资料" onClick={() => navigate('/documents')} />
          <NavButton icon={<Database size={15} className="cartoon-icon icon-database" />} label="数据库" onClick={() => navigate('/databases')} />
          <NavButton icon={<Brain size={15} className="cartoon-icon icon-memory" />} label={t('nav.memories')} onClick={() => navigate('/memories')} />
          <NavButton icon={<Bell size={15} className="cartoon-icon icon-task" />} label={t('nav.tasks')} onClick={() => navigate('/tasks')} />
          <NavButton icon={<CalendarDays size={15} />} label="我的日历" onClick={() => navigate('/calendar')} />
          <NavButton icon={<Activity size={15} />} label="主动预警" onClick={() => navigate('/alerts')} />
          <NavButton icon={<ShieldAlert size={15} className="cartoon-icon icon-audit" />} label={t('nav.audit')} onClick={() => navigate('/audit')} />
          <NavButton icon={<Plug size={15} className="cartoon-icon icon-integrations" />} label={t('nav.integrations')} onClick={() => navigate('/integrations')} />
          <NavButton icon={<Wrench size={15} className="cartoon-icon icon-skills" />} label="Skills" onClick={() => navigate(store.activeId ? `/skills?session=${encodeURIComponent(store.activeId)}` : '/skills')} />
          <NavButton icon={<BookOpen size={15} className="cartoon-icon" />} label="企业知识库" onClick={() => navigate('/knowledge-base')} />
          {role === 'admin' && (
            <NavButton icon={<Network size={15} className="cartoon-icon" />} label="知识治理中心" onClick={() => navigate('/knowledge')} />
          )}
          <NavButton icon={<FileCode size={15} className="cartoon-icon icon-rules" />} label="规则" onClick={() => navigate('/rules')} />
          {role === 'admin' && (
            <NavButton icon={<Building2 size={15} className="cartoon-icon" />} label="企业运营中心" onClick={() => navigate('/enterprise-admin')} />
          )}
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
    </>
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
