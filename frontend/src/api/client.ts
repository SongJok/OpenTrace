// API client — all backend calls go through here
import { normalizeFinalAnswerEnvelope, type TurnMetaEnvelope } from '../utils/streamEnvelope'

const BASE = '/api/v1'
const RESPONSES_BASE = '/api/v2'

export type { TurnMetaEnvelope }
const ENV_API = (import.meta as any)?.env?.VITE_API_URL as string | undefined
const RESPONSES_API_V2_ENABLED = String((import.meta as any)?.env?.VITE_RESPONSES_API_V2_ENABLED ?? '').toLowerCase() === 'true'
const BACKEND_DIRECT = `${(ENV_API && ENV_API.trim()) ? ENV_API.trim() : 'http://localhost:14100'}/api/v1`
const RESPONSES_BACKEND_DIRECT = `${(ENV_API && ENV_API.trim()) ? ENV_API.trim() : 'http://localhost:14100'}/api/v2`

if (typeof window !== 'undefined') {
  const configured = (ENV_API && ENV_API.trim()) ? ENV_API.trim() : '(unset)'
  console.info('[OpenTrace] API config:', {
    VITE_API_URL: configured,
    base: BASE,
    backendDirect: BACKEND_DIRECT,
    fallbackUsed: configured === '(unset)',
  })
  if (configured === '(unset)') {
    console.warn('[OpenTrace] VITE_API_URL 未设置，当前使用默认 http://localhost:14100')
  }
}

export type ReasoningStage = 'ROUTE' | 'REASON' | 'DECIDE' | 'EXECUTE' | 'OBSERVE' | 'REFLECT' | 'PLAN' | 'ACT' | 'DRAFT' | 'CRITIC' | 'REWRITE' | 'FINAL' | 'FUSION' | 'EVIDENCE' | 'STEP'
export type ReasoningStatus = 'pending' | 'running' | 'done'
export type ToolRunStatus = 'idle' | 'running' | 'success' | 'error'

export interface ReasoningStep {
  id: string
  stage: ReasoningStage
  content: string
  status: ReasoningStatus
  node_id?: string
  tool?: {
    name: string
    status: ToolRunStatus
    preview?: string
  }
}

export interface ConversationItem {
  id: string
  title: string
  turn_count: number
  created_at: string
  last_active: string
  archived_at?: string | null
}

export interface MessageItem {
  id: string
  conversation_id: string
  role: string
  content: string
  created_at?: string
}

export interface MemorySettings {
  memory_learning_enabled: boolean
  preference_learning_enabled: boolean
}

type ApiErr = { code?: number; message?: string; detail?: string }

async function readApiError(res: Response, fallback: string): Promise<string> {
  const err = (await res.json().catch(() => ({}))) as ApiErr
  return err.message || err.detail || fallback
}

function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
}

async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  try {
    const res = await fetch(`${BASE}${path}`, init)
    return res
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    return fetch(`${BACKEND_DIRECT}${path}`, init)
  }
}

async function apiFetchResponses(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${RESPONSES_BASE}${path}`, init)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    return fetch(`${RESPONSES_BACKEND_DIRECT}${path}`, init)
  }
}

function responseToLegacyChat(payload: any): any {
  const output = Array.isArray(payload?.output) ? payload.output : []
  const message = output.find((item: any) => item?.type === 'message' && item?.role === 'assistant')
  const metadata = payload?.metadata ?? message?.payload ?? {}
  return {
    content: message?.content ?? '',
    metadata,
    citations: metadata.citations ?? [],
    evidence_refs: metadata.evidence_refs ?? [],
    trace_id: metadata.trace_id,
    model: payload?.model,
  }
}

// ... keep existing content unchanged until Documents section ...

export interface DocumentOut {
  id: string
  title: string
  file_type: string
  file_size: number
  chunk_count: number
  chunk_strategy: number
  version: number
  status: 'pending' | 'processing' | 'ready' | 'error'
  created_at: string
  updated_at: string
  metadata?: Record<string, unknown>
}

export const CHUNK_STRATEGY_LABELS: Record<number, string> = {
  1: '上下文感知分块',
  2: '固定长度分块（预留）',
  3: '段落分割（预留）',
  4: '标题感知分块（预留）',
  5: '语义相似度分块（预留）',
  6: '滑动窗口分块（预留）',
  7: '递归字符分块（预留）',
  8: 'LLM辅助分块（预留）',
}

export interface DocumentDetail extends DocumentOut {
  content_preview: string
}

export interface SearchResult {
  document_id: string
  title: string
  chunk_index: number
  content: string
  score: number
}

export async function apiListDocuments(token: string): Promise<DocumentOut[]> {
  const res = await apiFetch('/documents', { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to list documents')
  return res.json()
}

export async function apiUploadDocument(
  token: string,
  file: File,
  options?: { title?: string; chunk_strategy?: number }
): Promise<DocumentOut> {
  const form = new FormData()
  form.append('file', file)
  if (options?.title) form.append('title', options.title)
  if (options?.chunk_strategy) form.append('chunk_strategy', String(options.chunk_strategy))
  const res = await apiFetch('/documents', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!res.ok) {
    throw new Error(await readApiError(res, 'Upload failed'))
  }
  return res.json()
}

export async function apiDeleteDocument(token: string, id: string): Promise<void> {
  const res = await apiFetch(`/documents/${id}`, {
    method: 'DELETE',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to delete document')
}

export async function apiGetDocument(token: string, id: string): Promise<DocumentDetail> {
  const res = await apiFetch(`/documents/${id}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to get document')
  return res.json()
}

