import { useEffect, useRef, useState, useCallback } from 'react'
import { BarChart3, BrainCircuit, Check, ChevronDown, Copy, Cpu, Database, FileWarning, Menu, User, Share2, MoreHorizontal, Sparkles, type LucideIcon } from 'lucide-react'
import Sidebar from '../components/Sidebar'
import MessageList, { type MessageListHandle } from '../components/MessageList'
import ChatInput from '../components/ChatInput'
import WelcomeScreen from '../components/WelcomeScreen'
import { apiCreateConversationShare, apiDeleteConversation, apiListAssistantProfiles, apiListConversations, apiUpdateConversation, type AssistantProfileItem } from '../api/client'
import { apiGetModelSettings, apiSelectModelSettings, withSelectedModel, type ModelSource, type UserModelSettings } from '../api/modelSettings'
import { getAuthSessionSnapshot, isAuthSessionCurrent, useAuthStore } from '../store/auth'
import { useChatStore } from '../store/chat'
import { getShowAvatars, setShowAvatars } from '../store/theme'
import { useChatPreferences } from '../store/chatPreferences'
import { useCompanyStore } from '../store/company'
import { copyTextToClipboard, formatConversationForCopy } from '../utils/clipboard'

const QUICK_TAGS: Array<{ label: string; prefix: string; icon: LucideIcon }> = [
  { label: '企业知识问答', prefix: '/rag ', icon: Database },
  { label: '企业数据问数', prefix: '/data_analysis ', icon: BarChart3 },
  { label: '询问企业大脑', prefix: '请基于企业大脑回答：', icon: BrainCircuit },
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
  const brandName = useCompanyStore((state) => state.brandName)
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
  const [showProfileMenu, setShowProfileMenu] = useState(false)
  const [modelSettings, setModelSettings] = useState<UserModelSettings | null>(null)
  const [modelSettingsSaving, setModelSettingsSaving] = useState(false)
  const [modelSettingsError, setModelSettingsError] = useState<string | null>(null)
  const [showModelMenu, setShowModelMenu] = useState(false)
  const [showMoreMenu, setShowMoreMenu] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)

  const selectProfile = (next: 'auto' | 'fast' | 'deep') => {
    setProfile(next)
    setShowProfileMenu(false)
  }

  const selectModel = async (source: ModelSource, selected: string) => {
    if (!modelSettings || modelSettingsSaving) return
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    const previous = modelSettings
    try {
      const optimistic = withSelectedModel(modelSettings, source, selected)
      setModelSettings(optimistic)
      setModelSettingsSaving(true)
      setModelSettingsError(null)
      const saved = await apiSelectModelSettings(token, source, selected)
      if (!isAuthSessionCurrent(authSession)) return
      setModelSettings(saved)
      setShowModelMenu(false)
    } catch (error) {
      if (!isAuthSessionCurrent(authSession)) return
      setModelSettings(previous)
      setModelSettingsError(error instanceof Error ? error.message : '切换模型失败')
    } finally {
      if (isAuthSessionCurrent(authSession)) setModelSettingsSaving(false)
    }
  }

  useEffect(() => {
    const authSession = getAuthSessionSnapshot()
    setModelSettings(null)
    setModelSettingsSaving(false)
    setModelSettingsError(null)
    setShowModelMenu(false)
    void apiGetModelSettings(token)
      .then((settings) => {
        if (!isAuthSessionCurrent(authSession)) return
        setModelSettings(settings)
      })
      .catch(() => {
        if (isAuthSessionCurrent(authSession)) setModelSettingsError('读取可用模型失败')
      })
  }, [token])

  useEffect(() => {
    let cancelled = false
    const authSession = getAuthSessionSnapshot()
    setAssistantProfiles([])
    void apiListAssistantProfiles(token).then((items) => {
      if (cancelled || !isAuthSessionCurrent(authSession)) return
      setAssistantProfiles(items)
      const selectedProfileId = useChatPreferences.getState().assistantProfileId
      if (!selectedProfileId || !items.some((item) => item.id === selectedProfileId)) {
        setAssistantProfileId(items.find((item) => item.is_default)?.id ?? items[0]?.id ?? null)
      }
    }).catch(() => {
      if (cancelled || !isAuthSessionCurrent(authSession)) return
      setAssistantProfiles([])
      setAssistantProfileId(null)
    })
    return () => { cancelled = true }
  }, [token])

  const activeModel = modelSettings?.active_selection.model || '默认模型'
  const availableFreeModels = modelSettings?.free.has_api_key ? modelSettings.free.models : []
  const availableCustomModels = modelSettings?.custom_models.filter((item) => item.has_api_key) ?? []

  const refreshConversations = async () => {
    const authSession = getAuthSessionSnapshot()
    const items = await apiListConversations(token)
    if (isAuthSessionCurrent(authSession)) setConversations(items)
  }

  const shareConversation = async () => {
    if (!activeId) return
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    const shared = await apiCreateConversationShare(token, activeId)
    if (!isAuthSessionCurrent(authSession)) return
    const copied = await copyTextToClipboard(`${window.location.origin}${shared.url}`)
    if (!isAuthSessionCurrent(authSession)) return
    window.alert(copied ? '分享链接已复制到剪贴板' : '分享链接已生成，但当前浏览器不允许写入剪贴板，请手动复制')
  }

  const copyConversation = async () => {
    if (!activeId) return
    const text = formatConversationForCopy(messages)
    const copied = await copyTextToClipboard(text)
    window.alert(copied ? '整个会话已复制到剪贴板' : '复制失败，请检查浏览器剪贴板权限')
    setShowMoreMenu(false)
  }

  const moreAction = async (action: 'rename' | 'pin' | 'delete') => {
    if (!activeId) return
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    if (action === 'rename') {
      const title = window.prompt('输入对话名称')
      if (title?.trim()) await apiUpdateConversation(token, activeId, { title: title.trim() })
    } else if (action === 'pin') {
      const current = (await apiListConversations(token)).find((item) => item.id === activeId)
      if (!isAuthSessionCurrent(authSession)) return
      await apiUpdateConversation(token, activeId, { pinned: !current?.pinned })
    } else if (window.confirm('确定删除此对话吗？此操作无法撤销。')) {
      await apiDeleteConversation(token, activeId)
      if (!isAuthSessionCurrent(authSession)) return
      setActiveId(null)
    }
    if (!isAuthSessionCurrent(authSession)) return
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
            <div className="relative mx-auto flex w-full max-w-[960px] -translate-y-4 flex-col items-center">
              <WelcomeScreen />
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
              <span className="hidden text-sm font-semibold sm:inline">{brandName}</span>
              <div className="relative min-w-0">
                <button
                  type="button"
                  disabled={!modelSettings}
                  onClick={() => { setShowModelMenu((value) => !value); setShowProfileMenu(false) }}
                  className="inline-flex max-w-48 items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-[var(--text)] hover:bg-[var(--surface)] disabled:opacity-60 sm:max-w-64"
                  aria-label="选择模型"
                  aria-expanded={showModelMenu}
                >
                  <Cpu size={15} className="shrink-0 text-[var(--accent)]" />
                  <span className="truncate font-medium">{activeModel}</span>
                  <ChevronDown size={14} className="shrink-0 text-[var(--text-secondary)]" />
                </button>
                {showModelMenu && modelSettings && (
                  <div role="menu" aria-label="可用模型" className="absolute left-0 top-10 z-30 w-72 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface-raised)] p-1 shadow-lg">
                    {availableFreeModels.length > 0 && <div className="px-3 pb-1 pt-2 text-[10px] font-medium text-[var(--text-secondary)]">通用免费模型</div>}
                    {availableFreeModels.map((model) => {
                      const selected = modelSettings.active_selection.source === 'free' && modelSettings.active_selection.model === model
                      return <button key={model} role="menuitemradio" aria-checked={selected} disabled={modelSettingsSaving} onClick={() => void selectModel('free', model)} className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface)] disabled:opacity-50 ${selected ? 'text-[var(--accent)]' : ''}`}><span className="min-w-0 flex-1 truncate font-mono">{model}</span>{selected && <Check size={14} className="shrink-0" />}</button>
                    })}
                    {availableCustomModels.length > 0 && <div className="mt-1 border-t border-[var(--border-subtle)] px-3 pb-1 pt-2 text-[10px] font-medium text-[var(--text-secondary)]">我的模型</div>}
                    {availableCustomModels.map((model) => {
                      const selected = modelSettings.active_selection.source === 'custom' && modelSettings.active_selection.custom_model_id === model.id
                      return <button key={model.id} role="menuitemradio" aria-checked={selected} disabled={modelSettingsSaving} onClick={() => void selectModel('custom', model.id)} className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-[var(--surface)] disabled:opacity-50 ${selected ? 'text-[var(--accent)]' : ''}`}><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{model.name}</span><span className="block truncate font-mono text-[10px] text-[var(--text-secondary)]">{model.model}</span></span>{selected && <Check size={14} className="shrink-0" />}</button>
                    })}
                    {availableFreeModels.length === 0 && availableCustomModels.length === 0 && <div className="px-3 py-4 text-sm text-[var(--text-secondary)]">当前账号暂无可用模型</div>}
                    {modelSettingsError && <div role="alert" className="border-t border-[var(--border-subtle)] px-3 py-2 text-xs text-red-500">{modelSettingsError}</div>}
                  </div>
                )}
              </div>
              <div className="relative">
                <button type="button" onClick={() => { setShowProfileMenu((value) => !value); setShowModelMenu(false) }} className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]" aria-label="选择推理模式" aria-expanded={showProfileMenu}>
                  <Sparkles size={15} className="text-[var(--accent)]" />
                  <span className="hidden sm:inline">{profile === 'auto' ? '自动' : profile === 'fast' ? '快速' : '深度思考'}</span>
                  <ChevronDown size={14} />
                </button>
                {showProfileMenu && <div role="menu" aria-label="推理模式" className="absolute left-0 top-10 z-30 w-36 rounded-xl border border-[var(--border)] bg-[var(--surface-raised)] p-1 shadow-lg">{([['auto','自动'], ['fast','快速'], ['deep','深度思考']] as const).map(([value, label]) => <button key={value} role="menuitemradio" aria-checked={profile === value} onClick={() => selectProfile(value)} className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface)] ${profile === value ? 'text-[var(--accent)]' : ''}`}><span className="flex-1">{label}</span>{profile === value && <Check size={14} />}</button>)}</div>}
              </div>
              </div>
              <div className="flex items-center gap-1.5">
                <select aria-label="助手角色" value={assistantProfileId ?? ''} onChange={(event) => setAssistantProfileId(event.target.value || null)} className="hidden rounded-lg border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs text-[var(--text-secondary)] sm:block">
                  {assistantProfiles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
                <button type="button" onClick={() => void shareConversation()} aria-label="分享对话" title="分享对话" className="rounded-lg p-2 text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]"><Share2 size={16} /></button>
                <div className="relative"><button type="button" onClick={() => setShowMoreMenu((v) => !v)} aria-label="更多操作" title="更多操作" className="rounded-lg p-2 text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]"><MoreHorizontal size={18} /></button>{showMoreMenu && <div className="absolute right-0 top-10 z-30 w-40 rounded-xl border border-[var(--border)] bg-[var(--surface-raised)] p-1 shadow-lg"><button onClick={() => void copyConversation()} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface)]"><Copy size={14} />复制整个会话</button><button onClick={() => void moreAction('rename')} className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface)]">重命名</button><button onClick={() => void moreAction('pin')} className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface)]">置顶/取消置顶</button><button onClick={() => void moreAction('delete')} className="w-full rounded-lg px-3 py-2 text-left text-sm text-red-500 hover:bg-[var(--surface)]">删除</button></div>}</div>
                <button
                  type="button"
                  onClick={toggleAvatars}
                  aria-pressed={showAvatars}
                  title={showAvatars ? '隐藏对话头像' : '显示对话头像'}
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
