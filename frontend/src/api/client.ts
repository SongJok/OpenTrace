// API client — all backend calls go through here
import { normalizeFinalAnswerEnvelope, type TurnMetaEnvelope } from '../utils/streamEnvelope'

const BASE = '/api/v1'
const RESPONSES_BASE = '/api/v2'

export type { TurnMetaEnvelope }
const ENV_API = (import.meta as any)?.env?.VITE_API_URL as string | undefined
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
  pinned?: boolean
  is_temporary?: boolean
  expires_at?: string | null
}

export interface MessageItem {
  id: string
  conversation_id: string
  role: string
  content: string
  created_at?: string
  response_id?: string
  parent_response_id?: string | null
  version_index?: number
  sibling_count?: number
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

export type ResponseStatus = 'queued' | 'in_progress' | 'requires_action' | 'completed' | 'failed' | 'incomplete' | 'cancelled'

export interface ResponseOutputItem {
  id: string
  type: 'input_message' | 'message' | 'reasoning' | 'function_call' | 'function_call_output' | 'approval_request' | 'citation' | 'error'
  role?: string | null
  content?: string | null
  payload?: Record<string, unknown>
  sequence_number: number
}

export interface OpenTraceResponse {
  id: string
  object: 'response'
  status: ResponseStatus
  conversation: { id: string }
  conversation_id: string
  previous_response_id?: string | null
  model?: string | null
  output?: ResponseOutputItem[]
  metadata?: Record<string, unknown>
  error?: { code?: string; message?: string } | null
}

export interface ApprovalRequest {
  id: string
  call_id: string
  tool_name: string
  side_effect: 'write' | 'destructive'
  arguments: Record<string, unknown>
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

export async function apiCreateConversation(token: string, title?: string, temporary = false): Promise<any> {
  const res = await apiFetchResponses('/conversations', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ title, temporary }),
  })
  if (!res.ok) throw new Error('Failed to create conversation')
  return res.json()
}