export async function apiLogin(email: string, password: string): Promise<any> {
  const res = await apiFetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as any
    throw new Error(err.message || err.detail || 'Login failed')
  }
  return res.json()
}

export async function apiRegister(email: string, displayName?: string): Promise<{ message: string; email: string }> {
  const res = await apiFetch('/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, display_name: displayName }),
  })
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as any
    throw new Error(err.message || err.detail || 'Registration failed')
  }
  return res.json()
}

export async function apiGetCurrentUser(token: string): Promise<any> {
  const res = await apiFetch('/auth/me', { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to get current user')
  return res.json()
}

export async function apiListUsers(token: string, status?: string): Promise<any> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  const res = await apiFetch(`/admin/users${qs}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to list users')
  return res.json()
}

export async function apiApproveUser(token: string, userId: string): Promise<any> {
  const res = await apiFetch(`/admin/users/${userId}/approve`, {
    method: 'POST',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to approve user')
  return res.json()
}

export async function apiDisableUser(token: string, userId: string): Promise<any> {
  const res = await apiFetch(`/admin/users/${userId}/disable`, {
    method: 'POST',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to disable user')
  return res.json()
}

export async function apiEnableUser(token: string, userId: string): Promise<any> {
  const res = await apiFetch(`/admin/users/${userId}/enable`, {
    method: 'POST',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to enable user')
  return res.json()
}

export async function apiCreateConversation(token: string, title?: string): Promise<any> {
  const res = await apiFetch('/conversations', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ title }),
  })
  if (!res.ok) throw new Error('Failed to create conversation')
  return res.json()
}

export async function apiListConversations(token: string, filters?: { query?: string; archived?: boolean }): Promise<ConversationItem[]> {
  const qs = new URLSearchParams()
  if (filters?.query) qs.set('query', filters.query)
  if (filters?.archived !== undefined) qs.set('archived', String(filters.archived))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  const res = await apiFetch(`/conversations${suffix}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to list conversations')
  return res.json()
}

export async function apiGetMessages(token: string, conversationId: string): Promise<MessageItem[]> {
  const res = await apiFetch(`/conversations/${conversationId}/messages`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to get messages')
  return res.json()
}

export async function apiRenameConversation(token: string, id: string, title: string): Promise<any> {
  const res = await apiFetch(`/conversations/${id}`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify({ title }) })
  if (!res.ok) throw new Error('Failed to rename conversation')
  return res.json()
}

export async function apiDeleteConversation(token: string, id: string): Promise<void> {
  const res = await apiFetch(`/conversations/${id}`, { method: 'DELETE', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, 'Failed to delete conversation'))
}

export async function apiArchiveConversation(token: string, id: string, archived = true): Promise<any> {
  const res = await apiFetch(`/conversations/${id}/archive`, { method: archived ? 'POST' : 'DELETE', headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to archive conversation')
  return res.json()
}

export async function apiPatchMessage(token: string, id: string, payload: any): Promise<any> {
  const res = await apiFetch(`/messages/${id}`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error('Failed to patch message')
  return res.json()
}

export async function apiBranchConversation(token: string, id: string, messageId: string): Promise<any> {
  const res = await apiFetch(`/conversations/${id}/branch`, { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ message_id: messageId }) })
  if (!res.ok) throw new Error('Failed to branch conversation')
  return res.json()
}

export async function apiGetMessageVersions(token: string, messageId: string): Promise<any> {
  const res = await apiFetch(`/chat/messages/${messageId}/versions`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to get message versions')
  return res.json()
}

export async function apiSubmitFeedback(
  token: string,
  sessionId: string,
  messageId: string | null,
  feedbackType: 'like' | 'dislike' | 'none',
  score?: number,
): Promise<any> {
  const res = await apiFetch('/chat/feedback', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({
      session_id: sessionId,
      message_id: messageId,
      feedback_type: feedbackType,
      score: score ?? (feedbackType === 'like' ? 1.0 : feedbackType === 'dislike' ? 0.0 : undefined),
    }),
  })
  if (!res.ok) throw new Error('Failed to submit feedback')
  return res.json()
}

export async function apiChatSync(
  token: string,
  sessionId: string,
  query: string,
  options: Record<string, unknown> = {}
): Promise<any> {
  if (RESPONSES_API_V2_ENABLED) {
    const res = await apiFetchResponses('/responses', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ input: query, conversation_id: sessionId, stream: false, ...options }),
    })
    if (!res.ok) throw new Error(await readApiError(res, 'Responses sync failed'))
    return responseToLegacyChat(await res.json())
  }
  const payload = { session_id: sessionId, query, stream: false, ...options }
  const res = await apiFetch('/chat', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await readApiError(res, 'Chat sync failed'))
  return res.json()
}

