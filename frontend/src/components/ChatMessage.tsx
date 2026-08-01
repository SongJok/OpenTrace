import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { CalendarDays, Check, ChevronDown, Copy, FileText, GitBranch, RefreshCw, ThumbsDown, ThumbsUp } from 'lucide-react'
import type { Message } from '../store/chat'
import { useChatStore } from '../store/chat'
import { getAuthSessionSnapshot, isAuthSessionCurrent, useAuthStore } from '../store/auth'
import { copyTextToClipboard } from '../utils/clipboard'
import { apiBranchConversation, apiGetMessages, apiGetResponse, apiListConversations, apiListResponseSiblings, apiResolveResponseApproval, apiResumeResponseWithRetry, apiSetActiveResponse, apiSubmitFeedback } from '../api/client'
import { useChatCommands } from '../store/chatCommands'
import { useCompanyStore } from '../store/company'

const MarkdownMessage = lazy(() => import('./MarkdownMessage'))

interface Citation {
  source?: string
  title: string
  url?: string
  relevance?: number
}

interface ChatMessageProps {
  /** Store-backed message used by MessageList. */
  message?: Message
  /** Lightweight standalone API retained for embeds. */
  role?: 'user' | 'assistant'
  content?: string
  isStreaming?: boolean
  reasoningSteps?: unknown[]
  citations?: Citation[]
  onBranch?: () => void
}

type ToolCard =
  | { type: 'time'; data: Record<string, unknown> }
  | { type: 'weather'; data: Record<string, unknown> }
  | { type: 'table'; data: { title?: string; columns: string[]; rows: Record<string, unknown>[] } }

function balancedJsonEnd(value: string, start: number): number {
  const opener = value[start]
  const closer = opener === '{' ? '}' : ']'
  if (opener !== '{' && opener !== '[') return -1
  let depth = 0
  let quoted = false
  let escaped = false
  for (let index = start; index < value.length; index += 1) {
    const char = value[index]
    if (quoted) {
      if (escaped) escaped = false
      else if (char === '\\') escaped = true
      else if (char === '"') quoted = false
      continue
    }
    if (char === '"') quoted = true
    else if (char === opener) depth += 1
    else if (char === closer) {
      depth -= 1
      if (depth === 0) return index + 1
    }
  }
  return -1
}

function cardFromJson(value: string): ToolCard | null {
  try {
    const parsed: unknown = JSON.parse(value)
    if (Array.isArray(parsed) && parsed.length > 0 && parsed.every((row) => row && typeof row === 'object' && !Array.isArray(row))) {
      const rows = parsed as Record<string, unknown>[]
      return { type: 'table', data: { columns: Object.keys(rows[0]), rows } }
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    const data = parsed as Record<string, unknown>
    if (data.type === 'time' || typeof data.displayTime === 'string') return { type: 'time', data }
    if (data.type === 'table' && Array.isArray(data.rows)) {
      const rows = data.rows.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object' && !Array.isArray(row))
      const columns = Array.isArray(data.columns) ? data.columns.map(String) : Object.keys(rows[0] ?? {})
      return { type: 'table', data: { title: typeof data.title === 'string' ? data.title : undefined, columns, rows } }
    }
    if ((typeof data.city === 'string' || typeof data.location === 'string') && (data.temperature !== undefined || data.weather !== undefined || data.current !== undefined)) {
      return { type: 'weather', data }
    }
  } catch {
    // A normal message can contain braces or JSON-looking prose.
  }
  return null
}

/** Compatibility parser for historical text payloads. New Responses items are typed. */
export function tryParseToolCard(content: string): ToolCard | null {
  const text = content.trim()
  const direct = cardFromJson(text)
  if (direct) return direct
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] !== '{' && text[index] !== '[') continue
    const end = balancedJsonEnd(text, index)
    if (end < 0) continue
    const card = cardFromJson(text.slice(index, end))
    if (card) return card
  }
  return null
}

