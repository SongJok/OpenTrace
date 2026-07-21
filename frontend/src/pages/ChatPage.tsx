import { useEffect, useRef, useState, useCallback } from 'react'
import { BarChart3, ChevronDown, Database, FileWarning, FileText, Menu, Package, User, Share2, MoreHorizontal, Sparkles, type LucideIcon } from 'lucide-react'
import Sidebar from '../components/Sidebar'
import MessageList, { type MessageListHandle } from '../components/MessageList'
import ChatInput from '../components/ChatInput'
import WelcomeScreen from '../components/WelcomeScreen'
import { apiCreateConversationShare, apiDeleteConversation, apiListAssistantProfiles, apiListConversations, apiListDatabases, apiListProjects, apiUpdateConversation, type AssistantProfileItem, type DataSourceItem, type ProjectItem } from '../api/client'
import { useAuthStore } from '../store/auth'
import { useChatStore } from '../store/chat'
import { getShowAvatars, setShowAvatars } from '../store/theme'
import { useChatPreferences } from '../store/chatPreferences'

const QUICK_TAGS: Array<{ label: string; prefix: string; icon: LucideIcon }> = [
  { label: '总结一段文字', prefix: '请总结以下内容：', icon: FileText },
  { label: '分析数据', prefix: '/data_analysis ', icon: BarChart3 },
  { label: '搜索知识库', prefix: '/rag ', icon: Database },
  { label: '编写代码', prefix: '请帮我编写代码：', icon: Package },
]

function QuickTags() {
  function handleTagClick(prefix: string) {
    useChatPreferences.getState().requestPrefill(prefix + ' ')
  }

  return (
    <div className="mt-8 flex flex-wrap items-center justify-center gap-3 px-4">
      {QUICK_TAGS.map((tag) => {
        const Icon = tag.icon
        return (
          <button
            key={tag.label}
            onClick={() => handleTagClick(tag.prefix)}
            className="flex items-center gap-2 rounded-2xl border border-[var(--hero-pill-border)] bg-[var(--hero-pill)] px-4 py-2 text-[13px] text-[var(--text-secondary)] shadow-[0_4px_18px_rgba(15,23,42,0.04)] transition-all hover:-translate-y-0.5 hover:text-[var(--text)]"
          >
            <Icon size={15} strokeWidth={1.9} />
            <span>{tag.label}</span>
          </button>
        )
      })}
    </div>
  )
}