export async function apiListConversations(token: string, filters?: { query?: string; archived?: boolean }): Promise<ConversationItem[]> {
  const qs = new URLSearchParams()
  if (filters?.query) qs.set('query', filters.query)
  if (filters?.archived !== undefined) qs.set('archived', String(filters.archived))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  const res = await apiFetchResponses(`/conversations${suffix}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to list conversations')
  return res.json()
}

export async function apiGetMessages(token: string, conversationId: string): Promise<MessageItem[]> {
  const res = await apiFetchResponses(`/conversations/${conversationId}/messages`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to get messages')
  return res.json()
}

export async function apiRenameConversation(token: string, id: string, title: string): Promise<any> {
  const res = await apiFetchResponses(`/conversations/${id}`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify({ title }) })
  if (!res.ok) throw new Error('Failed to rename conversation')
  return res.json()
}

export async function apiDeleteConversation(token: string, id: string): Promise<void> {
  const res = await apiFetchResponses(`/conversations/${id}`, { method: 'DELETE', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, 'Failed to delete conversation'))
}

export async function apiArchiveConversation(token: string, id: string, archived = true): Promise<any> {
  const res = await apiFetchResponses(`/conversations/${id}/archive`, { method: archived ? 'POST' : 'DELETE', headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to archive conversation')
  return res.json()
}

export async function apiUpdateConversation(token: string, id: string, payload: { title?: string; pinned?: boolean }): Promise<any> {
  const res = await apiFetchResponses(`/conversations/${id}`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, 'Failed to update conversation'))
  return res.json()
}

export async function apiCreateConversationShare(token: string, id: string): Promise<{ url: string; public_id: string; token: string }> {
  const res = await apiFetchResponses(`/conversations/${id}/share`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, 'Failed to share conversation'))
  return res.json()
}

export async function apiSetActiveResponse(token: string, conversationId: string, responseId: string): Promise<void> {
  const res = await apiFetchResponses(`/conversations/${conversationId}/active-response`, { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ response_id: responseId }) })
  if (!res.ok) throw new Error(await readApiError(res, 'Failed to switch response version'))
}

export async function apiListResponseSiblings(token: string, responseId: string): Promise<Array<{ id: string; active: boolean; status: string }>> {
  const res = await apiFetchResponses(`/responses/${encodeURIComponent(responseId)}/siblings`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, 'Failed to load response versions'))
  return ((await res.json()) as { items?: Array<{ id: string; active: boolean; status: string }> }).items ?? []
}

export async function apiRetryResponse(token: string, responseId: string, input?: string): Promise<any> {
  const res = await apiFetchResponses(`/responses/${responseId}/retry`, { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ input, stream: true }) })
  if (!res.ok) throw new Error(await readApiError(res, 'Failed to retry response'))
  return res
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
  const res = await apiFetchResponses(`/messages/${messageId}/versions`, { headers: authHeaders(token) })
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
  const res = await apiFetchResponses(`/responses/${encodeURIComponent(messageId || sessionId)}/feedback`, {
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

export async function apiGetResponse(token: string, responseId: string): Promise<any> {
  const res = await apiFetchResponses(`/responses/${encodeURIComponent(responseId)}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取响应失败'))
  return res.json()
}

export async function apiResumeResponse(
  token: string,
  responseId: string,
  startingAfter = -1,
  callbacks: Parameters<typeof streamSseResponse>[1] = {},
  signal?: AbortSignal,
): Promise<void> {
  const res = await apiFetchResponses(`/responses/${encodeURIComponent(responseId)}?stream=true&starting_after=${startingAfter}`, {
    headers: authHeaders(token),
    signal,
  })
  if (!res.ok) throw new Error(await readApiError(res, '恢复响应失败'))
  await streamSseResponse(res, callbacks, signal)
}

export async function apiCancelResponse(token: string, responseId: string): Promise<any> {
  const res = await apiFetchResponses(`/responses/${encodeURIComponent(responseId)}/cancel`, {
    method: 'POST',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '停止响应失败'))
  return res.json()
}

export async function apiResolveResponseApproval(
  token: string,
  responseId: string,
  approvalId: string,
  approved: boolean,
  reason?: string,
): Promise<any> {
  const res = await apiFetchResponses(`/responses/${encodeURIComponent(responseId)}/approvals/${encodeURIComponent(approvalId)}/resolve`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ approved, reason }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '审批失败'))
  return res.json()
}

export interface ProjectItem {
  id: string
  name: string
  description: string
  instructions: string
  assistant_profile_id?: string | null
  data_source_ids: string[]
}

