import { type ChangeEvent, type KeyboardEvent, useEffect, useRef, useState } from 'react'
import { ArrowUp, FileText, LoaderCircle, Paperclip, Square, X } from 'lucide-react'
import clsx from 'clsx'
import { apiCancelResponse, apiChatStream, apiCreateConversation, apiDeleteAttachment, apiUploadAttachment, type AttachmentItem, type ReasoningStep } from '../api/client'
import {
  getAuthSessionSnapshot,
  isAuthSessionCurrent,
  type AuthSessionSnapshot,
  useAuthStore,
} from '../store/auth'
import { useChatCommands } from '../store/chatCommands'
import { useChatPreferences } from '../store/chatPreferences'
import { DEFAULT_TIMEZONE } from '../utils/timezone'
import { useChatStore } from '../store/chat'
import { createClientId } from '../utils/clientId'


type ChatInputVariant = 'default' | 'welcome'


export default function ChatInput({ variant = 'default' }: { variant?: ChatInputVariant }) {
  const token = useAuthStore((state) => state.token)!
  const sessionGeneration = useAuthStore((state) => state.sessionGeneration)
  const store = useChatStore()
  const activeId = useChatStore((state) => state.activeId)
  const streaming = useChatStore((state) => state.streaming)
  const activeResponseId = useChatStore((state) => state.activeResponseId)
  const executionProfile = useChatPreferences((state) => state.executionProfile)
  const assistantProfileId = useChatPreferences((state) => state.assistantProfileId)
  const projectId = useChatPreferences((state) => state.projectId)
  const dataSourceId = useChatPreferences((state) => state.dataSourceId)
  const prefillText = useChatPreferences((state) => state.prefillText)
  const consumePrefill = useChatPreferences((state) => state.consumePrefill)
  const regenerate = useChatCommands((state) => state.regenerate)
  const consumeRegenerate = useChatCommands((state) => state.consumeRegenerate)
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [attachments, setAttachments] = useState<AttachmentItem[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setText('')
    setAttachments([])
    setError(null)
  }, [sessionGeneration, token])

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
    attachmentIds: string[] = [],
    authSession: AuthSessionSnapshot = getAuthSessionSnapshot(),
  ) => {
    if (authSession.token !== token || !isAuthSessionCurrent(authSession)) return
    const isCurrentSession = () => isAuthSessionCurrent(authSession)
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
          if (!isCurrentSession()) return
          const responseId = String(payload?.response_id || payload?.id || '')
          if (!responseId) return
          store.setActiveResponseId(responseId)
          store.setMessageResponseId(conversationId, assistantMessageId, responseId)
        },
        onReasoningStep: (step: ReasoningStep) => {
          if (isCurrentSession()) store.addReasoningStep(conversationId, step)
        },
        onThinking: (payload) => {
          if (!isCurrentSession()) return
          const stage = String(payload?.stage || payload?.intent?.task_type || '')
          if (stage) store.appendThinking(conversationId, stage)
        },
        onDelta: (chunk) => {
          if (isCurrentSession()) store.appendStreamingChunk(conversationId, chunk)
        },
        onToolCall: (payload) => {
          if (!isCurrentSession()) return
          store.updateToolStatus(conversationId, {
            tool_name: String(payload?.name || payload?.tool_name || 'tool'),
            status: 'running',
            node_id: payload?.call_id,
          })
        },
        onToolResult: (payload) => {
          if (!isCurrentSession()) return
          store.updateToolResult(conversationId, {
            tool_name: String(payload?.name || payload?.tool_name || 'tool'),
            node_id: payload?.call_id,
            preview: JSON.stringify(payload?.result ?? payload),
          })
        },
        onApprovalRequired: (approvals) => {
          if (!isCurrentSession()) return
          store.setMessageApprovals(conversationId, assistantMessageId, approvals)
          store.setActiveResponseId(null)
        },
        onFinalAnswer: (envelope) => {
          if (!isCurrentSession()) return
          store.finishLastAssistantMessage(conversationId, envelope.content || '（空响应）')
          if (envelope.citations?.length) store.setLastAssistantCitations(conversationId, envelope.citations as any)
          if (envelope.annotations?.length) store.setLastAssistantAnnotations(conversationId, envelope.annotations as any)
          store.setLastAssistantTurnMeta(conversationId, envelope)
          store.setActiveResponseId(null)
        },
        onError: (streamError) => {
          if (!isCurrentSession()) return
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
        data_source_ids: dataSourceId ? [dataSourceId] : [],
        attachment_ids: attachmentIds,
        timezone: DEFAULT_TIMEZONE,
      },
    )
  }

  const ensureConversation = async (authSession: AuthSessionSnapshot) => {
    if (authSession.token !== token || !isAuthSessionCurrent(authSession)) return null
    const current = useChatStore.getState().activeId
    if (current) return current
    const conversation = await apiCreateConversation(token)
    if (!isAuthSessionCurrent(authSession)) return null
    store.addConversation(conversation)
    store.setActiveId(conversation.id)
    store.setMessages(conversation.id, [])
    return conversation.id
  }

  const selectFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    const files = Array.from(event.target.files ?? []).slice(0, Math.max(0, 10 - attachments.length))
    event.target.value = ''
    if (!files.length) return
    try {
      const conversationId = await ensureConversation(authSession)
      if (!conversationId || !isAuthSessionCurrent(authSession)) return
      for (const file of files) {
        if (!isAuthSessionCurrent(authSession)) return
        const localId = createClientId('attachment_')
        setAttachments((items) => [...items, { id: localId, file, name: file.name, size: file.size, status: 'uploading' }])
        try {
          const uploaded = await apiUploadAttachment(token, file, conversationId)
          if (!isAuthSessionCurrent(authSession)) return
          setAttachments((items) => items.map((item) => item.id === localId ? {
            ...item,
            status: 'done',
            serverId: uploaded.attachment_id,
            contentHash: uploaded.content_hash,
            contentSummary: uploaded.content_summary,
            isDuplicate: uploaded.is_duplicate,
            ingestStatus: uploaded.ingest_status,
          } : item))
        } catch (uploadError) {
          if (!isAuthSessionCurrent(authSession)) return
          setAttachments((items) => items.map((item) => item.id === localId ? {
            ...item,
            status: 'error',
            error: uploadError instanceof Error ? uploadError.message : String(uploadError),
          } : item))
        }
      }
    } catch (conversationError) {
      if (!isAuthSessionCurrent(authSession)) return
      setError(conversationError instanceof Error ? conversationError.message : String(conversationError))
    }
  }

  const removeAttachment = async (item: AttachmentItem) => {
    setAttachments((items) => items.filter((candidate) => candidate.id !== item.id))
    if (item.serverId) await apiDeleteAttachment(token, item.serverId).catch(() => undefined)
  }

  const send = async () => {
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    const query = text.trim()
    const readyAttachments = attachments.filter((item) => item.status === 'done' && item.serverId)
    if ((!query && !readyAttachments.length) || streaming || attachments.some((item) => item.status === 'uploading')) return
    let conversationId = activeId
    if (!conversationId) {
      const conversation = await apiCreateConversation(token)
      if (!isAuthSessionCurrent(authSession)) return
      store.addConversation(conversation)
      store.setActiveId(conversation.id)
      store.setMessages(conversation.id, [])
      conversationId = conversation.id
    }
    const displayText = query || `请处理这些附件：${readyAttachments.map((item) => item.name).join('、')}`
    store.appendUserMessage(conversationId, {
      id: `user_${Date.now()}`,
      content: displayText,
      attachments: readyAttachments.map((item) => ({ id: item.serverId!, filename: item.name, file_size: item.size, mime_type: item.file.type })),
    })
    store.updateTitle(conversationId, displayText.slice(0, 40) + (displayText.length > 40 ? '…' : ''))
    setText('')
    setAttachments([])
    try {
      await runResponse(
        conversationId,
        displayText,
        `assistant_${Date.now()}`,
        undefined,
        readyAttachments.map((item) => item.serverId!),
        authSession,
      )
    } catch (sendError) {
      if (!isAuthSessionCurrent(authSession)) return
      if (!(sendError instanceof DOMException && sendError.name === 'AbortError')) {
        const message = sendError instanceof Error ? sendError.message : String(sendError)
        store.failLastAssistantMessage(conversationId, message)
        setError(message)
      }
    } finally {
      if (isAuthSessionCurrent(authSession)) {
        store.setStreaming(false)
        abortRef.current = null
      }
    }
  }

  useEffect(() => {
    if (!regenerate || !activeId || streaming) return
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    const request = regenerate
    consumeRegenerate()
    void runResponse(activeId, request.input ?? '', `assistant_${Date.now()}`, request.responseId, [], authSession)
      .finally(() => {
        if (!isAuthSessionCurrent(authSession)) return
        store.setStreaming(false)
        abortRef.current = null
      })
  }, [regenerate, activeId, streaming, token])

  const stop = async () => {
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    if (activeResponseId) await apiCancelResponse(token, activeResponseId).catch(() => undefined)
    if (!isAuthSessionCurrent(authSession)) return
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
      <div className="rounded-[26px] border border-[var(--border)] bg-[var(--surface-raised)] p-3 shadow-[0_8px_32px_rgba(0,0,0,0.08)] focus-within:border-[var(--accent-border)]">
        <input ref={fileInputRef} type="file" multiple className="hidden" onChange={(event) => void selectFiles(event)} accept=".gif,.jpeg,.jpg,.png,.webp,.aac,.flac,.m4a,.mp3,.ogg,.wav,.avi,.flv,.mkv,.mov,.mp4,.webm,.wmv,.pdf,.txt,.md,.csv,.json,.docx,.xlsx,.pptx,.py,.js,.ts,.html,.css,.xml,.yaml,.yml,.log" />
        {attachments.length > 0 && <div className="mb-2 flex flex-wrap gap-2 px-1">{attachments.map((item) => <div key={item.id} className="flex max-w-full items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs"><span className="shrink-0">{item.status === 'uploading' ? <LoaderCircle size={14} className="animate-spin" /> : <FileText size={14} />}</span><span className="max-w-48 truncate">{item.name}</span>{item.status === 'error' && <span className="text-red-500">{item.error || '上传失败'}</span>}<button type="button" onClick={() => void removeAttachment(item)} aria-label={`移除 ${item.name}`} className="rounded p-0.5 hover:bg-[var(--surface-hover)]"><X size={13} /></button></div>)}</div>}
        <textarea
          data-chat-message-input
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
            <button type="button" onClick={() => fileInputRef.current?.click()} disabled={attachments.length >= 10 || streaming} aria-label="添加附件" title="添加图片、音视频或文件" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[var(--border)] hover:bg-[var(--surface-hover)] disabled:opacity-40"><Paperclip size={15} /></button>
            <span className="hidden truncate sm:inline">
              {executionProfile === 'deep' ? '深度思考' : executionProfile === 'fast' ? '快速' : '自动'}
              {projectId ? ' · Project 上下文' : ''}
              {assistantProfileId ? ' · 个性化角色' : ''}
            </span>
          </div>
          {streaming ? (
            <button type="button" onClick={() => void stop()} aria-label="停止生成" title="停止生成" className="inline-flex h-9 min-w-16 items-center justify-center gap-1.5 rounded-full bg-[var(--text)] px-3 text-sm font-medium text-[var(--bg)]"><Square size={14} fill="currentColor" /><span>停止</span></button>
          ) : (
            <button type="button" disabled={(!text.trim() && !attachments.some((item) => item.status === 'done')) || attachments.some((item) => item.status === 'uploading')} onClick={() => void send()} aria-label="确定发送" title="确定发送" className="inline-flex h-9 min-w-20 items-center justify-center gap-1.5 rounded-full bg-[var(--accent)] px-3 text-sm font-medium text-[var(--accent-foreground)] shadow-sm transition hover:bg-[var(--accent-hover)] disabled:cursor-not-allowed disabled:opacity-35"><ArrowUp size={16} /><span>确定</span></button>
          )}
        </div>
      </div>
      {error && <p role="alert" className="mt-2 px-3 text-xs text-red-500">{error}</p>}
      <p className="mt-2 text-center text-[11px] text-[var(--text-secondary)]">OpenTrace 可能会出错，请核对重要信息。写入操作会先请求授权。</p>
    </div>
  )
}