export default function ChatPage() {
  const token = useAuthStore((s) => s.token)!
  const activeId = useChatStore((s) => s.activeId)
  const setActiveId = useChatStore((s) => s.setActiveId)
  const setConversations = useChatStore((s) => s.setConversations)
  const messages = useChatStore((s) => (activeId ? s.messages[activeId] ?? [] : []))
  const showWelcome = !activeId || messages.length === 0

  const messageListRef = useRef<MessageListHandle>(null)
  const [isAtBottom, setIsAtBottom] = useState(true)
  const [showAvatars, setShowAvatarsLocal] = useState(() => getShowAvatars())
  const profile = useChatPreferences((state) => state.executionProfile)
  const setProfile = useChatPreferences((state) => state.setExecutionProfile)
  const assistantProfileId = useChatPreferences((state) => state.assistantProfileId)
  const setAssistantProfileId = useChatPreferences((state) => state.setAssistantProfileId)
  const [assistantProfiles, setAssistantProfiles] = useState<AssistantProfileItem[]>([])
  const projectId = useChatPreferences((state) => state.projectId)
  const setProjectId = useChatPreferences((state) => state.setProjectId)
  const dataSourceId = useChatPreferences((state) => state.dataSourceId)
  const setDataSourceId = useChatPreferences((state) => state.setDataSourceId)
  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [dataSources, setDataSources] = useState<DataSourceItem[]>([])
  const [showProfileMenu, setShowProfileMenu] = useState(false)
  const [showMoreMenu, setShowMoreMenu] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)

  const selectProfile = (next: 'auto' | 'fast' | 'deep') => {
    setProfile(next)
    setShowProfileMenu(false)
  }

  useEffect(() => {
    void apiListAssistantProfiles(token).then((items) => {
      setAssistantProfiles(items)
      if (!assistantProfileId) setAssistantProfileId(items.find((item) => item.is_default)?.id ?? items[0]?.id ?? null)
    })
  }, [token])

  useEffect(() => {
    void apiListProjects(token).then(setProjects)
  }, [token])

  useEffect(() => {
    void apiListDatabases(token).then((items) => {
      const active = items.filter((item) => !item.status || item.status === 'active')
      setDataSources(active)
      if (dataSourceId && active.some((item) => item.id === dataSourceId)) return
      try {
        const saved = JSON.parse(localStorage.getItem('opentrace:selected_data_source') || 'null')
        setDataSourceId(active.some((item) => item.id === saved?.id) ? String(saved.id) : null)
      } catch {
        setDataSourceId(null)
      }
    }).catch(() => setDataSources([]))
  }, [token])

  const selectedProject = projects.find((item) => item.id === projectId)
  const availableDataSources = selectedProject
    ? dataSources.filter((item) => selectedProject.data_source_ids.includes(item.id))
    : dataSources

  useEffect(() => {
    if (dataSourceId && !availableDataSources.some((item) => item.id === dataSourceId)) {
      setDataSourceId(availableDataSources.length === 1 ? availableDataSources[0].id : null)
    } else if (!dataSourceId && availableDataSources.length === 1 && selectedProject) {
      setDataSourceId(availableDataSources[0].id)
    }
  }, [projectId, projects, dataSources])

  const selectProject = (nextProjectId: string | null) => {
    setProjectId(nextProjectId)
    const project = projects.find((item) => item.id === nextProjectId)
    const bound = project ? dataSources.filter((item) => project.data_source_ids.includes(item.id)) : dataSources
    if (dataSourceId && bound.some((item) => item.id === dataSourceId)) return
    setDataSourceId(bound.length === 1 ? bound[0].id : null)
  }

  const refreshConversations = async () => setConversations(await apiListConversations(token))

  const shareConversation = async () => {
    if (!activeId) return
    const shared = await apiCreateConversationShare(token, activeId)
    await navigator.clipboard?.writeText(`${window.location.origin}${shared.url}`)
    window.alert('分享链接已复制到剪贴板')
  }

  const moreAction = async (action: 'rename' | 'pin' | 'delete') => {
    if (!activeId) return
    if (action === 'rename') {
      const title = window.prompt('输入对话名称')
      if (title?.trim()) await apiUpdateConversation(token, activeId, { title: title.trim() })
    } else if (action === 'pin') {
      const current = (await apiListConversations(token)).find((item) => item.id === activeId)
      await apiUpdateConversation(token, activeId, { pinned: !current?.pinned })
    } else if (window.confirm('确定删除此对话吗？此操作无法撤销。')) {
      await apiDeleteConversation(token, activeId)
      setActiveId(null)
    }
    setShowMoreMenu(false)
    await refreshConversations()
  }

  const toggleAvatars = () => {
    const next = !showAvatars
    setShowAvatarsLocal(next)
    setShowAvatars(next)
  }

  const handleScrollStateChange = useCallback((atBottom: boolean) => {
    setIsAtBottom(atBottom)
  }, [])

  const scrollToBottom = () => {
    messageListRef.current?.scrollToBottom()
  }

  return (
    <div className="flex h-screen w-full overflow-hidden bg-[var(--bg)] text-[var(--text)]">
      <Sidebar mobileOpen={mobileSidebarOpen} onMobileClose={() => setMobileSidebarOpen(false)} />
      <div className="relative flex min-w-0 flex-1 flex-col bg-[var(--bg)]">
        {showWelcome ? (
          <div className="relative flex flex-1 flex-col justify-center overflow-hidden px-2 py-10 sm:px-6 animate-fade-in">
            <button
              type="button"
              aria-label="打开会话侧栏"
              onClick={() => setMobileSidebarOpen(true)}
              className="absolute left-3 top-3 z-30 flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--surface-raised)] text-[var(--text-secondary)] md:hidden"
            >
              <Menu size={17} />
            </button>
            <div className="pointer-events-none absolute inset-0">
              <div className="absolute left-1/2 top-[18%] h-72 w-[34rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,var(--hero-glow-secondary),transparent_72%)] blur-3xl opacity-80" />
              <div className="absolute left-1/2 top-[48%] h-96 w-[48rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,rgba(255,255,255,0.7),transparent_70%)] blur-3xl opacity-70" />
            </div>
            <div className="relative mx-auto flex w-full max-w-[960px] -translate-y-4 flex-col items-center">
              <WelcomeScreen />
              <div className="mb-3 flex w-full max-w-3xl flex-wrap justify-center gap-2 px-3">
                <select aria-label="Project" value={projectId ?? ''} onChange={(event) => selectProject(event.target.value || null)} className="max-w-48 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 py-2 text-xs text-[var(--text-secondary)]"><option value="">无 Project</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
                <select aria-label="企业数据源" value={dataSourceId ?? ''} onChange={(event) => setDataSourceId(event.target.value || null)} className="max-w-56 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 py-2 text-xs text-[var(--text-secondary)]"><option value="">自动选择数据源</option>{availableDataSources.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.type}</option>)}</select>
              </div>
              <ChatInput variant="welcome" />
            </div>
            <QuickTags />
          </div>
        ) : (
          <>
            <header className="flex h-14 flex-shrink-0 items-center justify-between gap-2 border-b border-[var(--border-subtle)] px-2 sm:px-6">
              <div className="flex min-w-0 items-center gap-1">
              <button
                type="button"
                aria-label="打开会话侧栏"
                onClick={() => setMobileSidebarOpen(true)}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[var(--text-secondary)] hover:bg-[var(--surface)] md:hidden"
              >
                <Menu size={17} />
              </button>
              <div className="relative min-w-0">
              <button type="button" onClick={() => setShowProfileMenu((v) => !v)} className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium text-[var(--text)] hover:bg-[var(--surface)]" aria-label="选择模型">
                <Sparkles size={16} className="text-[var(--accent)]" />
                <span>OpenTrace</span>
                <span className="hidden text-[var(--text-secondary)] sm:inline">· {profile === 'auto' ? '自动' : profile === 'fast' ? '快速' : '深度思考'}</span>
                <ChevronDown size={14} className="text-[var(--text-secondary)]" />
              </button>
              {showProfileMenu && <div className="absolute left-0 top-10 z-30 w-36 rounded-xl border border-[var(--border)] bg-[var(--surface-raised)] p-1 shadow-lg">{([['auto','自动'], ['fast','快速'], ['deep','深度思考']] as const).map(([value, label]) => <button key={value} onClick={() => selectProfile(value)} className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface)]">{label}</button>)}</div>}
              </div>
              </div>
              <div className="flex items-center gap-1.5">
                <select aria-label="Project" value={projectId ?? ''} onChange={(event) => selectProject(event.target.value || null)} className="hidden max-w-36 rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs text-[var(--text-secondary)] sm:block"><option value="">无 Project</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
                <select aria-label="企业数据源" value={dataSourceId ?? ''} onChange={(event) => setDataSourceId(event.target.value || null)} className="hidden max-w-40 rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs text-[var(--text-secondary)] lg:block"><option value="">自动数据源</option>{availableDataSources.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.type}</option>)}</select>
                <select aria-label="助手角色" value={assistantProfileId ?? ''} onChange={(event) => setAssistantProfileId(event.target.value || null)} className="hidden rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs text-[var(--text-secondary)] sm:block">
                  {assistantProfiles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
                <button type="button" onClick={() => void shareConversation()} aria-label="分享对话" title="分享对话" className="rounded-lg p-2 text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]"><Share2 size={16} /></button>
                <div className="relative"><button type="button" onClick={() => setShowMoreMenu((v) => !v)} aria-label="更多操作" title="更多操作" className="rounded-lg p-2 text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]"><MoreHorizontal size={18} /></button>{showMoreMenu && <div className="absolute right-0 top-10 z-30 w-32 rounded-xl border border-[var(--border)] bg-[var(--surface-raised)] p-1 shadow-lg"><button onClick={() => void moreAction('rename')} className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface)]">重命名</button><button onClick={() => void moreAction('pin')} className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface)]">置顶/取消置顶</button><button onClick={() => void moreAction('delete')} className="w-full rounded-lg px-3 py-2 text-left text-sm text-red-500 hover:bg-[var(--surface)]">删除</button></div>}</div>
                <button
                  onClick={toggleAvatars}
                  className={`hidden items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] transition-colors sm:inline-flex ${
                    showAvatars
                      ? 'border-[var(--accent)] bg-[var(--accent-dim)] text-[var(--accent)]'
                      : 'border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]'
                  }`}
                >
                  <User size={12} />
                  头像
                </button>
              </div>
            </header>
            <MessageList ref={messageListRef} onScrollStateChange={handleScrollStateChange} showAvatars={showAvatars} />
            <div className="relative flex-shrink-0">
              {!isAtBottom && (
                <div className="pointer-events-none absolute inset-x-0 bottom-full z-30 mx-auto w-full max-w-4xl px-6">
                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={scrollToBottom}
                      aria-label="跳转到最新消息"
                      title="回到底部"
                      className="pointer-events-auto inline-flex h-9 w-9 items-center justify-center rounded-full text-[var(--text-secondary)]/70 transition-all duration-200 hover:-translate-y-0.5 hover:text-[var(--text)]"
                    >
                      <ChevronDown size={16} strokeWidth={2.4} />
                    </button>
                  </div>
                </div>
              )}
              <ChatInput />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
