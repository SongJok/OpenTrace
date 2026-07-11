import { useRef, useState, KeyboardEvent, useEffect, useCallback, type ReactNode } from 'react'
import { Square, Paperclip, Globe, Brain, Settings2, Link2, Send, X, FileText, Database, BarChart3, FileWarning, Package, Loader2, AlertCircle } from 'lucide-react'
import { useChatStore, type MessageAttachment } from '../store/chat'
import { useAuthStore } from '../store/auth'
import {
  apiChatStream,
  apiChatSync,
  apiCreateConversation,
  apiGraphControl,
  apiGetSessionSkills,
  apiSetSessionSkills,
  apiStopChatStream,
  apiCreateMemory,
  apiListDatabases,
  apiUploadAttachment,
  apiPromoteAttachment,
  type ReasoningStep,
  type AttachmentItem,
  type AttachmentUploadResponse,
} from '../api/client'
import clsx from 'clsx'
import { isDatabaseQuestion } from '../lib/chatDatabase'
import { normalizeFinalAnswerEnvelope, type TurnMetaEnvelope } from '../utils/streamEnvelope'

function applyFinalAnswerEnvelope(
  store: ReturnType<typeof useChatStore.getState>,
  sessionId: string,
  assistantMessageId: string,
  envelope: TurnMetaEnvelope,
) {
  if (envelope.execution_graph) {
    store.setExecutionGraph(sessionId, assistantMessageId, envelope.execution_graph as any)
  }
  const display = normalizeAnswerContent(envelope.content) || '（空响应）'
  store.finishLastAssistantMessage(sessionId, display)
  if (envelope.citations?.length) {
    store.setLastAssistantCitations(sessionId, envelope.citations as any)
  }
  if (envelope.annotations?.length) {
    store.setLastAssistantAnnotations(sessionId, envelope.annotations as any)
  }
  store.setLastAssistantTurnMeta(sessionId, envelope)
}

type PrefillDetail = string | { text: string; autoSend?: boolean }
type ChatInputVariant = 'default' | 'welcome'

function normalizeAnswerContent(content: unknown): string {
  if (typeof content === 'string') return content
  if (content == null) return ''
  if (typeof content === 'object' && !Array.isArray(content)) {
    const obj = content as Record<string, unknown>
    // If the object looks like a card (has type/agent_type/tool_name),
    // serialize it as JSON so tryParseToolCard can parse it later
    const isCard = (
      obj.type === 'turn' || obj.type === 'agent_result' ||
      obj.type === 'time' || obj.type === 'weather' || obj.type === 'table' ||
      typeof obj.agent_type === 'string' ||
      typeof obj.tool_name === 'string'
    )
    if (isCard) {
      try {
        const innerText = (
          (typeof obj.content === 'string' ? obj.content : '') ||
          (typeof obj.text === 'string' ? obj.text : '') ||
          (typeof obj.answer === 'string' ? obj.answer : '') ||
          (typeof obj.summary === 'string' ? obj.summary : '') ||
          ''
        )
        const cardJson = JSON.stringify(obj)
        return innerText ? `${cardJson}\n\n${innerText}` : cardJson
      } catch { /* fall through */ }
    }
    if (typeof obj.content === 'string') return obj.content
    if (typeof obj.text === 'string') return obj.text
    if (typeof obj.answer === 'string') return obj.answer
    if (typeof obj.summary === 'string') return obj.summary
    if (typeof obj.output === 'string') return obj.output
    if (typeof obj.message === 'string') return obj.message
  }
  return ''
}

export type ForceMode = 'rag' | 'data_query' | 'data_analysis' | 'anomaly_tracking' | 'product' | 'vision' | null

// Slash command prefixes → force_mode mapping
const FORCE_MODE_PREFIXES: Record<string, ForceMode> = {
  '/rag': 'rag',
  '/data_query': 'data_query',
  '/data_analysis': 'data_analysis',
  '/skills': 'anomaly_tracking',
  '/product': 'product',
  '/vision': 'vision',
}

/**
 * Parse a slash command prefix from the query text.
 * Returns [cleanQuery, forceMode] — e.g. "/rag 什么是队长？" → ["什么是队长？", "rag"]
 */
