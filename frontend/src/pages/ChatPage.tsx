import { useEffect, useRef, useState, useCallback } from 'react'
import { BarChart3, ChevronDown, Database, FileWarning, FileText, Package, User, Share2, MoreHorizontal, Sparkles, type LucideIcon } from 'lucide-react'
import Sidebar from '../components/Sidebar'
import MessageList, { type MessageListHandle } from '../components/MessageList'
import ChatInput from '../components/ChatInput'
import WelcomeScreen from '../components/WelcomeScreen'
import { apiGetMessages, apiListConversations } from '../api/client'
import { useAuthStore } from '../store/auth'
import { useChatStore } from '../store/chat'
import { getShowAvatars, setShowAvatars } from '../store/theme'

const QUICK_TAGS: Array<{ label: string; prefix: string; icon: LucideIcon }> = [
  { label: '总结一段文字', prefix: '请总结以下内容：', icon: FileText },
  { label: '分析数据', prefix: '/data_analysis ', icon: BarChart3 },
  { label: '搜索知识库', prefix: '/rag ', icon: Database },
  { label: '编写代码', prefix: '请帮我编写代码：', icon: Package },
]

function QuickTags() {
  function handleTagClick(prefix: string) {
    window.dispatchEvent(new CustomEvent('opentrace:prefill', { detail: { text: prefix + ' ', autoSend: false } }))
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
  const setMessages = useChatStore((s) => s.setMessages)
  const setConversations = useChatStore((s) => s.setConversations)
  const messages = useChatStore((s) => (activeId ? s.messages[activeId] ?? [] : []))
  const showWelcome = !activeId || messages.length === 0

  const messageListRef = useRef<MessageListHandle>(null)
  const [isAtBottom, setIsAtBottom] = useState(true)
  const [showAvatars, setShowAvatarsLocal] = useState(() => getShowAvatars())

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

  useEffect(() => {
    const onSwitch = async (ev: Event) => {
      const ce = ev as CustomEvent<{ conversationId?: string }>
      const conversationId = ce.detail?.conversationId
      if (!conversationId) return
      setActiveId(conversationId)
      const [msgs, convs] = await Promise.all([
        apiGetMessages(token, conversationId),
        apiListConversations(token),
      ])
      setMessages(conversationId, msgs)
      setConversations(convs)
    }
    window.addEventListener('opentrace:switch-conversation', onSwitch as EventListener)
    return () => window.removeEventListener('opentrace:switch-conversation', onSwitch as EventListener)
  }, [setActiveId, setMessages, token, setConversations])

  return (
    <div className="flex h-screen w-full overflow-hidden bg-[var(--bg)] text-[var(--text)]">
      <Sidebar />
      <div className="relative flex min-w-0 flex-1 flex-col bg-[var(--bg)]">
        {showWelcome ? (
          <div className="relative flex flex-1 flex-col justify-center overflow-hidden px-2 py-10 sm:px-6 animate-fade-in">
            <div className="pointer-events-none absolute inset-0">
              <div className="absolute left-1/2 top-[18%] h-72 w-[34rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,var(--hero-glow-secondary),transparent_72%)] blur-3xl opacity-80" />
              <div className="absolute left-1/2 top-[48%] h-96 w-[48rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,rgba(255,255,255,0.7),transparent_70%)] blur-3xl opacity-70" />
            </div>
            <div className="relative mx-auto flex w-full max-w-[960px] -translate-y-4 flex-col items-center">
              <WelcomeScreen />
              <ChatInput variant="welcome" />
            </div>
            <QuickTags />
          </div>
        ) : (
          <>
            <header className="flex h-14 flex-shrink-0 items-center justify-between border-b border-[var(--border-subtle)] px-4 sm:px-6">
              <button type="button" className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium text-[var(--text)] hover:bg-[var(--surface)]" aria-label="选择模型">
                <Sparkles size={16} className="text-[var(--accent)]" />
                <span>OpenTrace</span>
                <span className="text-[var(--text-secondary)]">· Auto</span>
                <ChevronDown size={14} className="text-[var(--text-secondary)]" />
              </button>
              <div className="flex items-center gap-1.5">
                <button type="button" aria-label="分享对话" title="分享对话" className="rounded-lg p-2 text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]"><Share2 size={16} /></button>
                <button type="button" aria-label="更多操作" title="更多操作" className="rounded-lg p-2 text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]"><MoreHorizontal size={18} /></button>
                <button
                  onClick={toggleAvatars}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] transition-colors ${
                    showAvatars
                      ? 'border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]'
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