export async function apiListProjects(token: string): Promise<ProjectItem[]> {
  const res = await apiFetchResponses('/projects', { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取 Projects 失败'))
  return (await res.json()).items ?? []
}

export async function apiCreateProject(token: string, payload: Omit<ProjectItem, 'id'>): Promise<ProjectItem> {
  const res = await apiFetchResponses('/projects', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, '创建 Project 失败'))
  return res.json()
}

export interface AssistantProfileItem {
  id: string
  name: string
  personality: 'none' | 'friendly' | 'pragmatic'
  instructions: string
  default_model_profile: 'auto' | 'fast' | 'deep'
  built_in: boolean
  is_default: boolean
}

export async function apiListAssistantProfiles(token: string): Promise<AssistantProfileItem[]> {
  const res = await apiFetchResponses('/assistant-profiles', { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取助手角色失败'))
  return (await res.json()).items ?? []
}

export async function apiCreateAssistantProfile(token: string, payload: Record<string, unknown>): Promise<AssistantProfileItem> {
  const res = await apiFetchResponses('/assistant-profiles', {
    method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await readApiError(res, '创建助手角色失败'))
  return res.json()
}

export interface GoalItem {
  id: string
  objective: string
  success_criteria: string
  status: string
  project_id?: string | null
  conversation_id?: string | null
  response_id?: string | null
  current_step: number
}

export async function apiListGoals(token: string): Promise<GoalItem[]> {
  const res = await apiFetchResponses('/goals', { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取 Goals 失败'))
  return (await res.json()).items ?? []
}

export async function apiCreateGoal(token: string, payload: Record<string, unknown>): Promise<GoalItem> {
  const res = await apiFetchResponses('/goals', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, '创建 Goal 失败'))
  return res.json()
}

export async function apiGoalAction(token: string, goalId: string, action: 'pause' | 'resume' | 'cancel'): Promise<GoalItem> {
  const res = await apiFetchResponses(`/goals/${encodeURIComponent(goalId)}/${action}`, {
    method: 'POST', headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '更新 Goal 失败'))
  return res.json()
}

export interface ScheduledTaskItem {
  id: string
  title: string
  prompt: string
  rrule: string
  timezone: string
  status: string
  next_run_at?: string | null
  last_run_at?: string | null
  requires_confirmation: boolean
}

export async function apiListScheduledTasks(token: string): Promise<ScheduledTaskItem[]> {
  const res = await apiFetchResponses('/scheduled-tasks', { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取定时任务失败'))
  return (await res.json()).items ?? []
}

export async function apiCreateScheduledTask(token: string, payload: Record<string, unknown>): Promise<ScheduledTaskItem> {
  const res = await apiFetchResponses('/scheduled-tasks', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, '创建定时任务失败'))
  return res.json()
}

export async function apiPreviewScheduledTask(token: string, expression: string, timezone: string): Promise<{ rrule: string; timezone: string; next_run_at?: string | null }> {
  const res = await apiFetchResponses('/scheduled-tasks/preview', {
    method: 'POST', headers: authHeaders(token), body: JSON.stringify({ expression, timezone }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '无法解析运行时间'))
  return res.json()
}

export async function apiScheduledTaskAction(token: string, taskId: string, action: 'enable' | 'pause' | 'cancel'): Promise<ScheduledTaskItem> {
  const res = await apiFetchResponses(`/scheduled-tasks/${encodeURIComponent(taskId)}/actions/${action}`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '更新定时任务失败'))
  return res.json()
}

function parseSseEventBlock(block: string): { sequence_number?: number; type: string; data: any } | null {
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
    onEvent?: (event: { sequence_number?: number; type?: string; data?: any }) => void
    onResponseCreated?: (payload: any) => void
    onReasoningStep?: (step: ReasoningStep) => void
    onThinking?: (payload: any) => void
    onDelta?: (text: string) => void
    onToolCall?: (payload: any) => void
    onToolResult?: (payload: any) => void
    onApprovalRequired?: (approvals: ApprovalRequest[]) => void
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
      if (done) {
        if (!buffer.trim()) break
        buffer += '\n\n'
      } else {
        buffer += decoder.decode(value, { stream: true })
      }
      let splitIndex: number
      while ((splitIndex = buffer.indexOf('\n\n')) >= 0) {
        const chunk = buffer.slice(0, splitIndex).trim()
        buffer = buffer.slice(splitIndex + 2)
        if (!chunk || chunk.startsWith(':')) continue
        const event = parseSseEventBlock(chunk)
        if (!event) continue
        const type = String(event.type || '')
        const data = event.data ?? {}
        callbacks.onEvent?.(event)

        if (type === 'response.output_text.delta') {
          callbacks.onDelta?.(String(data.delta ?? ''))
          continue
        }
        if (type === 'response.created') {
          callbacks.onResponseCreated?.(data)
          continue
        }
        if (type.startsWith('opentrace.intent.') || type.startsWith('opentrace.context.') || type.startsWith('opentrace.model.')) {
          callbacks.onThinking?.(data)
          continue
        }
        if (type === 'response.reasoning_summary_text.done') {
          callbacks.onReasoningStep?.({ id: `summary-${event.sequence_number ?? Date.now()}`, stage: 'FINAL', content: String(data.text ?? ''), status: 'done' })
          continue
        }
        if (type === 'opentrace.tool.started') {
          callbacks.onToolCall?.(data)
          continue
        }
        if (type === 'opentrace.tool.completed' || type === 'opentrace.tool.failed') {
          callbacks.onToolResult?.(data)
          continue
        }
        if (type === 'response.requires_action') {
          callbacks.onApprovalRequired?.(Array.isArray(data.approvals) ? data.approvals : [])
          continue
        }
        if (type === 'response.completed') {
          const envelope = normalizeFinalAnswerEnvelope(data)
          await callbacks.onFinalAnswer?.(envelope)
          continue
        }
        if (type === 'response.cancelled') {
          throw new DOMException('Aborted', 'AbortError')
        }
        if (type === 'error' || type === 'response.failed') {
          throw new Error(data?.message ? String(data.message) : 'Streaming error')
        }
      }
      if (done) break
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
    onEvent?: (event: { sequence_number?: number; type?: string; data?: any }) => void
    onResponseCreated?: (payload: any) => void
    onReasoningStep?: (step: ReasoningStep) => void
    onThinking?: (payload: any) => void
    onDelta?: (text: string) => void
    onToolCall?: (payload: any) => void
    onToolResult?: (payload: any) => void
    onApprovalRequired?: (approvals: ApprovalRequest[]) => void
    onFinalAnswer?: (...args: any[]) => void | Promise<void>
    onError?: (err: any) => void | Promise<void>
  } = {},
  webEnabled?: boolean,
  signal?: AbortSignal,
  mode?: string,
  payload?: Record<string, unknown>,
  graphControls?: Record<string, unknown>
): Promise<void> {
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
  try {
    const retryResponseId = typeof payload?.retry_response_id === 'string' ? payload.retry_response_id : undefined
    const retryInput = typeof payload?.new_content === 'string' ? payload.new_content : undefined
    const res = await apiFetchResponses(retryResponseId ? `/responses/${encodeURIComponent(retryResponseId)}/retry` : '/responses', {
      // Retry reuses the server-side canonical input and creates a sibling,
      // avoiding the historic empty-query regeneration bug.
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({
        ...(retryResponseId ? { input: retryInput, stream: true } : {
          input: query,
          conversation: sessionId,
          stream: true,
          store: false,
          opentrace: {
            execution_profile: mode === 'fast' || mode === 'deep' ? mode : 'auto',
            memory_mode: payload?.memory_mode === 'temporary' ? 'temporary' : 'enabled',
            enabled_skills: Array.isArray(payload?.enabled_skills) ? payload.enabled_skills : [],
            project_id: typeof payload?.project_id === 'string' ? payload.project_id : undefined,
            assistant_profile_id: typeof payload?.assistant_profile_id === 'string' ? payload.assistant_profile_id : undefined,
          },
          ...(typeof payload?.model === 'string' && payload.model.trim() ? { model: payload.model.trim() } : {}),
        }),
      }),
      signal,
    })

    if (res.headers.get('content-type')?.includes('application/json') && !res.headers.get('content-type')?.includes('text/event-stream')) {
      const response = (await res.json().catch(() => null)) as any
      if (!response) throw new Error('Invalid Responses response')
      if (response.id && ['queued', 'in_progress'].includes(String(response.status || ''))) {
        callbacks.onResponseCreated?.({ response_id: response.id, status: response.status })
        await apiResumeResponse(token, String(response.id), -1, callbacks, signal)
        return
      }
      await callbacks.onFinalAnswer?.(normalizeFinalAnswerEnvelope({
        content: response?.content ?? response?.output_text ?? '',
        execution_graph: response?.execution_graph ?? null,
        citations: response?.citations ?? [],
        annotations: response?.annotations ?? [],
        metadata: response?.metadata ?? {},
      }))
      return
    }

    if (!res.ok) throw new Error(await readApiError(res, 'Responses stream failed'))
    const contentType = res.headers.get('content-type') || ''
    if (!contentType.includes('text/event-stream')) {
      const sync = (await res.json().catch(() => null)) as any
      if (!sync) throw new Error('Invalid Responses response')
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

    let responseId: string | null = null
    let cursor = -1
    const streamCallbacks = {
      ...callbacks,
      onEvent: (event: { sequence_number?: number; type?: string; data?: any }) => {
        if (typeof event.sequence_number === 'number') cursor = Math.max(cursor, event.sequence_number)
        responseId = String(event.data?.response_id || event.data?.id || responseId || '') || responseId
        callbacks.onEvent?.(event)
      },
    }
    try {
      await streamSseResponse(res, streamCallbacks, signal)
    } catch (streamError) {
      if (!signal?.aborted && responseId) {
        try {
          await apiResumeResponse(token, responseId, cursor, streamCallbacks, signal)
          return
        } catch {
          // Fall through to the regular error path after one deterministic resume.
        }
      }
      throw streamError
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err
    }
    await callbacks.onError?.(err)
    throw err
  }
}

export async function apiGraphControl(
  token: string,
  sessionId: string,
  action: 'prune' | 'expand',
  nodeId: string,
  requestId?: string,
): Promise<any> {
  const res = await apiFetch('/chat/graph-control', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ session_id: sessionId, request_id: requestId, action, node_id: nodeId }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '更新执行图失败'))
  return res.json()
}

export async function apiGetSessionSkills(token: string, sessionId: string): Promise<{ enabled_skills: string[]; disabled_skills: string[] }> {
  const res = await apiFetch(`/skills/session/${encodeURIComponent(sessionId)}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取会话技能失败'))
  return res.json()
}

export async function apiSetSessionSkills(
  token: string,
  sessionId: string,
  enabledSkills: string[],
  disabledSkills: string[],
): Promise<{ enabled_skills: string[]; disabled_skills: string[] }> {
  const res = await apiFetch('/skills/session/bind', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ session_id: sessionId, enabled_skills: enabledSkills, disabled_skills: disabledSkills }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '保存会话技能失败'))
  return res.json()
}

export async function apiStopChatStream(..._args: any[]): Promise<any> {
  const [token, responseId] = _args as [string, string]
  if (!token || !responseId || responseId.startsWith('c_')) return { ok: true }
  return apiCancelResponse(token, responseId)
}

export async function apiCreateMemory(token: string, payload: any): Promise<any> {
  const res = await apiFetchResponses('/memories', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error('Failed to create memory')
  return res.json()
}

export async function apiListMemories(token: string, memoryType?: string): Promise<MemoryItem[]> {
  const qs = memoryType ? `?memory_type=${encodeURIComponent(memoryType)}` : ''
  const res = await apiFetchResponses(`/memories${qs}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to list memories')
  const data = await res.json()
  return Array.isArray(data) ? data : (data.items || [])
}

export async function apiDeleteMemory(token: string, id: string): Promise<void> {
  const res = await apiFetchResponses(`/memories/${id}`, { method: 'DELETE', headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to delete memory')
}

export async function apiUpdateMemory(token: string, id: string, payload: any): Promise<any> {
  const res = await apiFetchResponses(`/memories/${id}`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error('Failed to update memory')
  return res.json()
}

export async function apiGetMemorySettings(token: string): Promise<MemorySettings> {
  const res = await apiFetchResponses('/memories/settings', { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to get memory settings')
  return res.json()
}

export async function apiSetMemorySettings(token: string, payload: Partial<MemorySettings>): Promise<MemorySettings> {
  const res = await apiFetchResponses('/memories/settings', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error('Failed to set memory settings')
  return res.json()
}

export interface MemoryCandidateItem {
  id: string
  content: string
  kind: string
  scope_type: 'user' | 'project' | 'conversation'
  scope_id?: string | null
  confidence: number
  salience: number
  response_id: string
  evidence?: { item_id?: string | null; excerpt: string } | null
}

export async function apiListMemoryInbox(token: string): Promise<MemoryCandidateItem[]> {
  const res = await apiFetchResponses('/memories/inbox', { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取记忆收件箱失败'))
  return (await res.json()).items ?? []
}

export async function apiResolveMemoryCandidate(token: string, candidateId: string, approved: boolean, content?: string): Promise<any> {
  const res = await apiFetchResponses(`/memories/inbox/${encodeURIComponent(candidateId)}/resolve`, { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ approved, content }) })
  if (!res.ok) throw new Error(await readApiError(res, '处理记忆候选失败'))
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
  pinned?: boolean
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
    xhr.open('POST', `${RESPONSES_BASE}/files`)

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
  const res = await fetch(`${RESPONSES_BASE}/files/${sessionId}`, {
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
  const res = await fetch(`${RESPONSES_BASE}/files/${attachmentId}`, {
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
  const res = await fetch(`${RESPONSES_BASE}/files/${attachmentId}/promote?publish_policy=${publishPolicy}`, {
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