export function stripJsonBlocks(content: string): string {
  let text = content.trim()
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] !== '{' && text[index] !== '[') continue
    const end = balancedJsonEnd(text, index)
    if (end < 0) break
    if (cardFromJson(text.slice(index, end))) {
      text = `${text.slice(0, index)}${text.slice(end)}`
      index = -1
    }
  }
  return text.trim()
}

function parseEpistemicMeta(messageText: string): { level?: 'FACT' | 'DOCUMENT' | 'SEARCH' | 'MEMORY' | 'INFERENCE' | 'SPECULATION' } {
  const icon = messageText.match(/^([📊📄🔗🧠💡⚠️])\s+/)?.[1]
  const levels = { '📊': 'FACT', '📄': 'DOCUMENT', '🔗': 'SEARCH', '🧠': 'MEMORY', '💡': 'INFERENCE', '⚠️': 'SPECULATION' } as const
  return { level: icon ? levels[icon as keyof typeof levels] : undefined }
}

function levelBadge(level?: string) {
  return level ? <span className="ml-2 rounded border border-[var(--border)] px-1.5 py-0.5 text-[10px] text-[var(--text-secondary)]">{level}</span> : null
}

function TimeCard({ data }: { data: Record<string, unknown> }) {
  return <div className="mt-2 rounded-xl border border-[var(--border)] px-3 py-2 text-sm">{String(data.displayTime ?? data.time ?? '')}</div>
}

function WeatherCard({ data }: { data: Record<string, unknown> }) {
  const current = data.current && typeof data.current === 'object' ? data.current as Record<string, unknown> : {}
  return <div className="mt-2 rounded-xl border border-[var(--border)] px-3 py-2 text-sm"><div>{String(data.city ?? data.location ?? '天气')}</div><div>{String(current.condition ?? data.weather ?? '')}</div><div>温度</div><div>{String(current.temperature ?? data.temperature ?? '')}</div><div>湿度</div><div>{String(current.humidity ?? data.humidity ?? '')}</div></div>
}

function ToolCardView({ toolCard }: { toolCard: ToolCard | null }) {
  if (toolCard?.type === 'time') {
    return <TimeCard data={toolCard.data} />
  }
  if (toolCard?.type === 'weather') {
    return <WeatherCard data={toolCard.data} />
  }
  if (!toolCard) return null
  return <div className="mt-2 overflow-x-auto rounded-xl border border-[var(--border)]"><div className="px-3 py-2 text-sm font-medium">{toolCard.data.title ?? '数据结果'}</div><table className="w-full text-sm"><thead><tr>{toolCard.data.columns.map((column) => <th className="px-3 py-2 text-left" key={column}>{column}</th>)}</tr></thead><tbody>{toolCard.data.rows.slice(0, 50).map((row, index) => <tr key={index}>{toolCard.data.columns.map((column) => <td className="px-3 py-2" key={column}>{String(row[column] ?? '')}</td>)}</tr>)}</tbody></table></div>
}