function parseSseEventBlock(block: string): { type: string; data: any } | null {
  const lines = block.split(/\r?\n/).filter(Boolean)
  const dataLines = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart())
  if (!dataLines.length) return null
  const raw = dataLines.join('\n')
  try {
    return JSON.parse(raw)
  } catch {
    return { type: 'message', data: raw }
  }
}

/** SSE parser — exported for stream protocol contract tests. */
export async function streamSseResponse(
  res: Response,
  callbacks: {
    onReasoningStep?: (step: ReasoningStep) => void
    onThinking?: (payload: any) => void
    onDelta?: (text: string) => void
    onToolCall?: (payload: any) => void
    onToolResult?: (payload: any) => void
    onDagNodeStart?: (payload: any) => void
    onDagNodeComplete?: (payload: any) => void
    onForceMode?: (mode: string | null) => void
    onFinalAnswer?: (envelope: TurnMetaEnvelope) => void | Promise<void>
    onError?: (err: any) => void | Promise<void>
  },
  signal?: AbortSignal,
) {
  const reader = res.body?.getReader()
  if (!reader) throw new Error('Streaming response unavailable')
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let splitIndex: number
      while ((splitIndex = buffer.indexOf('\n\n')) >= 0) {
        const chunk = buffer.slice(0, splitIndex).trim()
        buffer = buffer.slice(splitIndex + 2)
        if (!chunk || chunk.startsWith(':')) continue
        const event = parseSseEventBlock(chunk)
        if (!event) continue
        const type = String(event.type || '')
        const data = event.data ?? {}

        if (type === 'delta' || type === 'answer.delta' || type === 'response.output_text.delta') {
          callbacks.onDelta?.(String(data.text ?? data.delta ?? ''))
          continue
        }
        if (type === 'response.progress') {
          callbacks.onThinking?.(data)
          continue
        }
        if (type === 'thinking') {
          callbacks.onThinking?.(data)
          continue
        }
        if (type === 'reasoning_step') {
          callbacks.onReasoningStep?.(data)
          continue
        }
        if (type === 'tool_call') {
          callbacks.onToolCall?.(data)
          continue
        }
        if (type === 'tool_result') {
          callbacks.onToolResult?.(data)
          continue
        }
        if (type === 'dag_node_start') {
          callbacks.onDagNodeStart?.(data)
          continue
        }
        if (type === 'dag_node_complete') {
          callbacks.onDagNodeComplete?.(data)
          continue
        }
        if (type === 'force_mode') {
          callbacks.onForceMode?.(data?.mode ?? null)
          continue
        }
        if (type === 'final_answer' || type === 'answer.final' || type === 'response.completed') {
          const envelope = normalizeFinalAnswerEnvelope(data)
          await callbacks.onFinalAnswer?.(envelope)
          continue
        }
        if (type === 'knowledge.ingest.status' || type === 'knowledge.operation.status' || type === 'route.selected' || type === 'turn.accepted') {
          callbacks.onThinking?.(data)
          continue
        }
        if (type === 'aborted' || type === 'response.cancelled') {
          throw new DOMException('Aborted', 'AbortError')
        }
        if (type === 'error' || type === 'response.failed') {
          throw new Error(data?.message ? String(data.message) : 'Streaming error')
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

export async function apiChatStream(
  token: string,
  sessionId: string,
  query: string,
  callbacks: {
    onReasoningStep?: (step: ReasoningStep) => void
    onThinking?: (payload: any) => void
    onDelta?: (text: string) => void
    onToolCall?: (payload: any) => void
    onToolResult?: (payload: any) => void
    onDagNodeStart?: (payload: any) => void
    onDagNodeComplete?: (payload: any) => void
    onForceMode?: (mode: string | null) => void
    onFinalAnswer?: (...args: any[]) => void | Promise<void>
    onError?: (err: any) => void | Promise<void>
  } = {},
  webEnabled?: boolean,
  signal?: AbortSignal,
  mode?: string,
  payload?: Record<string, unknown>,
  graphControls?: Record<string, unknown>
): Promise<void> {
  void webEnabled
  void mode
  // Stream protocol includes dag_node_start / dag_node_complete (see streamSseResponse).
  void callbacks.onDagNodeStart
  void callbacks.onDagNodeComplete
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
  const finalPayload = { session_id: sessionId, query, stream: true, ...payload, ...(graphControls ? { graph_controls: graphControls } : {}) }
  try {
    const res = await (RESPONSES_API_V2_ENABLED
      ? apiFetchResponses('/responses', {
          method: 'POST',
          headers: authHeaders(token),
          body: JSON.stringify({ input: query, conversation_id: sessionId, stream: true, ...payload, ...(graphControls ? { graph_controls: graphControls } : {}) }),
          signal,
        })
      : apiFetch('/chat', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(finalPayload),
      signal,
      }))

    if (res.status === 404 || res.headers.get('content-type')?.includes('application/json') && !res.headers.get('content-type')?.includes('text/event-stream')) {
      const sync = await apiChatSync(token, sessionId, query, { ...payload, stream: false, ...(graphControls ? { graph_controls: graphControls } : {}) })
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
      const fm = sync?.metadata?.force_mode ?? null
      if (fm) callbacks.onForceMode?.(fm)
      if (sync?.reasoning_steps && Array.isArray(sync.reasoning_steps)) {
        for (const step of sync.reasoning_steps) callbacks.onReasoningStep?.(step)
      }
      if (sync?.thinking) callbacks.onThinking?.(sync.thinking)
      const streamedText = String(sync?.delta ?? sync?.content ?? sync?.answer ?? '')
      if (sync?.delta) {
        callbacks.onDelta?.(String(sync.delta))
      } else if (streamedText) {
        const segments = streamedText.match(/\n\n|\n|.{1,12}/g) || []
        for (const seg of segments) {
          if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
          callbacks.onDelta?.(seg)
          await new Promise((resolve) => window.setTimeout(resolve, 16))
        }
      }
      if (sync?.tool_calls && Array.isArray(sync.tool_calls)) {
        for (const item of sync.tool_calls) callbacks.onToolCall?.(item)
      }
      if (sync?.tool_results && Array.isArray(sync.tool_results)) {
        for (const item of sync.tool_results) callbacks.onToolResult?.(item)
      }
      await callbacks.onFinalAnswer?.(
        normalizeFinalAnswerEnvelope({
          content: sync?.content ?? sync?.answer ?? '',
          execution_graph: sync?.execution_graph ?? null,
          citations: sync?.citations ?? [],
          annotations: sync?.annotations ?? [],
          metadata: sync?.metadata ?? {},
          prompt_tokens: sync?.prompt_tokens,
          completion_tokens: sync?.completion_tokens,
        }),
      )
      return
    }

    if (!res.ok) throw new Error(await readApiError(res, 'Chat stream failed'))
    const contentType = res.headers.get('content-type') || ''
    if (!contentType.includes('text/event-stream')) {
      const sync = (await res.json().catch(() => null)) as any
      if (!sync) throw new Error('Invalid chat response')
      await callbacks.onFinalAnswer?.(
        normalizeFinalAnswerEnvelope({
          content: sync?.content ?? '',
          execution_graph: sync?.execution_graph ?? null,
          citations: sync?.citations ?? [],
          annotations: sync?.annotations ?? [],
          metadata: sync?.metadata ?? {},
        }),
      )
      return
    }

    await streamSseResponse(res, callbacks, signal)
  } catch (err) {
    if (err instanceof Error && err.message.includes('Not Found')) {
      await callbacks.onFinalAnswer?.(
        normalizeFinalAnswerEnvelope({
          content: `我叫 OpenTrace，是这个工作台里的 AI 助手。\n\n你刚刚问的是：${query}\n\n当前后端聊天接口返回了 Not Found，所以我先用前端兜底回复你。`,
        }),
      )
      return
    }
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err
    }
    await callbacks.onError?.(err)
    throw err
  }
}

export async function apiGraphControl(..._args: any[]): Promise<any> {
  return { ok: true }
}

export async function apiGetSessionSkills(..._args: any[]): Promise<any> {
  return { enabled_skills: [], disabled_skills: [] }
}

export async function apiSetSessionSkills(..._args: any[]): Promise<any> {
  return { ok: true }
}

export async function apiStopChatStream(..._args: any[]): Promise<any> {
  return { ok: true }
}

export async function apiCreateMemory(token: string, payload: any): Promise<any> {
  const res = await apiFetch('/memories', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error('Failed to create memory')
  return res.json()
}

export async function apiListMemories(token: string, memoryType?: string): Promise<MemoryItem[]> {
  const qs = memoryType ? `?memory_type=${encodeURIComponent(memoryType)}` : ''
  const res = await apiFetch(`/memories${qs}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to list memories')
  return res.json()
}

export async function apiDeleteMemory(token: string, id: string): Promise<void> {
  const res = await apiFetch(`/memories/${id}`, { method: 'DELETE', headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to delete memory')
}

export async function apiUpdateMemory(token: string, id: string, payload: any): Promise<any> {
  const res = await apiFetch(`/memories/${id}`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error('Failed to update memory')
  return res.json()
}

export async function apiGetMemorySettings(token: string): Promise<MemorySettings> {
  const res = await apiFetch('/memories/settings', { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to get memory settings')
  return res.json()
}

export async function apiSetMemorySettings(token: string, payload: Partial<MemorySettings>): Promise<MemorySettings> {
  const res = await apiFetch('/memories/settings', { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error('Failed to set memory settings')
  return res.json()
}

export async function apiListDatabases(token: string): Promise<DataSourceItem[]> { const res = await apiFetch('/databases', { headers: authHeaders(token) }); if (!res.ok) throw new Error('Failed to list databases'); const data = await res.json(); return Array.isArray(data) ? data : data.items || []; }
export async function apiCreateDatabase(token: string, payload: any): Promise<any> { const res = await apiFetch('/databases', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) }); if (!res.ok) throw new Error('Failed to create database'); return res.json() }
export async function apiDeleteDatabase(token: string, id: string): Promise<void> { const res = await apiFetch(`/databases/${id}`, { method: 'DELETE', headers: authHeaders(token) }); if (!res.ok) throw new Error('Failed to delete database') }
export async function apiUpdateDatabase(token: string, id: string, payload: any): Promise<any> {
  const res = await apiFetch(`/databases/${id}`, {
    method: 'PATCH',
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await readApiError(res, '更新数据库失败'))
  return res.json()
}
export async function apiAnalyzeDatabase(token: string, id: string): Promise<any> { const res = await apiFetch(`/databases/${id}/analysis`, { method: 'POST', headers: authHeaders(token) }); if (!res.ok) throw new Error('Failed to analyze database'); return res.json() }
export async function apiDatabaseQuery(token: string, id: string, query: any): Promise<any> { const res = await apiFetch(`/databases/${id}/query`, { method: 'POST', headers: authHeaders(token), body: JSON.stringify(query) }); if (!res.ok) throw new Error('Failed to query database'); return res.json() }
export async function apiGetDatabaseSchema(token: string, id: string): Promise<any> { const res = await apiFetch(`/databases/${id}/schema`, { headers: authHeaders(token) }); if (!res.ok) throw new Error('Failed to get database schema'); return res.json() }
export async function apiSyncDatabaseSchema(token: string, id: string): Promise<any> { const res = await apiFetch(`/databases/${id}/sync-schema`, { method: 'POST', headers: authHeaders(token) }); if (!res.ok) throw new Error('Failed to sync database schema'); return res.json() }
export async function apiTestDatabaseConnection(token: string, databaseId: string): Promise<any> { const res = await apiFetch(`/databases/${databaseId}/test-connection`, { method: 'POST', headers: authHeaders(token) }); if (!res.ok) throw new Error('Failed to test database connection'); return res.json() }

export async function apiUpdateDocument(
  token: string,
  id: string,
  payload: { title?: string; file?: File }
): Promise<DocumentOut> {
  const form = new FormData()
  if (payload.title !== undefined) form.append('title', payload.title)
  if (payload.file) form.append('file', payload.file)
  const res = await apiFetch(`/documents/${id}`, {
    method: 'PUT',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!res.ok) throw new Error(await readApiError(res, 'Update document failed'))
  return res.json()
}

export async function apiSearchDocuments(
  token: string,
  query: string,
  topK = 6
): Promise<SearchResult[]> {
  const res = await apiFetch('/documents/search', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ query, top_k: topK }),
  })
  if (!res.ok) throw new Error('Search failed')
  return res.json()
}

export interface TaskItem {
  id: string
  title: string
  description?: string
  trigger_type?: string
  status: string
}

export interface TaskRunItem {
  id: string
  status: string
  output?: string
  error?: string
}

export interface TaskNotificationItem {
  id: string
  title: string
  body?: string
  read: boolean
}

export async function apiListTasks(token: string): Promise<TaskItem[]> {
  const res = await apiFetch('/tasks', { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to list tasks')
  return res.json()
}

export async function apiGetTask(token: string, id: string): Promise<{ runs: TaskRunItem[] }> {
  const res = await apiFetch(`/tasks/${id}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to get task')
  return res.json()
}

export async function apiCreateTask(token: string, description: string): Promise<any> {
  const res = await apiFetch('/tasks', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ description }),
  })
  if (!res.ok) throw new Error('Failed to create task')
  return res.json()
}

