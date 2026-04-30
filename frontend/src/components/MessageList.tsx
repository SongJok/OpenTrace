import { useEffect, useMemo, useRef, useState } from 'react'
import { useChatStore, type Message } from '../store/chat'
import TypingIndicator from './TypingIndicator'
import ChatMessage from './ChatMessage'

export default function MessageList() {
  const activeId = useChatStore((s) => s.activeId)
  const messages = useChatStore((s) => (activeId ? s.messages[activeId] ?? [] : []))
  const streaming = useChatStore((s) => s.streaming)

  const parentRef = useRef<HTMLDivElement>(null)
  const [isAtBottom, setIsAtBottom] = useState(true)

  const items = useMemo(() => messages, [messages])

  useEffect(() => {
    const el = parentRef.current
    if (!el) return
    const onScroll = () => {
      const threshold = 64
      const dist = el.scrollHeight - el.scrollTop - el.clientHeight
      setIsAtBottom(dist < threshold)
    }
    el.addEventListener('scroll', onScroll)
    onScroll()
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    if (!isAtBottom) return
    const el = parentRef.current
    if (!el) return
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight
    })
  }, [items.length, streaming, isAtBottom])

  if (!activeId) return null

  return (
    <div ref={parentRef} className="flex-1 overflow-y-auto bg-[var(--bg)]">
      <div className="max-w-3xl mx-auto px-4 py-8">
        <div className="mb-6 rounded-[28px] border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-xs text-[var(--text-secondary)] shadow-[0_10px_30px_rgba(0,0,0,0.12)]">
          对话内容将按任务、证据和执行链路自动整理展示
        </div>
        {items.map((msg) => (
          <MessageBubble key={`${msg.id}-${msg.status}`} msg={msg} />
        ))}

        {streaming && items[items.length - 1]?.role !== 'assistant' && (
          <div className="pt-2">
            <div className="flex animate-fade-in">
              <TypingIndicator />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function MessageBubble({ msg }: { msg: Message }) {
  if (msg.role === 'user') {
    return (
      <div className="flex items-start justify-end group animate-fade-in py-2">
        <ChatMessage message={msg} />
      </div>
    )
  }

  return (
    <div className="flex items-start animate-fade-in py-2">
      <div className="flex-1 min-w-0 prose text-[15px] leading-relaxed">
        <ChatMessage message={msg} />
        {msg.status === 'streaming' && <span className="animate-blink text-[#10a37f] ml-0.5">▋</span>}
      </div>
    </div>
  )
}