export default function ChatMessage({ message, role, content, isStreaming = false, reasoningSteps, citations, onBranch }: ChatMessageProps) {
  const brandName = useCompanyStore((state) => state.brandName)
  const contentRef = useRef<HTMLDivElement>(null)
  const [isHovered, setIsHovered] = useState(false)
  const [showCitations, setShowCitations] = useState(false)
  const [copied, setCopied] = useState(false)
  const [resolvingApproval, setResolvingApproval] = useState<string | null>(null)
  const [approvalError, setApprovalError] = useState<string | null>(null)
  const token = useAuthStore((state) => state.token)
  const activeConversationId = useChatStore((state) => state.activeId)
  const store = useChatStore()
  const requestRegenerate = useChatCommands((state) => state.requestRegenerate)
  const resolvedRole = message?.role === 'user' ? 'user' : role === 'user' ? 'user' : 'assistant'
  const resolvedContent = message?.status === 'streaming' ? message.streamText : message?.finalText ?? content ?? ''
  const resolvedStreaming = message?.status === 'streaming' || isStreaming
  const resolvedSteps = message?.reasoning_steps ?? reasoningSteps ?? []
  const resolvedCitations = (message?.citations ?? citations ?? []) as Citation[]
  const annotations = message?.annotations
  const evidenceRefs = message?.turn_meta?.evidence_refs ?? []
  const progress = message?.progress ?? []
  const messageAttachments = message?.attachments ?? []
  const toolCard = useMemo(() => resolvedRole === 'assistant' ? tryParseToolCard(resolvedContent) : null, [resolvedContent, resolvedRole])
  const visibleContent = useMemo(() => toolCard ? stripJsonBlocks(resolvedContent) : resolvedContent, [resolvedContent, toolCard])
  const epistemic = useMemo(() => parseEpistemicMeta(visibleContent), [visibleContent])
  const sourceRatio = useMemo(() => {
    const refs = evidenceRefs.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    const db = refs.filter((item) => ['db', 'database', 'sql', 'data'].includes(String(item.source_type ?? item.source ?? '').toLowerCase())).length
    return { db: refs.length ? db / refs.length : 0, docWeb: refs.length ? (refs.length - db) / refs.length : 0 }
  }, [evidenceRefs])
  const topCitations = resolvedCitations.slice(0, 3)
  const isUser = resolvedRole === 'user'

  const resolveApproval = async (approvalId: string, approved: boolean) => {
    if (!token || !message?.response_id || !message?.id || !activeConversationId) return
    const conversationId = activeConversationId
    const responseId = message.response_id
    const messageId = message.id
    const authSession = getAuthSessionSnapshot()
    if (authSession.token !== token) return
    const isCurrentConversation = () => (
      isAuthSessionCurrent(authSession)
      && useChatStore.getState().activeId === conversationId
    )
    const isCurrentApproval = () => (
      isCurrentConversation()
      && useChatStore.getState().activeResponseId === responseId
    )
    const isCalendarCreation = Boolean(
      approved && message.approvals?.some((approval) => approval.id === approvalId && approval.tool_name === 'create_calendar_event'),
    )
    let approvalResolved = false
    let calendarCreated = false
    setResolvingApproval(approvalId)
    setApprovalError(null)
    try {
      const resolution = await apiResolveResponseApproval(token, responseId, approvalId, approved)
      if (!isCurrentConversation()) return
      approvalResolved = true
      store.resumeAssistantMessage(conversationId, messageId)
      store.setActiveResponseId(responseId)
      const callbacks: NonNullable<Parameters<typeof apiResumeResponseWithRetry>[3]> = {
        onDelta: (text) => {
          if (isCurrentApproval()) store.appendMessageStreamingChunk(conversationId, messageId, text)
        },
        onReasoningStep: (step) => {
          if (isCurrentApproval()) store.addReasoningStep(conversationId, step)
        },
        onToolCall: (payload) => {
          if (isCurrentApproval()) store.updateToolStatus(conversationId, payload)
        },
        onToolResult: (payload) => {
          if (!isCurrentApproval()) return
          store.updateToolResult(conversationId, payload)
          if (
            isCalendarCreation
            && String(payload?.name || payload?.tool_name || '') === 'create_calendar_event'
            && ['success', 'completed'].includes(String(payload?.result?.status || payload?.status || '').toLowerCase())
          ) {
            calendarCreated = true
          }
        },
        onApprovalRequired: (approvals) => {
          if (isCurrentApproval()) store.setMessageApprovals(conversationId, messageId, approvals)
        },
        onFinalAnswer: (envelope) => {
          if (!isCurrentApproval()) return
          store.finishAssistantMessage(conversationId, messageId, envelope.content || '（空响应）')
          store.setStreaming(false)
          store.setActiveResponseId(null)
          if (calendarCreated) store.markCalendarActionCompleted(conversationId, messageId)
        },
        onError: (error) => {
          if (isCurrentApproval()) store.failAssistantMessage(conversationId, messageId, error instanceof Error ? error.message : String(error))
        },
      }
      await apiResumeResponseWithRetry(
        token,
        responseId,
        Number(resolution.starting_after),
        callbacks,
      )
    } catch (error) {
      if (approvalResolved ? !isCurrentApproval() : !isCurrentConversation()) return
      const text = error instanceof Error ? error.message : String(error)
      setApprovalError(text)
      if (approvalResolved) {
        try {
          const [responseState, messages] = await Promise.all([
            apiGetResponse(token, responseId),
            apiGetMessages(token, conversationId),
          ])
          if (!isCurrentApproval()) return
          store.setMessages(conversationId, messages)
          if (['queued', 'in_progress'].includes(String(responseState?.status || ''))) {
            const persistedMessage = [...messages].reverse().find((item) =>
              item.role === 'assistant' && item.response_id === responseId
            )
            const persistedMessageId = String(persistedMessage?.id || messageId)
            store.keepAssistantResponseRunning(conversationId, persistedMessageId)
            store.setActiveResponseId(responseId)
            setApprovalError('审批已提交，响应仍在后台执行；可稍后重新打开该会话查看结果。')
            return
          }
        } catch {
          if (!isCurrentApproval()) return
          store.failAssistantMessage(conversationId, messageId, `审批已提交，但状态同步失败：${text}`)
        }
        store.setStreaming(false)
      } else {
        store.restoreAssistantApproval(conversationId, messageId)
      }
      store.setActiveResponseId(null)
    } finally {
      if (isAuthSessionCurrent(authSession) && useChatStore.getState().activeId === conversationId) {
        setResolvingApproval(null)
      }
    }
  }

  const copyMessage = async () => {
    if (!visibleContent) return
    try {
      if (!(await copyTextToClipboard(visibleContent))) return
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1400)
    } catch {
      // Clipboard may be unavailable in a sandboxed browser.
    }
  }

  const regenerate = () => {
    if (!message?.response_id) return
    requestRegenerate({ responseId: message.response_id })
  }

  const switchVersion = async () => {
    if (!token || !activeConversationId || !message?.response_id) return
    const authSession = getAuthSessionSnapshot()
    const siblings = await apiListResponseSiblings(token, message.response_id)
    if (!isAuthSessionCurrent(authSession)) return
    if (siblings.length < 2) return
    const current = siblings.findIndex((item) => item.active)
    const next = siblings[(current + 1) % siblings.length]
    await apiSetActiveResponse(token, activeConversationId, next.id)
    const messages = await apiGetMessages(token, activeConversationId)
    if (isAuthSessionCurrent(authSession)) store.setMessages(activeConversationId, messages)
  }

  const feedback = async (value: 'like' | 'dislike') => {
    if (!token || !activeConversationId) return
    await apiSubmitFeedback(token, activeConversationId, message?.id ?? null, value)
  }

  const branch = async () => {
    if (!token || !activeConversationId || !message?.id) return
    const authSession = getAuthSessionSnapshot()
    const result = await apiBranchConversation(token, activeConversationId, message.id)
    if (!isAuthSessionCurrent(authSession)) return
    const conversationId = String(result.conversation_id || result.id || '')
    if (!conversationId) return
    store.setActiveId(conversationId)
    const [messages, conversations] = await Promise.all([
      apiGetMessages(token, conversationId),
      apiListConversations(token),
    ])
    if (!isAuthSessionCurrent(authSession)) return
    store.setMessages(conversationId, messages)
    store.setConversations(conversations)
  }

  useEffect(() => {
    if (resolvedStreaming && contentRef.current?.scrollIntoView) contentRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [resolvedContent, resolvedStreaming])

  return (
    <div
      className="group w-full py-4 sm:py-5"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className="mx-auto w-full max-w-3xl px-4 sm:px-6">
        <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'}`}>
          <div className={`min-w-0 ${isUser ? 'w-fit max-w-[min(82%,42rem)]' : 'w-full'}`}>
            <div className={`mb-1 flex items-center gap-2 text-[11px] text-[var(--text-secondary)] ${isUser ? 'justify-end pr-1' : ''}`}>
              {isUser ? <span className="sr-only">你</span> : <span className="font-medium tracking-tight">{brandName}</span>}
              {levelBadge(annotations?.[0]?.annotation?.level ?? epistemic.level)}
              {isHovered && !isUser && (onBranch || message?.id) && (
                <button onClick={() => void branch()} className="text-xs text-[var(--text-secondary)] hover:text-[var(--accent)]">分支</button>
              )}
            </div>
            {!isUser && (progress.length > 0 || resolvedSteps.length > 0) && (
              <ProgressSummary progress={progress} steps={resolvedSteps as any[]} complete={!resolvedStreaming} />
            )}
            {isUser && messageAttachments.length > 0 && <div className="mb-2 flex flex-wrap justify-end gap-2">{messageAttachments.map((attachment) => <div key={attachment.id} className="flex max-w-64 items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs"><FileText size={14} className="shrink-0" /><span className="truncate">{attachment.filename}</span></div>)}</div>}
            <div
              ref={contentRef}
              translate="no"
              className={`prose max-w-none text-[15px] leading-7 ${
                isUser
                  ? 'rounded-2xl rounded-tr-md bg-[var(--user-bubble)] px-4 py-2.5 text-[var(--text)] break-words whitespace-pre-wrap [&_.prose_p]:m-0'
                  : 'text-[var(--text)]'
              }`}
            >
              {visibleContent ? (
                <Suspense fallback={<div className="whitespace-pre-wrap">{visibleContent}</div>}>
                  <MarkdownMessage content={visibleContent} />
                </Suspense>
              ) : (resolvedStreaming && !isUser ? <span>正在生成…</span> : null)}
              {resolvedStreaming && !isUser && <span className="ml-1 inline-block h-4 w-1.5 animate-pulse bg-[var(--accent)] align-middle" />}
            </div>
            {!isUser && toolCard && <ToolCardView toolCard={toolCard} />}
            {!isUser && Boolean(message?.approvals?.length) && (
              <div className="mt-3 space-y-3">
                {message!.approvals!.map((approval) => (
                  <div key={approval.id} className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4">
                    <div className="text-sm font-medium">需要授权：{approval.tool_name}</div>
                    <div className="mt-1 text-xs text-[var(--text-secondary)]">
                      {approval.side_effect === 'destructive' ? '此操作可能删除或覆盖数据。' : '此操作会写入或修改外部状态。'}
                    </div>
                    <pre className="mt-3 max-h-40 overflow-auto rounded-xl bg-[var(--surface)] p-3 text-xs">{JSON.stringify(approval.arguments, null, 2)}</pre>
                    <div className="mt-3 flex gap-2">
                      <button disabled={Boolean(resolvingApproval)} onClick={() => void resolveApproval(approval.id, true)} className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm text-[var(--accent-foreground)] disabled:opacity-50">允许</button>
                      <button disabled={Boolean(resolvingApproval)} onClick={() => void resolveApproval(approval.id, false)} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm disabled:opacity-50">拒绝</button>
                    </div>
                    {approvalError && <p role="alert" className="mt-3 text-xs text-red-500">{approvalError}</p>}
                  </div>
                ))}
              </div>
            )}
            {!isUser && message?.calendar_action_completed && !message?.approvals?.length && (
              <a href="/calendar" className="mt-3 inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-xs text-[var(--accent)] hover:bg-[var(--surface)]">
                <CalendarDays size={14} />查看我的日历
              </a>
            )}
            {!isUser && annotations?.[0]?.annotation?.confidence !== undefined && (
              <div className="mt-2 text-xs text-[var(--text-secondary)]">
                置信度：{Math.round(annotations?.[0]?.annotation?.confidence * 100)}%
                {annotations?.[0]?.annotation?.caveats?.length ? ` · ${annotations?.[0]?.annotation?.caveats.join('；')}` : ''}
              </div>
            )}
            {!isUser && (resolvedCitations.length > 0 || evidenceRefs.length > 0) && (
              <div className="mt-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--text-secondary)]">
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  <span>DB 证据 {Math.round(sourceRatio.db * 100)}%</span>
                  <span>Doc / Web {Math.round(sourceRatio.docWeb * 100)}%</span>
                </div>
                {topCitations.map((citation, index) => <div className="mt-1" key={`${citation.title}-${index}`}>[{index + 1}] {citation.title}</div>)}
                <button onClick={() => setShowCitations(!showCitations)} className="mt-2 text-xs text-[var(--text-muted)] hover:text-[var(--text)]">
                  {showCitations ? '收起证据明细' : '展开证据明细'}
                </button>
                {showCitations && <div className="mt-2 space-y-1 border-l-2 border-[var(--border)] pl-4">
                  {resolvedCitations.map((citation, index) => <a key={`${citation.title}-${index}`} href={citation.url || '#'} target="_blank" rel="noopener noreferrer" className="block text-xs text-[var(--text-secondary)] hover:text-[var(--accent)]">[{index + 1}] {citation.title}{typeof citation.relevance === 'number' ? ` (${Math.round(citation.relevance * 100)}%)` : ''}</a>)}
                </div>}
              </div>
            )}
            {!isUser && !resolvedStreaming && <div className="mt-2 flex items-center gap-1 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100" data-testid="message-actions">
              <button type="button" aria-label="复制回答" title="复制" onClick={() => void copyMessage()} className="rounded-md p-1.5 text-[var(--text-secondary)] hover:bg-[var(--surface-raised)] hover:text-[var(--text)]">{copied ? <Check size={14} /> : <Copy size={14} />}</button>
              <button type="button" aria-label="重新生成" title="重新生成" onClick={regenerate} className="rounded-md p-1.5 text-[var(--text-secondary)] hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"><RefreshCw size={14} /></button>
              {(message?.sibling_count ?? 1) > 1 && <button type="button" aria-label="切换回答版本" title={`回答版本 ${message?.version_index ?? 1}/${message?.sibling_count}`} onClick={switchVersion} className="rounded-md px-1.5 py-1 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--surface-raised)]">{message?.version_index ?? 1}/{message?.sibling_count}</button>}
              <button type="button" aria-label="回答有帮助" title="有帮助" onClick={() => feedback('like')} className="rounded-md p-1.5 text-[var(--text-secondary)] hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"><ThumbsUp size={14} /></button>
              <button type="button" aria-label="回答没帮助" title="没帮助" onClick={() => feedback('dislike')} className="rounded-md p-1.5 text-[var(--text-secondary)] hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"><ThumbsDown size={14} /></button>
              {(onBranch || message?.id) && <button type="button" aria-label="创建分支" title="创建分支" onClick={() => void branch()} className="rounded-md p-1.5 text-[var(--text-secondary)] hover:bg-[var(--surface-raised)] hover:text-[var(--text)]"><GitBranch size={14} /></button>}
            </div>}
          </div>
        </div>
      </div>
    </div>
  )
}

function ProgressSummary({ progress, steps, complete }: { progress: string[]; steps: any[]; complete: boolean }) {
  const latest = progress[progress.length - 1] || steps[steps.length - 1]?.title || '处理中'
  return (
    <details className="mb-2 max-w-xl rounded-xl border border-[var(--border-subtle)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--text-secondary)]" open={!complete}>
      <summary className="flex cursor-pointer list-none items-center gap-2 select-none [&::-webkit-details-marker]:hidden">
        <span className={complete ? 'text-[var(--accent)]' : 'animate-pulse text-[var(--accent)]'}>{complete ? '✓' : '●'}</span>
        <span className="truncate">{complete ? '已完成' : latest}</span>
        <ChevronDown size={13} className="ml-auto opacity-60" />
      </summary>
      <div className="mt-2 space-y-1 border-l border-[var(--border)] pl-3">
        {progress.slice(-8).map((item, index) => <div key={`${item}-${index}`}>{item}</div>)}
        {steps.slice(-8).map((step, index) => <div key={`${step.id ?? step.title}-${index}`}>{step.title}{step.status === 'completed' ? ' ✓' : ''}</div>)}
      </div>
    </details>
  )
}
