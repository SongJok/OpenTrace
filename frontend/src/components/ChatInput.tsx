import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import { ArrowUp, Square } from 'lucide-react'
import clsx from 'clsx'
import { apiCancelResponse, apiChatStream, apiCreateConversation, type ReasoningStep } from '../api/client'
import { useAuthStore } from '../store/auth'
import { useChatCommands } from '../store/chatCommands'
import { useChatPreferences } from '../store/chatPreferences'
import { useChatStore } from '../store/chat'


type ChatInputVariant = 'default' | 'welcome'


export default function ChatInput({ variant = 'default' }: { variant?: ChatInputVariant }) {
  const token = useAuthStore((state) => state.token)!
  const store = useChatStore()
  const activeId = useChatStore((state) => state.activeId)
  const streaming = useChatStore((state) => state.streaming)
  const activeResponseId = useChatStore((state) => state.activeResponseId)
  const executionProfile = useChatPreferences((state) => state.executionProfile)
  const model = useChatPreferences((state) => state.model)
  const setModel = useChatPreferences((state) => state.setModel)
  const assistantProfileId = useChatPreferences((state) => state.assistantProfileId)
  const projectId = useChatPreferences((state) => state.projectId)
  const prefillText = useChatPreferences((state) => state.prefillText)
  const consumePrefill = useChatPreferences((state) => state.consumePrefill)
  const regenerate = useChatCommands((state) => state.regenerate)
  const consumeRegenerate = useChatCommands((state) => state.consumeRegenerate)
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (prefillText === null) return
    setText(prefillText)
    consumePrefill()
    textareaRef.current?.focus()
  }, [prefillText, consumePrefill])

  const runResponse = async (
    conversationId: string,
    query: string,
    assistantMessageId: string,
    retryResponseId?: string,
  ) => {
    const controller = new AbortController()
    abortRef.current = controller
    store.appendAssistantStreamingMessage(conversationId, { id: assistantMessageId })
    store.setStreaming(true)
    store.resetReasoning(conversationId, assistantMessageId)
    setError(null)
    await apiChatStream(
      token,
      conversationId,
      query,
      {
        onResponseCreated: (payload) => {
          const responseId = String(payload?.response_id || payload?.id || '')
          if (!responseId) return
          store.setActiveResponseId(responseId)
          store.setMessageResponseId(conversationId, assistantMessageId, responseId)
        },
        onReasoningStep: (step: ReasoningStep) => store.addReasoningStep(conversationId, step),
        onThinking: (payload) => {
          const stage = String(payload?.stage || payload?.intent?.task_type || '')
          if (stage) store.appendThinking(conversationId, stage)
        },
        onDelta: (chunk) => store.appendStreamingChunk(conversationId, chunk),
        onToolCall: (payload) => store.updateToolStatus(conversationId, {
          tool_name: String(payload?.name || payload?.tool_name || 'tool'),
          status: 'running',
          node_id: payload?.call_id,
        }),
        onToolResult: (payload) => store.updateToolResult(conversationId, {
          tool_name: String(payload?.name || payload?.tool_name || 'tool'),
          node_id: payload?.call_id,
          preview: JSON.stringify(payload?.result ?? payload),
        }),
        onApprovalRequired: (approvals) => {
          store.setMessageApprovals(conversationId, assistantMessageId, approvals)
          store.setActiveResponseId(null)
        },
        onFinalAnswer: (envelope) => {
          store.finishLastAssistantMessage(conversationId, envelope.content || '（空响应）')
          if (envelope.citations?.length) store.setLastAssistantCitations(conversationId, envelope.citations as any)
          if (envelope.annotations?.length) store.setLastAssistantAnnotations(conversationId, envelope.annotations as any)
          store.setLastAssistantTurnMeta(conversationId, envelope)
          store.setActiveResponseId(null)
        },
        onError: (streamError) => {
          const message = streamError instanceof Error ? streamError.message : String(streamError)
          store.failLastAssistantMessage(conversationId, message)
          setError(message)
        },
      },
      false,
      controller.signal,
      executionProfile,
      {
        retry_response_id: retryResponseId,
        assistant_profile_id: assistantProfileId ?? undefined,
        project_id: projectId ?? undefined,
        model,
      },
    )
  }

  const send = async () => {
    const query = text.trim()
    if (!query || streaming) return
    let conversationId = activeId
    if (!conversationId) {
      const conversation = await apiCreateConversation(token)
      store.addConversation(conversation)
      store.setActiveId(conversation.id)
      store.setMessages(conversation.id, [])
      conversationId = conversation.id
    }
    store.appendUserMessage(conversationId, { id: `user_${Date.now()}`, content: query })
    store.updateTitle(conversationId, query.slice(0, 40) + (query.length > 40 ? '…' : ''))
    setText('')
    try {
      await runResponse(conversationId, query, `assistant_${Date.now()}`)
    } catch (sendError) {
      if (!(sendError instanceof DOMException && sendError.name === 'AbortError')) {
        const message = sendError instanceof Error ? sendError.message : String(sendError)
        store.failLastAssistantMessage(conversationId, message)
        setError(message)
      }
    } finally {
      store.setStreaming(false)
      abortRef.current = null
    }
  }

  useEffect(() => {
    if (!regenerate || !activeId || streaming) return
    const request = regenerate
    consumeRegenerate()
    void runResponse(activeId, request.input ?? '', `assistant_${Date.now()}`, request.responseId)
      .finally(() => {
        store.setStreaming(false)
        abortRef.current = null
      })
  }, [regenerate, activeId, streaming])

  const stop = async () => {
    if (activeResponseId) await apiCancelResponse(token, activeResponseId).catch(() => undefined)
    abortRef.current?.abort()
    abortRef.current = null
    if (activeId) store.stopLastAssistantMessage(activeId)
    store.setActiveResponseId(null)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void send()
    }
  }

  return (
    <div className={clsx('mx-auto w-full px-4 pb-4', variant === 'welcome' ? 'max-w-3xl' : 'max-w-4xl')}>
      <div className="rounded-[26px] border border-[var(--border)] bg-[var(--surface-raised)] p-3 shadow-[0_8px_32px_rgba(0,0,0,0.08)] focus-within:border-[var(--accent)]/50">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          rows={variant === 'welcome' ? 4 : 2}
          placeholder="给 OpenTrace 发消息"
          aria-label="消息"
          className="max-h-56 min-h-12 w-full resize-none bg-transparent px-2 py-1 text-[15px] leading-6 outline-none placeholder:text-[var(--text-secondary)]"
        />
        <div className="mt-2 flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2 px-2 text-xs text-[var(--text-secondary)]">
            <select
              aria-label="选择模型"
              value={model}
              onChange={(event) => setModel(event.target.value as typeof model)}
              className="max-w-44 rounded-lg border border-[var(--border)] bg-transparent px-2 py-1 text-xs text-[var(--text-secondary)] outline-none focus:border-[var(--accent)]"
            >
              <option value="qwen3.7-max">Qwen 3.7 Max（默认）</option>
              <option value="qwen3.6-plus">Qwen 3.6 Plus</option>
              <option value="qwen3-14b">Qwen 3 14B</option>
              <option value="qwen3-8b">Qwen 3 8B（快速）</option>
            </select>
            <span className="hidden truncate sm:inline">
              {executionProfile === 'deep' ? '深度思考' : executionProfile === 'fast' ? '快速' : '自动'}
              {projectId ? ' · Project 上下文' : ''}
              {assistantProfileId ? ' · 个性化角色' : ''}
            </span>
          </div>
          {streaming ? (
            <button type="button" onClick={() => void stop()} aria-label="停止生成" title="停止生成" className="inline-flex h-9 min-w-16 items-center justify-center gap-1.5 rounded-full bg-[var(--text)] px-3 text-sm font-medium text-[var(--bg)]"><Square size={14} fill="currentColor" /><span>停止</span></button>
          ) : (
            <button type="button" disabled={!text.trim()} onClick={() => void send()} aria-label="确定发送" title="确定发送" className="inline-flex h-9 min-w-20 items-center justify-center gap-1.5 rounded-full bg-[var(--accent)] px-3 text-sm font-medium text-[var(--accent-foreground)] shadow-sm transition hover:bg-[var(--accent-hover)] disabled:cursor-not-allowed disabled:opacity-35"><ArrowUp size={16} /><span>确定</span></button>
          )}
        </div>
      </div>
      {error && <p role="alert" className="mt-2 px-3 text-xs text-red-500">{error}</p>}
      <p className="mt-2 text-center text-[11px] text-[var(--text-secondary)]">OpenTrace 可能会出错，请核对重要信息。写入操作会先请求授权。</p>
    </div>
  )
}
