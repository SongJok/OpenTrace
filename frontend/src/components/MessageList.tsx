import { useEffect, useImperativeHandle, useMemo, useRef, useState, forwardRef } from 'react'
import { useChatStore, type Message } from '../store/chat'
import TypingIndicator from './TypingIndicator'
import ChatMessage from './ChatMessage'
import { QuestionerAvatar, ResponderAvatar } from './Avatar'

export interface MessageListHandle {
  scrollToBottom: () => void
}

interface MessageListProps {
  onScrollStateChange?: (isAtBottom: boolean) => void
  showAvatars?: boolean
}

const MessageList = forwardRef<MessageListHandle, MessageListProps>(function MessageList(
  { onScrollStateChange, showAvatars = false },
  ref,
) {
  const activeId = useChatStore((s) => s.activeId)
  const messages = useChatStore((s) => (activeId ? s.messages[activeId] ?? [] : []))
  const streaming = useChatStore((s) => s.streaming)

  const parentRef = useRef<HTMLDivElement>(null)
  const [isAtBottom, setIsAtBottom] = useState(true)

  const items = useMemo(() => messages, [messages])

  useImperativeHandle(ref, () => ({
    scrollToBottom: () => {
      const el = parentRef.current
      if (!el) return
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    },
  }))

  useEffect(() => {
    onScrollStateChange?.(isAtBottom)
  }, [isAtBottom, onScrollStateChange])

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
    <div ref={parentRef} className="relative flex-1 overflow-y-auto bg-[var(--bg)]">
      <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6 sm:py-8">
        {items.map((msg) => (
          <MessageBubble key={`${msg.id}-${msg.status}`} msg={msg} showAvatar={showAvatars} />
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
})

export default MessageList

function MessageBubble({ msg, showAvatar }: { msg: Message; showAvatar?: boolean }) {
  if (msg.role === 'user') {
    return (
      <div className="group flex w-full items-start justify-end gap-3 py-1.5 animate-fade-in">
        <ChatMessage message={msg} onBranch={() => window.dispatchEvent(new CustomEvent('opentrace:branch', { detail: { messageId: msg.id } }))} />
        {showAvatar && <QuestionerAvatar />}
      </div>
    )
  }

  return (
    <div className="flex w-full items-start gap-3 py-1.5 animate-fade-in">
      {showAvatar && <ResponderAvatar />}
      <div className="flex-1 min-w-0">
        <ChatMessage message={msg} />
        {msg.status === 'streaming' && <span className="animate-blink text-[#10a37f] ml-0.5">▋</span>}
      </div>
    </div>
  )
}
