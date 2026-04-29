import { useEffect } from 'react'
import { BarChart3, Database, FileWarning, FileText, Package, type LucideIcon } from 'lucide-react'
import Sidebar from '../components/Sidebar'
import MessageList from '../components/MessageList'
import ChatInput from '../components/ChatInput'
import WelcomeScreen from '../components/WelcomeScreen'
import { apiGetMessages, apiListConversations } from '../api/client'
import { useAuthStore } from '../store/auth'
import { useChatStore } from '../store/chat'

const QUICK_TAGS: Array<{ label: string; prefix: string; icon: LucideIcon }> = [
  { label: 'RAG', prefix: '/rag', icon: FileText },
  { label: '数据查询', prefix: '/data_query', icon: Database },
  { label: '数据分析', prefix: '/data_analysis', icon: BarChart3 },
  { label: '异常追踪', prefix: '/skills', icon: FileWarning },
  { label: '产品查询', prefix: '/product', icon: Package },
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
  }, [setActiveId, setMessages, token])

  return (
    <div className="flex h-screen w-full overflow-hidden bg-[var(--bg)] text-[var(--text)]">
      <Sidebar />
      <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden bg-[radial-gradient(circle_at_top,rgba(255,255,255,0.04),transparent_32%),linear-gradient(180deg,var(--bg-secondary),var(--bg))]">
        {showWelcome ? (
          <div className="relative flex flex-1 flex-col justify-center overflow-hidden px-2 py-10 sm:px-6 animate-fade-in">
            <div className="pointer-events-none absolute inset-0">
              <div className="absolute left-1/2 top-[18%] h-72 w-[34rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,var(--hero-glow-secondary),transparent_72%)] blur-3xl opacity-80" />
              <div className="absolute left-1/2 top-[48%] h-96 w-[48rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,rgba(255,255,255,0.7),transparent_70%)] blur-3xl opacity-70" />
            </div>
            <div className="relative mx-auto flex w-full max-w-[980px] -translate-y-4 flex-col items-center">
              <WelcomeScreen />
              <ChatInput variant="welcome" />
            </div>
            <QuickTags />
          </div>
        ) : (
          <>
            <div className="flex h-16 flex-shrink-0 items-center justify-between border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--bg)_92%,transparent)] px-6 backdrop-blur-xl">
              <div>
                <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--text-secondary)]">OpenTrace</div>
                <div className="mt-1 text-sm text-[var(--text)]">Chat · 证据驱动的对话工作台</div>
              </div>
              <div className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1 text-[11px] text-[var(--text-secondary)]">
                AI Workflow Console
              </div>
            </div>
            <MessageList />
            <ChatInput />
          </>
        )}
      </div>
    </div>
  )
}