function parseSlashPrefix(query: string): [string, ForceMode] {
  const trimmed = query.trim()
  for (const [prefix, mode] of Object.entries(FORCE_MODE_PREFIXES)) {
    if (trimmed.startsWith(prefix + ' ')) {
      return [trimmed.slice(prefix.length).trim(), mode]
    }
    if (trimmed === prefix) {
      // Slash command alone — return empty query with mode set
      return ['', mode]
    }
  }
  return [trimmed, null]
}

/** Slash command definitions for the suggestion dropdown */
const SLASH_COMMANDS: Array<{ prefix: string; mode: ForceMode; label: string; description: string }> = [
  { prefix: '/rag', mode: 'rag', label: 'RAG', description: '知识库检索' },
  { prefix: '/data_query', mode: 'data_query', label: '数据查询', description: '查询数据库' },
  { prefix: '/data_analysis', mode: 'data_analysis', label: '数据分析', description: '数据分析' },
  { prefix: '/skills', mode: 'anomaly_tracking', label: '异常追踪', description: '技能调用' },
  { prefix: '/product', mode: 'product', label: '产品查询', description: '规则引擎查询' },
  { prefix: '/vision', mode: 'vision', label: '视觉识别', description: '图片分析与识别' },
]

interface SlashSuggestion {
  visible: boolean
  query: string
  selectedIndex: number
}