export async function apiPauseTask(token: string, id: string): Promise<any> {
  const res = await apiFetch(`/tasks/${id}/pause`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to pause task')
  return res.json()
}

export async function apiResumeTask(token: string, id: string): Promise<any> {
  const res = await apiFetch(`/tasks/${id}/resume`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to resume task')
  return res.json()
}

export async function apiCancelTask(token: string, id: string): Promise<any> {
  const res = await apiFetch(`/tasks/${id}/cancel`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to cancel task')
  return res.json()
}

export async function apiListTaskNotifications(token: string): Promise<TaskNotificationItem[]> {
  const res = await apiFetch('/tasks/notifications', { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to list task notifications')
  return res.json()
}

export async function apiMarkTaskNotificationRead(token: string, id: string): Promise<any> {
  const res = await apiFetch(`/tasks/notifications/${id}/read`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to mark task notification read')
  return res.json()
}

export interface AuditLogItem {
  id: string
  action: string
  created_at: string
  actor?: string
  resource_type?: string
  resource_id?: string
  payload?: unknown
}

export async function apiListAuditLogs(token: string, filters?: { action?: string; start?: string; end?: string }): Promise<AuditLogItem[]> {
  const qs = new URLSearchParams()
  if (filters?.action) qs.set('action', filters.action)
  if (filters?.start) qs.set('start', filters.start)
  if (filters?.end) qs.set('end', filters.end)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  const res = await apiFetch(`/audit/logs${suffix}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to list audit logs')
  return res.json()
}

export async function apiExportAuditLogs(token: string, filters?: { action?: string; start?: string; end?: string; format?: string }): Promise<string> {
  const qs = new URLSearchParams()
  if (filters?.action) qs.set('action', filters.action)
  if (filters?.start) qs.set('start', filters.start)
  if (filters?.end) qs.set('end', filters.end)
  if (filters?.format) qs.set('format', filters.format)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  const res = await apiFetch(`/audit/logs/export${suffix}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to export audit logs')
  return res.text()
}

export interface MemoryItem {
  id: string
  title: string
  content: string
  memory_type: string
  kind?: string
  enabled?: boolean
  access_count?: number
  tags?: string[]
}

export interface DataSourceItem {
  id: string
  name: string
  type: string
  host?: string
  port?: number
  database?: string
  username?: string
  status?: string
  table_count?: number
  last_schema_sync_at?: string
  synced_at?: string
  updated_at?: string
}

export interface ConnectorItem {
  id: string
  display_name?: string
  status: string
  capabilities?: string[]
}

export interface SkillItem {
  id: string
  skill_id?: string
  name?: string
  version?: string
  entrypoint?: string
  description?: string
  skill_type?: string
  code?: string
  test_cases?: Array<Record<string, unknown>>
  data_source_id?: string
  path?: string
  created_at?: string
}

export async function apiListConnectors(token: string): Promise<ConnectorItem[]> {
  const res = await apiFetch('/connectors', { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to list connectors')
  return res.json()
}

export async function apiConnectorAuthorize(token: string, provider: string, redirectUri: string): Promise<any> {
  const res = await apiFetch('/connectors/authorize', { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ provider, redirect_uri: redirectUri }) })
  if (!res.ok) throw new Error('Failed to authorize connector')
  return res.json()
}

export async function apiConnectorCallback(token: string, provider: string, code: string, redirectUri: string): Promise<any> {
  const res = await apiFetch('/connectors/callback', { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ provider, code, redirect_uri: redirectUri }) })
  if (!res.ok) throw new Error('Failed to complete connector callback')
  return res.json()
}

export async function apiConnectorResources(token: string, provider: string): Promise<any> {
  const res = await apiFetch(`/connectors/${provider}/resources`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to fetch connector resources')
  return res.json()
}

export async function apiConnectorSync(token: string, provider: string): Promise<any> {
  const res = await apiFetch(`/connectors/${provider}/sync`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to sync connector')
  return res.json()
}

export async function apiListSkills(token: string): Promise<SkillItem[]> {
  const res = await apiFetch('/skills', { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to list skills')
  return res.json()
}

export async function apiInstallSkill(token: string, gitUrl: string, ref: string): Promise<any> {
  const res = await apiFetch('/skills/install', { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ git_url: gitUrl, ref }) })
  if (!res.ok) throw new Error('Failed to install skill')
  return res.json()
}

export async function apiUninstallSkill(token: string, id: string): Promise<any> {
  const res = await apiFetch('/skills/uninstall', { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ skill_id: id }) })
  if (!res.ok) throw new Error('Failed to uninstall skill')
  return res.json()
}

export async function apiCreateSkill(token: string, payload: {
  name: string
  version?: string
  entrypoint?: string
  code?: string
  description?: string
  skill_type?: string
  test_cases?: Array<Record<string, unknown>>
  data_source_id?: string
}): Promise<any> {
  const res = await apiFetch('/skills/create', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error('Failed to create skill')
  return res.json()
}

export async function apiGetSkill(token: string, id: string): Promise<SkillItem> {
  const res = await apiFetch(`/skills/${id}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to get skill')
  const data = await res.json()
  return data.skill
}

export async function apiTestSkill(token: string, id: string, testInput: Record<string, unknown>): Promise<any> {
  const res = await apiFetch(`/skills/${id}/test`, { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ test_input: testInput }) })
  if (!res.ok) throw new Error('Failed to test skill')
  return res.json()
}

export async function apiGetSemanticConfig(token: string, dataSourceId: string): Promise<any> {
  const res = await apiFetch(`/databases/${dataSourceId}/semantic`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to get semantic config')
  return res.json()
}

export async function apiUpdateSemanticConfig(token: string, dataSourceId: string, payload: {
  dimensions?: Record<string, { column: string; table: string }>
  metrics?: Record<string, string>
  time_macros?: Array<{ keyword: string; column: string; days: number }>
}): Promise<any> {
  const res = await apiFetch(`/databases/${dataSourceId}/semantic`, { method: 'PUT', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error('Failed to update semantic config')
  return res.json()
}

export async function apiAutoExtractSemantic(token: string, dataSourceId: string): Promise<any> {
  const res = await apiFetch(`/databases/${dataSourceId}/semantic/auto-extract`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to auto-extract semantic')
  return res.json()
}

export async function apiGetUiSettings(token: string): Promise<any> {
  const res = await apiFetch('/ui/settings', { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to get UI settings')
  return res.json()
}

export async function apiPatchUiSettings(token: string, payload: any): Promise<any> {
  const res = await apiFetch('/ui/settings', { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error('Failed to patch UI settings')
  return res.json()
}

// ── Rules API ────────────────────────────────────────────────────────
export interface RuleItem {
  id: string
  name: string
  trigger: string
  description: string
  version: string
  filename: string
  data_sources_count: number
  conditions_count: number
  outputs_count: number
}

export interface RuleCondition {
  id: string
  data_ref: string
  expr: string
}

export interface RuleOutput {
  label: string
  when: string[]
  template: string
}

export interface RuleDataSource {
  label: string
  type: string
  description?: string
  sql?: string
  value?: Record<string, unknown>
}

export interface RuleFormData {
  id: string
  name: string
  trigger: string
  description: string
  version: string
  data_sources: RuleDataSource[]
  conditions: RuleCondition[]
  outputs: RuleOutput[]
}

export async function apiListRules(token: string): Promise<RuleItem[]> {
  const res = await apiFetch('/rules', { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to list rules')
  return res.json()
}

export async function apiGetRule(token: string, filename: string): Promise<RuleFormData & { yaml_raw: string; filename: string }> {
  const res = await apiFetch(`/rules/${encodeURIComponent(filename)}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to get rule')
  return res.json()
}

export async function apiCreateRule(token: string, payload: RuleFormData): Promise<any> {
  const res = await apiFetch('/rules', {
    method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error('Failed to create rule')
  return res.json()
}

export async function apiUpdateRule(token: string, filename: string, payload: RuleFormData): Promise<any> {
  const res = await apiFetch(`/rules/${encodeURIComponent(filename)}`, {
    method: 'PUT', headers: authHeaders(token), body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error('Failed to update rule')
  return res.json()
}

export async function apiDeleteRule(token: string, filename: string): Promise<void> {
  const res = await apiFetch(`/rules/${encodeURIComponent(filename)}`, {
    method: 'DELETE', headers: authHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to delete rule')
}

export async function apiGenerateRule(token: string, payload: {
  id: string; name: string; trigger: string; description: string;
  dataSourcesCount: number; conditionsCount: number; outputsCount: number;
}): Promise<{ rule: RuleFormData; yaml_content: string; filename: string }> {
  const res = await apiFetch('/rules/generate', {
    method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error('Failed to generate rule')
  return res.json()
}

// ── Attachment API ────────────────────────────────────────────────────────

export interface AttachmentUploadResponse {
  attachment_id: string
  content_summary: string
  content_hash: string
  is_duplicate: boolean
  scope?: 'session' | 'workspace'
  ingest_status?: string
}

export interface AttachmentInfo {
  id: string
  filename: string
  file_size: number
  mime_type: string | null
  file_extension: string | null
  content_summary: string | null
  status: string
  message_id: string | null
  created_at: string
  scope?: 'session' | 'workspace'
  ingest_status?: string
  promoted_document_id?: string | null
}

export interface AttachmentListResponse {
  session_id: string
  attachments: AttachmentInfo[]
  total: number
}

export interface AttachmentItem {
  id: string
  file: File
  name: string
  size: number
  status: 'pending' | 'uploading' | 'done' | 'error'
  serverId?: string
  contentHash?: string
  contentSummary?: string
  isDuplicate?: boolean
  error?: string
  ingestStatus?: string
}

export async function apiUploadAttachment(
  token: string,
  file: File,
  sessionId: string,
  messageId?: string,
  onProgress?: (pct: number) => void,
): Promise<AttachmentUploadResponse> {
  const form = new FormData()
  form.append('file', file)
  form.append('session_id', sessionId)
  if (messageId) form.append('message_id', messageId)

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE}/chat/attachments`)

    xhr.setRequestHeader('Authorization', `Bearer ${token}`)

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100))
      }
    })

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText))
        } catch {
          reject(new Error('Invalid response'))
        }
      } else {
        let msg = 'Upload failed'
        try {
          const err = JSON.parse(xhr.responseText)
          msg = err.message || err.detail || msg
        } catch { /* ignore */ }
        reject(new Error(msg))
      }
    })

    xhr.addEventListener('error', () => reject(new Error('Network error')))
    xhr.addEventListener('abort', () => reject(new Error('Upload aborted')))

    xhr.send(form)
  })
}

export async function apiListAttachments(
  token: string,
  sessionId: string,
): Promise<AttachmentListResponse> {
  const res = await fetch(`${BASE}/chat/attachments/${sessionId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: 'Failed to list attachments' }))
    throw new Error(err.message || err.detail || 'Failed to list attachments')
  }
  return res.json()
}

export async function apiDeleteAttachment(
  token: string,
  attachmentId: string,
): Promise<{ attachment_id: string; status: string }> {
  const res = await fetch(`${BASE}/chat/attachments/${attachmentId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: 'Delete failed' }))
    throw new Error(err.message || err.detail || 'Delete failed')
  }
  return res.json()
}

export async function apiPromoteAttachment(
  token: string,
  attachmentId: string,
  publishPolicy: 'review' | 'auto' = 'review',
): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/chat/attachments/${attachmentId}/promote?publish_policy=${publishPolicy}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: 'Promote failed' }))
    throw new Error(err.message || err.detail || 'Promote failed')
  }
  return res.json()
}

// ── Personalization API ──────────────────────────────────────────────────

export interface CustomInstructions {
  id?: string
  about_user: string
  response_style: string
  enabled: boolean
  version: number
  tenant_id?: string
  workspace_id?: string
  updated_at?: string | null
}

export async function apiGetCustomInstructions(token: string): Promise<CustomInstructions> {
  const res = await apiFetch('/personalization/custom-instructions', {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to load custom instructions')
  return res.json()
}

export async function apiSetCustomInstructions(
  token: string,
  payload: Pick<CustomInstructions, 'about_user' | 'response_style' | 'enabled'>,
): Promise<CustomInstructions> {
  const res = await apiFetch('/personalization/custom-instructions', {
    method: 'PUT',
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error('Failed to save custom instructions')
  return res.json()
}

export async function apiDeleteCustomInstructions(token: string): Promise<{ deleted: boolean }> {
  const res = await apiFetch('/personalization/custom-instructions', {
    method: 'DELETE',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error('Failed to delete custom instructions')
  return res.json()
}