export default function ChatInput({ variant = 'default' }: { variant?: ChatInputVariant }) {
  const [text, setText] = useState('')
  const [webEnabled, setWebEnabled] = useState(false)
  const [selectedDataSourceId, setSelectedDataSourceId] = useState<string>('')
  const [graphControls, setGraphControls] = useState<{ pruned_nodes: string[]; expanded_nodes: string[] }>({
    pruned_nodes: [],
    expanded_nodes: [],
  })
  const [enabledSkills, setEnabledSkills] = useState<string[]>([])
  const [disabledSkills, setDisabledSkills] = useState<string[]>([])
  const [selectedDataSourceName, setSelectedDataSourceName] = useState<string>('')
  const [dataSourceOptions, setDataSourceOptions] = useState<Array<{ id: string; name: string }>>([])
  const [toolPermissionToken, setToolPermissionToken] = useState<string | null>(null)
  const [suggestion, setSuggestion] = useState<SlashSuggestion>({ visible: false, query: '', selectedIndex: 0 })
  const [attachments, setAttachments] = useState<AttachmentItem[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const token = useAuthStore((s) => s.token)!
  const streaming = useChatStore((s) => s.streaming)
  const activeId = useChatStore((s) => s.activeId)
  const store = useChatStore()
  const isWelcome = variant === 'welcome'
  const maxTextareaHeight = isWelcome ? 240 : 200
  const minTextareaHeight = isWelcome ? 136 : 0

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.max(Math.min(el.scrollHeight, maxTextareaHeight), minTextareaHeight) + 'px'
  }, [maxTextareaHeight, minTextareaHeight, text])

  /** Detect '/' typing and update suggestion dropdown */
  const updateSlashSuggestion = useCallback((currentText: string) => {
    const el = textareaRef.current
    if (!el) return
    const pos = el.selectionStart
    const before = currentText.substring(0, pos)

    // Find a '/' that's not preceded by non-whitespace (i.e. start of word)
    const slashMatch = before.match(/(?:^|\s)\/(\S*)$/)
    if (!slashMatch) {
      if (suggestion.visible) setSuggestion({ visible: false, query: '', selectedIndex: 0 })
      return
    }

    const typed = slashMatch[1].toLowerCase()
    const matches = SLASH_COMMANDS.filter(
      (c) => c.prefix.slice(1).startsWith(typed)
    )
    if (matches.length === 0) {
      if (suggestion.visible) setSuggestion({ visible: false, query: '', selectedIndex: 0 })
      return
    }

    setSuggestion({ visible: true, query: typed, selectedIndex: 0 })
  }, [suggestion.visible])

  useEffect(() => {
    const loadSelectedDataSource = async () => {
      try {
        const raw = localStorage.getItem('opentrace:selected_data_source')
        const list = await apiListDatabases(token)
        setDataSourceOptions(list.map((x) => ({ id: x.id, name: x.name })))

        // Resolve selected data source: prefer saved one if it still belongs to this user
        let resolvedId = ''
        let resolvedName = ''
        if (raw) {
          try {
            const parsed = JSON.parse(raw)
            if (parsed?.id && list.some((db) => db.id === parsed.id)) {
              resolvedId = parsed.id
              resolvedName = parsed.name || ''
            }
          } catch { /* malformed JSON, ignore */ }
        }

        if (!resolvedId && list.length > 0) {
          const first = list[0]
          resolvedId = first.id
          resolvedName = first.name
        }

        setSelectedDataSourceId(resolvedId)
        setSelectedDataSourceName(resolvedName)
        if (resolvedId) {
          localStorage.setItem('opentrace:selected_data_source', JSON.stringify({ id: resolvedId, name: resolvedName }))
        } else {
          localStorage.removeItem('opentrace:selected_data_source')
        }
      } catch {
        // ignore
      }
    }
    void loadSelectedDataSource()
  }, [token])

  /** Select a slash command from the suggestion dropdown */
  function selectSlashCommand(cmd: { prefix: string; mode: ForceMode }) {
    const el = textareaRef.current
    if (!el) return
    const pos = el.selectionStart
    const before = text.substring(0, pos)
    const after = text.substring(pos)

    // Replace the partial slash with the full command prefix + space
    const slashIdx = before.lastIndexOf('/')
    const newText = text.substring(0, slashIdx) + cmd.prefix + ' ' + after
    setText(newText)
    setSuggestion({ visible: false, query: '', selectedIndex: 0 })

    // Move cursor after the prefix + space
    const newPos = slashIdx + cmd.prefix.length + 1
    el.focus()
    setTimeout(() => {
      el.setSelectionRange(newPos, newPos)
    }, 0)
  }

  /** Handle file selection from hidden input */
  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (!files || files.length === 0) return
    const newAttachments: AttachmentItem[] = Array.from(files).map((file) => ({
      id: `att_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      file,
      name: file.name,
      size: file.size,
      status: 'pending' as const,
    }))
    setAttachments((prev) => [...prev, ...newAttachments])
    // Reset input so re-selecting the same file works
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  /** Remove an attachment from the list */
  function removeAttachment(id: string) {
    setAttachments((prev) => prev.filter((a) => a.id !== id))
  }

  /** Upload all pending attachments and return their server IDs */
  async function uploadAttachments(sessionId: string): Promise<string[]> {
    const pending = attachments.filter((a) => a.status === 'pending')
    if (pending.length === 0) {
      return attachments
        .filter((a) => a.status === 'done' && a.serverId)
        .map((a) => a.serverId!)
    }

    const serverIds: string[] = []

    for (const att of attachments) {
      if (att.status === 'done' && att.serverId) {
        serverIds.push(att.serverId)
        continue
      }
      if (att.status === 'error') continue

      // Mark as uploading
      setAttachments((prev) =>
        prev.map((a) => (a.id === att.id ? { ...a, status: 'uploading' as const } : a))
      )

      try {
        const resp: AttachmentUploadResponse = await apiUploadAttachment(token, att.file, sessionId)
        setAttachments((prev) =>
          prev.map((a) =>
            a.id === att.id
              ? { ...a, status: 'done' as const, serverId: resp.attachment_id, contentHash: resp.content_hash, contentSummary: resp.content_summary, isDuplicate: resp.is_duplicate }
              : a
          )
        )
        serverIds.push(resp.attachment_id)
      } catch (err: any) {
        setAttachments((prev) =>
          prev.map((a) =>
            a.id === att.id
              ? { ...a, status: 'error' as const, error: err?.message || 'Upload failed' }
              : a
          )
        )
      }
    }

    return serverIds
  }

  async function promoteAttachment(att: AttachmentItem) {
    if (!att.serverId || att.status !== 'done') return
    try {
      await apiPromoteAttachment(token, att.serverId, 'review')
      setAttachments((prev) => prev.map((item) => item.id === att.id ? { ...item, ingestStatus: 'queued' } : item))
    } catch (err: any) {
      setAttachments((prev) => prev.map((item) => item.id === att.id ? { ...item, error: err?.message || 'Promote failed' } : item))
    }
  }

  async function send(overrideText?: string) {
    const rawQuery = (overrideText ?? text).trim()
    if (!rawQuery || streaming) return

    // Parse slash command prefix
    const [query, parsedMode] = parseSlashPrefix(rawQuery)
    // If slash command was the only content, treat the raw query as-is (no mode activation)
    if (!query) return
    const effectiveMode = parsedMode

    const needDataSource = isDatabaseQuestion(query) || effectiveMode === 'data_query' || effectiveMode === 'data_analysis'
    const dataSourceContext = selectedDataSourceId
      ? {
          data_source_id: selectedDataSourceId,
          data_source_name: selectedDataSourceName || undefined,
        }
      : undefined
    if (needDataSource && !selectedDataSourceId) {
      alert('当前问题涉及数据库/分析，请先在输入框下拉中选择数据库。')
      return
    }

    let currentSessionId = activeId ?? ''

    try {
      // Ensure session exists before uploading attachments
      if (!currentSessionId) {
        const conv = await apiCreateConversation(token)
        store.addConversation(conv)
        store.setActiveId(conv.id)
        store.setMessages(conv.id, [])
        currentSessionId = conv.id
      }

      // Upload attachments before sending (needs session_id)
      const attachmentIds = await uploadAttachments(currentSessionId)

      // Build attachment metadata to display on the user message
      const msgAttachments: MessageAttachment[] = attachments
        .filter(a => a.status === 'done' && a.serverId)
        .map(a => {
          const dot = a.name.lastIndexOf('.')
          const ext = dot >= 0 ? a.name.slice(dot + 1) : undefined
          return {
            id: a.serverId || a.id,
            filename: a.name,
            file_size: a.size,
            file_extension: ext,
            content_summary: a.contentSummary,
          }
        })

      const controller = new AbortController()
      abortRef.current = controller

      store.appendUserMessage(currentSessionId, {
        id: `u_${Date.now()}`,
        content: query,
        attachments: msgAttachments.length > 0 ? msgAttachments : undefined,
      })
      setText('')
      setAttachments([])
      if (textareaRef.current) textareaRef.current.style.height = 'auto'
      const assistantMessageId = `a_${Date.now()}`
      store.appendAssistantStreamingMessage(currentSessionId, { id: assistantMessageId })
      store.setStreaming(true)
      store.resetReasoning(currentSessionId, assistantMessageId)

      store.updateTitle(currentSessionId, query.slice(0, 40) + (query.length > 40 ? '…' : ''))

      await apiChatStream(
        token,
        currentSessionId,
        query,
        {
          onReasoningStep: (step: ReasoningStep) => {
            store.addReasoningStep(currentSessionId, step)
          },
          onThinking: (payload) => {
            if (payload.content) store.appendThinking(currentSessionId, payload.content)
          },
          onDelta: (text) => {
            if (text) store.appendStreamingChunk(currentSessionId, text)
          },
          onToolCall: (payload) => {
            store.updateToolStatus(currentSessionId, payload)
            if (String(payload.tool_name || '').startsWith('dag:')) {
              store.updateDagNodeEvent(currentSessionId, {
                node_id: String(payload.node_id || ''),
                agent_type: String(payload.tool_name || '').replace(/^dag:/, ''),
                status: String(payload.status || 'running'),
                preview: String(payload.preview || ''),
              })
            }
          },
          onToolResult: (payload) => {
            store.updateToolResult(currentSessionId, payload)
            if (String(payload.tool_name || '').startsWith('dag:')) {
              store.updateDagNodeEvent(currentSessionId, {
                node_id: String(payload.node_id || ''),
                agent_type: String(payload.tool_name || '').replace(/^dag:/, ''),
                status: 'success',
                preview: String(payload.preview || ''),
              })
            }
          },
          onFinalAnswer: async (envelope) => {
            applyFinalAnswerEnvelope(store, currentSessionId, assistantMessageId, envelope)
            window.dispatchEvent(new Event(`opentrace:assistant-stream-done:${assistantMessageId}`))
          },
          onError: async (err) => {
            if (err instanceof Error && err.message === 'REQUEST_ABORTED') {
              store.stopLastAssistantMessage(currentSessionId)
              return
            }
            const errMsg = err instanceof Error ? err.message : String(err)
            try {
              const parsed = JSON.parse(errMsg)
              if (parsed?.requires_confirmation && parsed?.tool_permission_token) {
                const ok = window.confirm(`检测到高风险操作（${parsed.risk_level}）。是否授权继续？`)
                if (ok) {
                  setToolPermissionToken(parsed.tool_permission_token)
                  await send(query)
                  return
                }
              }
            } catch {
              // not json error
            }
            try {
              const sync: any = await apiChatSync(token, currentSessionId, query, {
                ...dataSourceContext,
                force_database: needDataSource,
                force_mode: effectiveMode,
                enabled_skills: enabledSkills,
                disabled_skills: disabledSkills,
                tool_permission_token: toolPermissionToken,
                confirmation_granted: Boolean(toolPermissionToken),
                attachment_ids: attachmentIds.length > 0 ? attachmentIds : undefined,
                knowledge: {
                  action: 'auto', scope: 'session', attachment_ids: attachmentIds, publish_policy: 'review',
                },
              })
              applyFinalAnswerEnvelope(
                store,
                currentSessionId,
                assistantMessageId,
                normalizeFinalAnswerEnvelope({
                  content: sync.content,
                  execution_graph: sync.execution_graph,
                  citations: sync.citations,
                  annotations: sync.annotations,
                  metadata: sync.metadata ?? {},
                  prompt_tokens: sync.prompt_tokens,
                  completion_tokens: sync.completion_tokens,
                }),
              )
            } catch {
              store.failLastAssistantMessage(currentSessionId, `Error: ${errMsg}`)
            }
          },
        },
        webEnabled,
        controller.signal,
        'chat',
        {
          enabled_skills: enabledSkills,
          disabled_skills: disabledSkills,
          tool_permission_token: toolPermissionToken,
          confirmation_granted: Boolean(toolPermissionToken),
          ...dataSourceContext,
          force_database: needDataSource,
          force_mode: effectiveMode,
          attachment_ids: attachmentIds.length > 0 ? attachmentIds : undefined,
          knowledge: {
            action: 'auto', scope: 'session', attachment_ids: attachmentIds, publish_policy: 'review',
          },
        },
        graphControls
      )
    } catch (e: any) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        if (currentSessionId) {
          store.stopLastAssistantMessage(currentSessionId)
        }
        store.setStreaming(false)
        return
      }
      const msg = e?.message || '发送失败'
      alert(msg)
      store.setStreaming(false)
    } finally {
      abortRef.current = null
    }
  }

  async function stop() {
    if (activeId) {
      try {
        await apiStopChatStream(token, activeId)
      } catch {
        // ignore and fallback to abort local stream
      }
    }
    abortRef.current?.abort()
    abortRef.current = null
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (suggestion.visible) {
      const matches = SLASH_COMMANDS.filter((c) => c.prefix.slice(1).startsWith(suggestion.query))
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSuggestion((s) => ({ ...s, selectedIndex: (s.selectedIndex + 1) % matches.length }))
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSuggestion((s) => ({ ...s, selectedIndex: (s.selectedIndex - 1 + matches.length) % matches.length }))
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        selectSlashCommand(matches[suggestion.selectedIndex])
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setSuggestion({ visible: false, query: '', selectedIndex: 0 })
        return
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  useEffect(() => {
    const stopHandler = () => {
      abortRef.current?.abort()
      abortRef.current = null
    }
    window.addEventListener('opentrace:stop-stream', stopHandler)
    return () => window.removeEventListener('opentrace:stop-stream', stopHandler)
  }, [])

  useEffect(() => {
    const handler = async (e: Event) => {
      const detail = (e as CustomEvent<{ action: 'prune' | 'expand'; nodeId: string }>).detail
      if (!detail?.nodeId) return
      setGraphControls((prev) => {
        if (detail.action === 'prune') {
          if (prev.pruned_nodes.includes(detail.nodeId)) return prev
          return { ...prev, pruned_nodes: [...prev.pruned_nodes, detail.nodeId] }
        }
        if (prev.expanded_nodes.includes(detail.nodeId)) return prev
        return { ...prev, expanded_nodes: [...prev.expanded_nodes, detail.nodeId] }
      })
      if (activeId) {
        try {
          await apiGraphControl(token, activeId, detail.action, detail.nodeId)
        } catch {
          // ignore live control error; local controls still applied for next request
        }
      }
    }
    window.addEventListener('opentrace:graph-control', handler)
    return () => window.removeEventListener('opentrace:graph-control', handler)
  }, [activeId, token])

  useEffect(() => {
    const loadSkills = async () => {
      if (!activeId) return
      try {
        const cfg = await apiGetSessionSkills(token, activeId)
        setEnabledSkills(cfg.enabled_skills || [])
        setDisabledSkills(cfg.disabled_skills || [])
      } catch {
        // ignore
      }
    }
    void loadSkills()
  }, [activeId, token])

  useEffect(() => {
    const persistSkills = async () => {
      if (!activeId) return
      try {
        await apiSetSessionSkills(token, activeId, enabledSkills, disabledSkills)
      } catch {
        // ignore
      }
    }
    void persistSkills()
  }, [activeId, token, enabledSkills, disabledSkills])

  // Close suggestion dropdown when clicking outside
  useEffect(() => {
    if (!suggestion.visible) return
    const handler = () => setSuggestion((s) => ({ ...s, visible: false, selectedIndex: 0 }))
    window.addEventListener('click', handler)
    return () => window.removeEventListener('click', handler)
  }, [suggestion.visible])

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<PrefillDetail>).detail
      const payload = typeof detail === 'string' ? { text: detail, autoSend: false } : detail
      setText(payload.text)
      textareaRef.current?.focus()
      if (payload.autoSend) {
        window.setTimeout(() => {
          void send(payload.text)
        }, 0)
      }
    }
    window.addEventListener('opentrace:prefill', handler)
    return () => window.removeEventListener('opentrace:prefill', handler)
  }, [streaming, activeId, token, webEnabled])

  useEffect(() => {
    const regenHandler = (e: Event) => {
      const detail = (e as CustomEvent<{ mode: 'regenerate' | 'edit-regenerate'; messageId?: string; newContent?: string }>).detail
      if (!activeId || streaming) return
      const controller = new AbortController()
      abortRef.current = controller
      const assistantMessageId = `a_${Date.now()}`
      store.appendAssistantStreamingMessage(activeId, { id: assistantMessageId })
      store.setStreaming(true)
      store.resetReasoning(activeId, assistantMessageId)
      void apiChatStream(
        token,
        activeId,
        '',
        {
          onReasoningStep: (step: ReasoningStep) => store.addReasoningStep(activeId, step),
          onThinking: (payload) => payload.content && store.appendThinking(activeId, payload.content),
          onDelta: (text) => text && store.appendStreamingChunk(activeId, text),
          onToolCall: (payload) => store.updateToolStatus(activeId, payload),
          onToolResult: (payload) => store.updateToolResult(activeId, payload),
          onFinalAnswer: async (envelope) => {
            applyFinalAnswerEnvelope(store, activeId, assistantMessageId, envelope)
          },
          onError: (err) => {
            if (err instanceof Error && err.message === 'REQUEST_ABORTED') {
              store.stopLastAssistantMessage(activeId)
              return
            }
            store.failLastAssistantMessage(activeId, `Error: ${err instanceof Error ? err.message : String(err)}`)
          },
        },
        webEnabled,
        controller.signal,
        detail.mode,
        detail.mode === 'edit-regenerate'
          ? { message_id: detail.messageId, new_content: detail.newContent }
          : undefined
      )
    }
    window.addEventListener('opentrace:regen', regenHandler)
    return () => window.removeEventListener('opentrace:regen', regenHandler)
  }, [activeId, streaming, token, webEnabled])

  const canSend = text.trim().length > 0 && !streaming

  return (
    <div className={isWelcome ? 'w-full pt-4' : 'pb-4 pt-2'}>
      <div className={isWelcome ? 'mx-auto w-full max-w-[820px] px-4 sm:px-6' : 'mx-auto w-full max-w-4xl px-6'}>
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleFileSelect}
          accept=".txt,.md,.markdown,.csv,.tsv,.pdf,.json,.jsonl,.docx,.xlsx,.xls,.py,.js,.ts,.tsx,.jsx,.go,.rs,.java,.c,.cpp,.h,.hpp,.sql,.sh,.bash,.yaml,.yml,.toml,.ini,.cfg,.conf,.html,.css,.scss,.less,.vue,.svelte,.png,.jpg,.jpeg,.gif,.webp,.bmp,.svg"
        />

        {/* Attachment preview chips */}
        {attachments.length > 0 && (
          <div className={clsx('flex flex-wrap gap-2 mb-2', isWelcome ? 'px-0' : 'px-0')}>
            {attachments.map((att) => (
              <div
                key={att.id}
                className={clsx(
                  'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs transition-colors',
                  att.status === 'error'
                    ? 'border-red-300 bg-red-50 text-red-600'
                    : att.status === 'uploading'
                    ? 'border-blue-200 bg-blue-50 text-blue-600'
                    : 'border-[var(--border)] bg-[var(--surface-raised)] text-[var(--text-secondary)]'
                )}
              >
                {att.status === 'uploading' ? (
                  <Loader2 size={12} className="animate-spin flex-shrink-0" />
                ) : att.status === 'error' ? (
                  <AlertCircle size={12} className="flex-shrink-0" />
                ) : (
                  <FileText size={12} className="flex-shrink-0" />
                )}
                <span className="max-w-[140px] truncate">{att.name}</span>
                {att.status === 'done' && att.serverId && (
                  <button
                    onClick={() => void promoteAttachment(att)}
                    className="ml-1 rounded px-1 text-[10px] text-[var(--accent)] hover:bg-[var(--accent)]/10"
                    title="加入工作区知识库"
                  >入库</button>
                )}
                {att.isDuplicate && (
                  <span className="text-amber-500 flex-shrink-0" title="此文件内容与已上传的文件相同">
                    <AlertCircle size={10} />
                  </span>
                )}
                <button
                  onClick={() => removeAttachment(att.id)}
                  className="ml-0.5 flex-shrink-0 rounded-full p-0.5 hover:bg-black/10 transition-colors"
                  title="移除附件"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        )}

        <div
          className={clsx(
            'relative border shadow transition-colors',
            isWelcome
              ? 'rounded-[30px] border-[var(--hero-shell-border)] bg-[var(--hero-shell)] shadow-[0_22px_52px_rgba(15,23,42,0.08)] backdrop-blur-xl focus-within:border-[color-mix(in_srgb,var(--accent)_22%,transparent)]'
              : 'rounded-3xl border-[var(--border)] bg-[var(--surface)] focus-within:border-[var(--accent)]'
          )}
        >
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => { setText(e.target.value); updateSlashSuggestion(e.target.value) }}
            onKeyDown={onKeyDown}
            placeholder="和我聊聊天吧"
            rows={1}
            className={clsx(
              'w-full bg-transparent text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none leading-relaxed resize-none',
              isWelcome
                ? 'min-h-[136px] px-6 pt-5 pb-16 text-base sm:px-7 sm:pt-6 sm:pb-[72px]'
                : 'px-6 pt-5 pb-16 text-[15px]'
            )}
          />
          {suggestion.visible && (
            <SlashDropdown
              matches={SLASH_COMMANDS.filter((c) => c.prefix.slice(1).startsWith(suggestion.query))}
              selectedIndex={suggestion.selectedIndex}
              onSelect={selectSlashCommand}
            />
          )}
          <div
            className={clsx(
              'absolute left-4 right-4 flex items-center justify-between',
              isWelcome ? 'bottom-3.5 sm:left-5 sm:right-5' : 'bottom-3'
            )}
          >
            <div className={clsx('flex items-center', isWelcome ? 'gap-1.5' : 'gap-0.5')}>
              <IconOnlyButton
                icon={<Paperclip size={16} />}
                label="Attach"
                variant={variant}
                onClick={() => fileInputRef.current?.click()}
              />
              <IconOnlyButton icon={<Settings2 size={16} />} label="Settings" variant={variant} />
              <button
                className={clsx(
                  'flex items-center gap-1 text-xs font-medium transition-colors',
                  isWelcome
                    ? 'rounded-xl border border-blue-200/60 bg-blue-50 px-3 py-1.5 text-blue-600'
                    : 'rounded-lg bg-blue-500/15 px-2 py-1 text-blue-400'
                )}
                title="思考"
              >
                <Brain size={13} />
                <span>思考</span>
              </button>
              <button
                onClick={() => setWebEnabled((v) => !v)}
                className={clsx(
                  'flex items-center gap-1 text-xs transition-colors',
                  webEnabled
                    ? isWelcome
                      ? 'rounded-xl border border-blue-200/60 bg-blue-50 px-3 py-1.5 text-blue-600'
                      : 'rounded-lg bg-blue-500/15 px-2 py-1 text-blue-400'
                    : isWelcome
                      ? 'rounded-xl border border-[var(--hero-pill-border)] bg-[var(--hero-pill)] px-3 py-1.5 text-[var(--text-secondary)] hover:text-[var(--text)]'
                      : 'rounded-lg px-2 py-1 text-[var(--text-secondary)] hover:bg-[var(--surface-raised)]'
                )}
                title="Web Search"
              >
                <Globe size={13} />
                <span>联网</span>
              </button>
            </div>
            <div className={clsx('flex items-center', isWelcome ? 'gap-2.5' : 'gap-2')}>
              <button
                className={clsx(
                  'flex items-center gap-1.5 rounded-full border text-xs transition-colors',
                  isWelcome
                    ? 'border-[var(--hero-pill-border)] bg-[var(--hero-pill)] px-3.5 py-1.5 text-[var(--text)] shadow-[0_2px_10px_rgba(15,23,42,0.04)]'
                    : 'border-[var(--border)] px-3 py-1 text-[var(--text-secondary)] hover:text-[var(--text)]'
                )}
                title="Agent"
              >
                <Link2 size={12} />
                <span>Agent</span>
              </button>
              <button
                onClick={streaming ? stop : () => void send()}
                className={clsx(
                  'flex items-center justify-center rounded-full transition-all',
                  isWelcome ? 'h-9 w-9' : 'h-8 w-8',
                  canSend
                    ? 'bg-[var(--text)] text-[var(--bg)] hover:opacity-85'
                    : streaming
                    ? 'bg-[var(--text)] text-[var(--bg)] hover:opacity-85'
                    : isWelcome
                      ? 'cursor-not-allowed bg-[rgba(15,23,42,0.08)] text-[var(--text-muted)]'
                      : 'bg-[var(--surface-raised)] text-[var(--text-muted)] cursor-not-allowed'
                )}
              >
                {streaming ? <Square size={14} fill="currentColor" /> : <Send size={15} />}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function IconOnlyButton({
  icon,
  label,
  variant,
  onClick,
}: {
  icon: ReactNode
  label: string
  variant: ChatInputVariant
  onClick?: () => void
}) {
  const isWelcome = variant === 'welcome'
  return (
    <button
      onClick={onClick}
      className={clsx(
        'flex items-center justify-center text-[var(--text-secondary)] transition-colors',
        isWelcome
          ? 'h-9 w-9 rounded-xl border border-[var(--hero-pill-border)] bg-[var(--hero-pill)] shadow-[0_2px_10px_rgba(15,23,42,0.04)] hover:text-[var(--text)]'
          : 'h-8 w-8 rounded-lg hover:bg-[var(--surface-raised)] hover:text-[var(--text)]'
      )}
      title={label}
    >
      {icon}
    </button>
  )
}

const SLASH_ICON_MAP: Record<string, typeof FileText> = {
  '/rag': FileText,
  '/data_query': Database,
  '/data_analysis': BarChart3,
  '/skills': FileWarning,
  '/product': Package,
}

function SlashDropdown({
  matches,
  selectedIndex,
  onSelect,
}: {
  matches: Array<{ prefix: string; mode: ForceMode; label: string; description: string }>
  selectedIndex: number
  onSelect: (cmd: { prefix: string; mode: ForceMode }) => void
}) {
  const iconMap = SLASH_ICON_MAP

  return (
    <div className="absolute left-6 bottom-full z-50 mb-2 w-60 rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-lg overflow-hidden">
      {matches.map((cmd, i) => {
        const Icon = iconMap[cmd.prefix] ?? FileText
        const selected = i === selectedIndex
        return (
          <button
            key={cmd.prefix}
            onMouseDown={(e) => { e.preventDefault(); onSelect(cmd) }}
            className={clsx(
              'flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm transition-colors first:rounded-t-xl last:rounded-b-xl',
              selected
                ? 'bg-[var(--accent)]/15 text-[var(--text)]'
                : 'text-[var(--text-secondary)] hover:bg-[var(--surface-raised)] hover:text-[var(--text)]'
            )}
          >
            <Icon size={15} strokeWidth={1.9} className="flex-shrink-0" />
            <div className="flex flex-1 flex-col">
              <span className="font-medium">{cmd.prefix} {cmd.label}</span>
              <span className="text-xs text-[var(--text-muted)]">{cmd.description}</span>
            </div>
            {selected && <span className="text-xs text-[var(--text-muted)]">Enter</span>}
          </button>
        )
      })}
    </div>
  )
}
