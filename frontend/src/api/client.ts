// API client — all backend calls go through here
import { normalizeFinalAnswerEnvelope, type TurnMetaEnvelope } from '../utils/streamEnvelope'
import { DEFAULT_TIMEZONE } from '../utils/timezone'
import {
  streamSseResponse,
  trackResponseStream,
  type ApprovalRequest,
  type ReasoningStep,
  type ResponseStreamCallbacks,
} from './responseStream'
import { apiFetch, apiFetchResponses, authHeaders, RESPONSES_BASE } from './transport'

export type { TurnMetaEnvelope }
export { streamSseResponse }
export type {
  ApprovalRequest,
  ReasoningStage,
  ReasoningStatus,
  ReasoningStep,
  ToolRunStatus,
} from './responseStream'

export interface CompanyProfileItem {
  bound: boolean
  id: string | null
  legal_name: string
  short_name: string
  brand_name: string
  description: string
  current_version_id?: string | null
  last_maintenance_at?: string | null
}

export type CompanyBrainFolder = '文化' | '行政' | '前端' | '后端' | '产品' | '客服' | '财务' | '数据'
export type CompanyBrainTier = 'long' | 'medium' | 'short'

export interface CompanyBrainFolderItem {
  name: CompanyBrainFolder
  default_tier?: CompanyBrainTier
  source_count: number
  ready_count: number
  review_count?: number
}

export interface CompanyBrainSourceItem {
  id: string
  company_id: string
  folder: CompanyBrainFolder
  memory_tier: CompanyBrainTier
  source_type: 'manual' | 'upload' | 'conversation'
  title: string
  processed_content: string
  source_content?: string
  source_preview?: string
  status: 'pending' | 'processing' | 'retry' | 'review' | 'ready' | 'rebuild' | 'inactive' | 'error'
  active: boolean
  salience: number
  processing_attempts: number
  error_message?: string | null
  quality_issue?: string | null
  processed_at?: string | null
  created_at?: string | null
}

export interface CompanyBrainVersionItem {
  id: string
  company_id: string
  version: number
  status: 'draft' | 'published' | 'superseded'
  content: string
  char_count: number
  long_term_chars: number
  medium_term_chars: number
  short_term_chars: number
  source_ids: string[]
  trigger: string
  change_summary: string
  published_at?: string | null
  created_at?: string | null
  target_ratios: { long: number; medium: number; short: number }
  limits: { hard: number; compression_threshold: number; maintenance_target: number }
}

export interface CompanyBrainSnapshot {
  profile: CompanyProfileItem
  folders: CompanyBrainFolderItem[]
  published: CompanyBrainVersionItem | null
  draft: CompanyBrainVersionItem | null
}

export async function apiGetCompanyProfile(): Promise<CompanyProfileItem> {
  const res = await apiFetchResponses('/company/profile')
  if (!res.ok) throw new Error(await readApiError(res, '读取公司品牌失败'))
  return res.json()
}

export async function apiBindCompany(token: string, payload: {
  legal_name: string
  short_name: string
  description?: string
}): Promise<CompanyProfileItem> {
  const res = await apiFetchResponses('/admin/company/profile', { method: 'PUT', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, '绑定公司失败'))
  return res.json()
}

export async function apiGetCompanyBrain(token: string): Promise<CompanyBrainSnapshot> {
  const res = await apiFetchResponses('/company/brain', { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取企业大脑失败'))
  return res.json()
}

export async function apiListCompanyBrainSources(token: string, folder?: CompanyBrainFolder): Promise<CompanyBrainSourceItem[]> {
  const params = folder ? `?folder=${encodeURIComponent(folder)}` : ''
  const res = await apiFetchResponses(`/admin/company/brain/sources${params}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取企业大脑来源失败'))
  return (await res.json()).items ?? []
}

export async function apiCreateCompanyBrainManualSource(token: string, payload: {
  folder: CompanyBrainFolder
  title: string
  content: string
  memory_tier: 'auto' | CompanyBrainTier
  salience?: number
}): Promise<CompanyBrainSourceItem> {
  const res = await apiFetchResponses('/admin/company/brain/sources/manual', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, '录入企业大脑信息失败'))
  return res.json()
}

export async function apiUploadCompanyBrainSource(token: string, payload: {
  folder: CompanyBrainFolder
  memory_tier: 'auto' | CompanyBrainTier
  file: File
  title?: string
}): Promise<CompanyBrainSourceItem> {
  const body = new FormData()
  body.append('folder', payload.folder)
  body.append('memory_tier', payload.memory_tier)
  body.append('file', payload.file)
  if (payload.title) body.append('title', payload.title)
  const res = await apiFetchResponses('/admin/company/brain/sources/upload', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body })
  if (!res.ok) throw new Error(await readApiError(res, '上传企业大脑文档失败'))
  return res.json()
}

export async function apiDeactivateCompanyBrainSource(token: string, sourceId: string): Promise<void> {
  const res = await apiFetchResponses(`/admin/company/brain/sources/${encodeURIComponent(sourceId)}`, { method: 'DELETE', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '停用企业大脑来源失败'))
}

export async function apiApproveCompanyBrainSource(token: string, sourceId: string): Promise<CompanyBrainSourceItem> {
  const res = await apiFetchResponses(`/admin/company/brain/sources/${encodeURIComponent(sourceId)}/approve`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '审核企业大脑候选失败'))
  return res.json()
}

export async function apiRetryCompanyBrainSource(token: string, sourceId: string): Promise<CompanyBrainSourceItem> {
  const res = await apiFetchResponses(`/admin/company/brain/sources/${encodeURIComponent(sourceId)}/retry`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '重新处理企业大脑来源失败'))
  return res.json()
}

export async function apiSaveCompanyBrainDraft(token: string, content: string, changeSummary: string): Promise<CompanyBrainVersionItem> {
  const res = await apiFetchResponses('/admin/company/brain/draft', { method: 'PUT', headers: authHeaders(token), body: JSON.stringify({ content, change_summary: changeSummary }) })
  if (!res.ok) throw new Error(await readApiError(res, '保存 COMPANY.md 草稿失败'))
  return res.json()
}

export async function apiPublishCompanyBrainDraft(token: string, versionId?: string): Promise<CompanyBrainVersionItem> {
  const res = await apiFetchResponses('/admin/company/brain/publish', { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ version_id: versionId || null }) })
  if (!res.ok) throw new Error(await readApiError(res, '发布 COMPANY.md 失败'))
  return res.json()
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
  conversation_id?: string
  role: string
  content: string
  created_at?: string
  response_id?: string
  parent_response_id?: string | null
  version_index?: number
  sibling_count?: number
  status?: ResponseStatus | 'streaming' | 'interrupted'
  approvals?: ApprovalRequest[]
}

export interface MemorySettings {
  memory_learning_enabled: boolean
  preference_learning_enabled: boolean
}

type ApiErr = { code?: number; message?: string; detail?: string }

async function readApiError(res: Response, fallback: string): Promise<string> {
  const err = (await res.json().catch(() => ({}))) as ApiErr
  if (res.status === 413) return '上传内容超过服务允许的大小，请压缩或拆分后重试'
  return err.message || err.detail || fallback
}

export type ResponseStatus = 'queued' | 'in_progress' | 'requires_action' | 'completed' | 'failed' | 'incomplete' | 'cancelled'

export interface ResponseOutputItem {
  id: string
  type: 'input_message' | 'message' | 'reasoning' | 'agent_plan' | 'function_call' | 'function_call_output' | 'approval_request' | 'citation' | 'error'
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
  project_id?: string | null
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

export async function apiListDocuments(token: string, projectId?: string | null): Promise<DocumentOut[]> {
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
  const res = await apiFetch(`/documents${query}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to list documents')
  return res.json()
}

export async function apiUploadDocument(
  token: string,
  file: File,
  options?: { title?: string; chunk_strategy?: number; project_id?: string | null; knowledge_space_id?: string | null; classification?: 'public' | 'internal' | 'confidential' | 'restricted'; publish_policy?: 'auto' | 'review' }
): Promise<DocumentOut> {
  const form = new FormData()
  form.append('file', file)
  if (options?.title) form.append('title', options.title)
  if (options?.chunk_strategy) form.append('chunk_strategy', String(options.chunk_strategy))
  if (options?.project_id) form.append('project_id', options.project_id)
  if (options?.knowledge_space_id) form.append('knowledge_space_id', options.knowledge_space_id)
  if (options?.classification) form.append('classification', options.classification)
  if (options?.publish_policy) form.append('publish_policy', options.publish_policy)
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

export interface KnowledgeSpaceItem {
  id: string
  name: string
  slug: string
  description: string
  space_type: 'company' | 'department' | 'role' | 'project' | 'personal'
  visibility: 'private' | 'members' | 'tenant'
  classification: 'public' | 'internal' | 'confidential' | 'restricted'
  publish_policy: 'auto' | 'review'
  review_cycle_days: number
  status: string
  role: 'viewer' | 'contributor' | 'reviewer' | 'publisher' | 'admin'
  metadata?: Record<string, unknown>
}

export interface EnterpriseKnowledgeSourceItem {
  id: string
  title: string
  source_type: string
  source_system?: string | null
  classification: string
  authority: string
  status: string
  sync_status: string
  active_version_id?: string | null
  effective_from?: string | null
  effective_to?: string | null
  review_due_at?: string | null
  updated_at?: string | null
}

export interface EnterpriseKnowledgeAssetItem {
  id: string
  source_id: string
  source_version_id: string
  title: string
  page_type: string
  summary?: string | null
  authority: string
  confidence: number
  classification: string
  review_due_at?: string | null
}

export interface EnterpriseKnowledgeEvidence {
  id: string
  source_type: string
  title: string
  text: string
  score: number
  source_id?: string | null
  source_version_id?: string | null
  document_id?: string | null
  claim_id?: string | null
  knowledge_page_id?: string | null
  authority?: string | null
  classification?: string | null
  source_system?: string | null
  sync_status?: string | null
  effective_from?: string | null
  effective_to?: string | null
  review_due_at?: string | null
  disclosure_stage?: string
  provenance?: Record<string, unknown>
}

export type KnowledgeFeedbackType = 'helpful' | 'unhelpful' | 'incorrect' | 'outdated' | 'correction'

export interface KnowledgeFeedbackItem {
  id: string
  target_type: string
  target_id: string
  feedback_type: string
  score?: number | null
  correction?: string | null
  applied: boolean
  user_id: string
  source_id: string
  source_title: string
  space_id?: string | null
  source_version_id?: string | null
  metadata: Record<string, unknown>
  created_at?: string | null
}

export interface KnowledgeGovernanceHealth {
  score: number
  status: 'healthy' | 'attention' | 'critical'
  scope: { space_id?: string | null; space_count: number }
  metrics: {
    sources?: number
    published_sources?: number
    due_reviews?: number
    expired_sources?: number
    pending_reviews?: number
    blocked_reviews?: number
    failed_jobs?: number
    stale_sources?: number
    open_lint_issues?: number
    open_lint_errors?: number
    unresolved_feedback?: number
    open_merge_cases?: number
    failed_connectors?: number
    stale_connectors?: number
  }
}

export interface KnowledgeLintIssueItem {
  id: string
  severity: string
  code: string
  resource_type: string
  resource_id: string
  message: string
  status: string
  details: Record<string, unknown>
}

export interface KnowledgeMergeCandidateItem {
  id: string
  text: string
  page_id: string
  page_title: string
  source_id: string
  source_title: string
  authority: string
  confidence: number
}

export interface KnowledgeMergeCaseItem {
  id: string
  entity_key: string
  conflict_type: string
  candidate_ids: string[]
  candidates: KnowledgeMergeCandidateItem[]
  status: string
  resolution: Record<string, unknown>
}

export interface KnowledgeSpaceMemberItem {
  id: string
  subject_type: 'user' | 'department' | 'group' | 'role' | 'project'
  subject_id: string
  role: 'viewer' | 'contributor' | 'reviewer' | 'publisher' | 'admin'
  expires_at?: string | null
}

export interface EnterpriseKnowledgeConnectorItem {
  id: string
  space_id: string
  name: string
  connector_type: string
  status: string
  sync_cursor?: string | null
  last_sync_at?: string | null
  last_error?: string | null
}

export interface KnowledgeSyncRunItem {
  id: string
  connector_id: string
  connector_name: string
  status: 'pending' | 'running' | 'succeeded' | 'failed'
  cursor_before?: string | null
  cursor_after?: string | null
  stats: {
    queued?: number
    running?: number
    succeeded?: number
    failed?: number
    created?: number
    updated?: number
    unchanged?: number
    deleted?: number
  }
  error?: string | null
  started_at?: string | null
  completed_at?: string | null
}

export interface KnowledgeSyncItem {
  id: string
  external_id: string
  title: string
  deleted: boolean
  status: 'pending' | 'running' | 'succeeded' | 'failed'
  attempts: number
  document_id?: string | null
  source_id?: string | null
  error?: string | null
  started_at?: string | null
  completed_at?: string | null
}

export interface KnowledgeReviewItem {
  id: string
  source_id: string
  source_title: string
  source_version_id: string
  version_number: number
  space_id?: string | null
  status: string
  required_role: string
  requested_by?: string | null
  assigned_to?: string | null
  review_reason?: string | null
  review_due_at?: string | null
  classification?: string | null
  authority?: string | null
  source_system?: string | null
  diff_summary: Record<string, unknown>
  created_at?: string | null
}

export interface KnowledgeSourceItem {
  id: string
  document_id?: string | null
  project_id?: string | null
  space_id?: string | null
  title: string
  source_type: string
  source_system?: string | null
  authority: string
  classification?: string | null
  status: string
  sync_status?: string | null
  active_version_id?: string | null
  review_due_at?: string | null
  updated_at?: string | null
}

export interface KnowledgePageItem {
  id: string
  source_id: string
  source_version_id?: string
  version_number?: number
  title: string
  type: string
  summary?: string | null
  authority: string
  status: string
  metadata?: Record<string, unknown>
}

export interface KnowledgeJobItem {
  id: string
  source_id: string
  status: string
  project_id?: string | null
  error?: string | null
  result?: Record<string, unknown>
  created_at?: string | null
  completed_at?: string | null
}

export interface KnowledgeGraphNode {
  id: string
  label: string
  type: string
  page_type?: string
  document_id?: string | null
}

export interface KnowledgeGraphEdge {
  id: string
  source: string
  target: string
  type: string
  confidence?: number
}

export interface KnowledgeGraphData {
  network: 'entity' | 'dependency' | 'provenance'
  project_id?: string | null
  nodes: KnowledgeGraphNode[]
  edges: KnowledgeGraphEdge[]
}

function projectQuery(projectId?: string | null, extra?: Record<string, string>): string {
  const params = new URLSearchParams(extra || {})
  if (projectId) params.set('project_id', projectId)
  const value = params.toString()
  return value ? `?${value}` : ''
}

export async function apiListKnowledgeSpaces(token: string): Promise<KnowledgeSpaceItem[]> {
  const res = await apiFetch('/knowledge/spaces', { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取知识空间失败'))
  return (await res.json()).items ?? []
}

export async function apiCreateKnowledgeSpace(token: string, payload: Record<string, unknown>): Promise<{ id: string; slug: string; role: string }> {
  const res = await apiFetch('/knowledge/spaces', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, '创建知识空间失败'))
  return res.json()
}

export async function apiListKnowledgeSpaceMembers(token: string, spaceId: string): Promise<KnowledgeSpaceMemberItem[]> {
  const res = await apiFetch(`/knowledge/spaces/${encodeURIComponent(spaceId)}/members`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取知识空间成员失败'))
  return (await res.json()).items ?? []
}

export async function apiGrantKnowledgeSpaceMember(token: string, spaceId: string, payload: Omit<KnowledgeSpaceMemberItem, 'id'>): Promise<{ id: string; role: string }> {
  const res = await apiFetch(`/knowledge/spaces/${encodeURIComponent(spaceId)}/members`, { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, '授权知识空间失败'))
  return res.json()
}

export async function apiRevokeKnowledgeSpaceMember(token: string, spaceId: string, memberId: string): Promise<void> {
  const res = await apiFetch(`/knowledge/spaces/${encodeURIComponent(spaceId)}/members/${encodeURIComponent(memberId)}`, { method: 'DELETE', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '撤销知识空间授权失败'))
}

export async function apiListEnterpriseKnowledgeConnectors(token: string, spaceId?: string): Promise<EnterpriseKnowledgeConnectorItem[]> {
  const query = spaceId ? `?space_id=${encodeURIComponent(spaceId)}` : ''
  const res = await apiFetch(`/knowledge/connectors${query}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取知识连接器失败'))
  return (await res.json()).items ?? []
}

export async function apiCreateEnterpriseKnowledgeConnector(token: string, payload: Record<string, unknown>): Promise<{ id: string; status: string }> {
  const res = await apiFetch('/knowledge/connectors', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, '创建知识连接器失败'))
  return res.json()
}

export async function apiSyncDingTalkKnowledgeConnector(token: string, connectorId: string): Promise<{ queued: number; documents: number; chats: number; departments: number; memberships: number }> {
  const res = await apiFetch(`/knowledge/connectors/${encodeURIComponent(connectorId)}/sync-dingtalk`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ include_documents: true, include_chats: true, include_directory: true }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '同步钉钉企业数据失败'))
  return res.json()
}

export async function apiListKnowledgeSyncRuns(token: string, connectorId?: string, spaceId?: string): Promise<KnowledgeSyncRunItem[]> {
  const params = new URLSearchParams()
  if (connectorId) params.set('connector_id', connectorId)
  if (spaceId) params.set('space_id', spaceId)
  const query = params.size ? `?${params.toString()}` : ''
  const res = await apiFetch(`/knowledge/sync-runs${query}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取连接器同步记录失败'))
  return (await res.json()).items ?? []
}

export async function apiListKnowledgeSyncRunItems(token: string, runId: string): Promise<KnowledgeSyncItem[]> {
  const res = await apiFetch(`/knowledge/sync-runs/${encodeURIComponent(runId)}/items`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取同步明细失败'))
  return (await res.json()).items ?? []
}

export async function apiRetryKnowledgeSyncRun(token: string, runId: string): Promise<{ run_id: string; requeued: number; status: string }> {
  const res = await apiFetch(`/knowledge/sync-runs/${encodeURIComponent(runId)}/retry`, {
    method: 'POST',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '重试同步失败项失败'))
  return res.json()
}

export async function apiListKnowledgeSpaceSources(token: string, spaceId: string): Promise<EnterpriseKnowledgeSourceItem[]> {
  const res = await apiFetch(`/knowledge/spaces/${encodeURIComponent(spaceId)}/sources`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取空间知识源失败'))
  return (await res.json()).items ?? []
}

export async function apiListKnowledgeSpaceAssets(token: string, spaceId: string): Promise<EnterpriseKnowledgeAssetItem[]> {
  const res = await apiFetch(`/knowledge/spaces/${encodeURIComponent(spaceId)}/assets`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取知识资产失败'))
  return (await res.json()).items ?? []
}

export async function apiSearchEnterpriseKnowledge(token: string, query: string, projectId?: string | null, spaceId?: string | null, topK = 8): Promise<EnterpriseKnowledgeEvidence[]> {
  const res = await apiFetch('/knowledge/search', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ query, project_id: projectId || null, space_id: spaceId || null, top_k: topK }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '企业知识检索失败'))
  return (await res.json()).items ?? []
}

export async function apiListKnowledgeReviews(token: string, status = 'pending', spaceId?: string | null): Promise<KnowledgeReviewItem[]> {
  const params = new URLSearchParams({ status })
  if (spaceId) params.set('space_id', spaceId)
  const res = await apiFetch(`/knowledge/reviews?${params.toString()}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取知识审核任务失败'))
  return (await res.json()).items ?? []
}

export async function apiDecideKnowledgeReview(token: string, reviewId: string, decision: 'approve' | 'reject', comment = ''): Promise<Record<string, unknown>> {
  const res = await apiFetch(`/knowledge/reviews/${encodeURIComponent(reviewId)}/decision`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ decision, comment }),
  })
  if (!res.ok) throw new Error(await readApiError(res, decision === 'approve' ? '发布知识失败' : '驳回知识失败'))
  return res.json()
}

export async function apiReconcileDueKnowledgeReviews(token: string, spaceId?: string | null): Promise<{ scanned: number; reopened: number; already_pending: number; blocked: number }> {
  const query = spaceId ? `?space_id=${encodeURIComponent(spaceId)}` : ''
  const res = await apiFetch(`/knowledge/reviews/reconcile-due${query}`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '扫描到期复审失败'))
  return res.json()
}

export async function apiSubmitKnowledgeFeedback(
  token: string,
  payload: { target_type: string; target_id: string; feedback_type: KnowledgeFeedbackType; correction?: string | null; score?: number | null },
): Promise<{ accepted: boolean; feedback_id: string }> {
  const res = await apiFetch('/knowledge/feedback', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, '提交知识反馈失败'))
  return res.json()
}

export async function apiListKnowledgeFeedback(token: string, spaceId?: string | null, applied = false): Promise<KnowledgeFeedbackItem[]> {
  const params = new URLSearchParams({ applied: String(applied), actionable_only: 'true', limit: '200' })
  if (spaceId) params.set('space_id', spaceId)
  const res = await apiFetch(`/knowledge/feedback?${params.toString()}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取知识反馈失败'))
  return (await res.json()).items ?? []
}

export async function apiResolveKnowledgeFeedback(token: string, feedbackId: string, resolution: 'acknowledged' | 'needs_revision' | 'corrected' | 'dismissed', comment = ''): Promise<Record<string, unknown>> {
  const res = await apiFetch(`/knowledge/feedback/${encodeURIComponent(feedbackId)}/resolve`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ resolution, comment }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '处理知识反馈失败'))
  return res.json()
}

export async function apiGetKnowledgeGovernanceHealth(token: string, spaceId?: string | null): Promise<KnowledgeGovernanceHealth> {
  const query = spaceId ? `?space_id=${encodeURIComponent(spaceId)}` : ''
  const res = await apiFetch(`/knowledge/governance/health${query}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取知识治理健康度失败'))
  return res.json()
}

export async function apiRunKnowledgeLint(token: string, spaceId?: string | null): Promise<{ open_count: number; findings: Array<Record<string, unknown>> }> {
  const query = spaceId ? `?space_id=${encodeURIComponent(spaceId)}` : ''
  const res = await apiFetch(`/knowledge/lint${query}`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '执行知识质量检查失败'))
  return res.json()
}

export async function apiListKnowledgeLintIssues(token: string, status = 'open', spaceId?: string | null): Promise<KnowledgeLintIssueItem[]> {
  const params = new URLSearchParams({ status })
  if (spaceId) params.set('space_id', spaceId)
  const res = await apiFetch(`/knowledge/lint/issues?${params.toString()}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取知识质量问题失败'))
  return res.json()
}

export async function apiListKnowledgeMergeCases(token: string, status = 'open', spaceId?: string | null): Promise<KnowledgeMergeCaseItem[]> {
  const params = new URLSearchParams({ status })
  if (spaceId) params.set('space_id', spaceId)
  const res = await apiFetch(`/knowledge/merge-cases?${params.toString()}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取知识冲突失败'))
  return res.json()
}

export async function apiResolveKnowledgeMergeCase(token: string, caseId: string, resolution: Record<string, unknown>, spaceId?: string | null): Promise<Record<string, unknown>> {
  const query = spaceId ? `?space_id=${encodeURIComponent(spaceId)}` : ''
  const res = await apiFetch(`/knowledge/merge-cases/${encodeURIComponent(caseId)}/resolve${query}`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(resolution),
  })
  if (!res.ok) throw new Error(await readApiError(res, '处理知识冲突失败'))
  return res.json()
}

export async function apiWithdrawKnowledgeSource(token: string, sourceId: string, reason: string): Promise<Record<string, unknown>> {
  const res = await apiFetch(`/knowledge/sources/${encodeURIComponent(sourceId)}/withdraw`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ reason }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '撤回知识来源失败'))
  return res.json()
}

export async function apiListKnowledgeSources(
  token: string,
  options?: { projectId?: string | null; spaceId?: string | null; status?: string | null },
): Promise<KnowledgeSourceItem[]> {
  const query = new URLSearchParams()
  if (options?.projectId) query.set('project_id', options.projectId)
  if (options?.spaceId) query.set('space_id', options.spaceId)
  if (options?.status) query.set('status', options.status)
  const suffix = query.size ? `?${query.toString()}` : ''
  const res = await apiFetch(`/knowledge/sources${suffix}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取知识源失败'))
  return res.json()
}

export async function apiListKnowledgePages(
  token: string,
  projectId?: string | null,
  status: 'published' | 'review' = 'published',
): Promise<KnowledgePageItem[]> {
  const res = await apiFetch(`/knowledge/pages${projectQuery(projectId, { limit: '200', status })}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取知识页面失败'))
  return res.json()
}

export async function apiListKnowledgeJobs(token: string, projectId?: string | null): Promise<KnowledgeJobItem[]> {
  const res = await apiFetch(`/knowledge/jobs${projectQuery(projectId, { limit: '100' })}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取编排任务失败'))
  return res.json()
}

export async function apiGetKnowledgeGraph(
  token: string,
  network: KnowledgeGraphData['network'],
  projectId?: string | null,
): Promise<KnowledgeGraphData> {
  const res = await apiFetch(`/knowledge/graph${projectQuery(projectId, { network })}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取知识网络失败'))
  return res.json()
}

export async function apiOrchestrateKnowledge(token: string, projectId?: string | null): Promise<Record<string, unknown>> {
  const res = await apiFetch(`/knowledge/orchestrate${projectQuery(projectId)}`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '启动知识编排失败'))
  return res.json()
}

export interface KnowledgeRuleItem {
  id: string
  rule_key: string
  version: number
  status: string
  project_id?: string | null
  schema: Record<string, unknown>
  instructions?: string | null
}

export async function apiListKnowledgeRules(token: string, projectId?: string | null): Promise<KnowledgeRuleItem[]> {
  const res = await apiFetch(`/knowledge/rules${projectQuery(projectId)}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取编排规则失败'))
  return res.json()
}

export async function apiCreateKnowledgeRule(token: string, payload: Record<string, unknown>): Promise<any> {
  const res = await apiFetch('/knowledge/rules', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, '保存编排规则失败'))
  return res.json()
}

export async function apiApproveKnowledgeRule(token: string, ruleId: string): Promise<any> {
  const res = await apiFetch(`/knowledge/rules/${encodeURIComponent(ruleId)}/approve`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '发布编排规则失败'))
  return res.json()
}

export async function apiPublishKnowledgePage(token: string, pageId: string): Promise<Record<string, unknown>> {
  const res = await apiFetch(`/knowledge/pages/${encodeURIComponent(pageId)}/publish`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '发布知识版本失败'))
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

export async function apiChangePassword(token: string, oldPassword: string, newPassword: string): Promise<{ message: string }> {
  const res = await apiFetch('/auth/change-password', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '修改密码失败'))
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

export async function apiResetUserPassword(token: string, userId: string, newPassword: string): Promise<{ message: string }> {
  const res = await apiFetch(`/admin/users/${encodeURIComponent(userId)}/reset-password`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ new_password: newPassword }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '重置用户密码失败'))
  return res.json()
}

export interface MemoryConstitutionRules {
  prohibited_categories: string[]
  allowed_proactive_kinds: string[]
  custom_blocked_terms: string[]
  min_proactive_confidence: number
  proactive_activation_observations: number
  retention_days: number
  max_memory_chars: number
}

export interface MemoryConstitutionData {
  id: string | null
  version: number
  content: string
  rules: MemoryConstitutionRules
  created_by?: string | null
  created_at?: string | null
  immutable_categories: string[]
  editable_categories: Record<string, string>
  quarantined_count?: number
  effective_immediately?: boolean
  unchanged?: boolean
}

export interface MemoryConstitutionHistoryItem {
  id: string
  version: number
  is_active: boolean
  created_by: string
  created_at?: string | null
  summary: string
}

export interface MemoryConstitutionPreview {
  current_version: number
  proposed_version: number
  scanned_count: number
  would_quarantine_count: number
  scan_limited: boolean
  reason_counts: Record<string, number>
  category_counts: Record<string, number>
}

export interface MemoryConstitutionAuditItem {
  id: string
  subject_user_id?: string | null
  response_id?: string | null
  constitution_version: number
  decision: 'allow' | 'review' | 'block'
  reason_code: string
  categories: string[]
  source: string
  created_at?: string | null
}

export async function apiGetMemoryConstitution(token: string): Promise<MemoryConstitutionData> {
  const res = await apiFetch('/admin/memory/constitution', { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取记忆宪法失败'))
  return res.json()
}

export async function apiUpdateMemoryConstitution(
  token: string,
  payload: { content: string; rules: MemoryConstitutionRules; expected_version?: number },
): Promise<MemoryConstitutionData> {
  const res = await apiFetch('/admin/memory/constitution', {
    method: 'PUT',
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await readApiError(res, '发布记忆宪法失败'))
  return res.json()
}

export async function apiPreviewMemoryConstitution(
  token: string,
  payload: { content: string; rules: MemoryConstitutionRules; expected_version?: number },
): Promise<MemoryConstitutionPreview> {
  const res = await apiFetch('/admin/memory/constitution/preview', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await readApiError(res, '评估记忆宪法影响失败'))
  return res.json()
}

export async function apiListMemoryConstitutionHistory(
  token: string,
): Promise<MemoryConstitutionHistoryItem[]> {
  const res = await apiFetch('/admin/memory/constitution/history', {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '读取宪法版本失败'))
  return ((await res.json()).items ?? []) as MemoryConstitutionHistoryItem[]
}

export async function apiRestoreMemoryConstitution(
  token: string,
  version: number,
  expectedVersion: number,
): Promise<MemoryConstitutionData> {
  const res = await apiFetch(`/admin/memory/constitution/history/${version}/restore`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ expected_version: expectedVersion }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '恢复宪法版本失败'))
  return res.json()
}

export async function apiListMemoryConstitutionAudits(
  token: string,
  limit = 30,
): Promise<MemoryConstitutionAuditItem[]> {
  const res = await apiFetch(`/admin/memory/constitution/audits?limit=${limit}`, {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '读取宪法审计失败'))
  return ((await res.json()).items ?? []) as MemoryConstitutionAuditItem[]
}

export interface ChatConstitutionRules {
  enabled: boolean
  prohibited_categories: string[]
  custom_blocked_terms: string[]
  custom_allowed_terms: string[]
  block_message: string
  max_input_chars: number
}

export interface ChatConstitutionData {
  id: string | null
  version: number
  content: string
  rules: ChatConstitutionRules
  created_by?: string | null
  created_at?: string | null
  immutable_categories: string[]
  immutable_category_labels: Record<string, string>
  editable_categories: Record<string, string>
  effective_immediately?: boolean
  unchanged?: boolean
}

export interface ChatConstitutionPreview {
  current_version: number
  proposed_version: number
  decision: 'allow' | 'block'
  reason_code: string
  categories: string[]
  block_message: string
}

export interface ChatConstitutionHistoryItem {
  id: string
  version: number
  is_active: boolean
  created_by: string
  created_at?: string | null
  summary: string
}

export interface ChatConstitutionAuditItem {
  id: string
  subject_user_id?: string | null
  request_id?: string | null
  constitution_version: number
  decision: 'allow' | 'block'
  reason_code: string
  categories: string[]
  content_length: number
  source: string
  created_at?: string | null
}

export async function apiGetChatConstitution(token: string): Promise<ChatConstitutionData> {
  const res = await apiFetch('/admin/chat/constitution', { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取聊天宪法失败'))
  return res.json()
}

export async function apiUpdateChatConstitution(
  token: string,
  payload: { content: string; rules: ChatConstitutionRules; expected_version?: number },
): Promise<ChatConstitutionData> {
  const res = await apiFetch('/admin/chat/constitution', {
    method: 'PUT',
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await readApiError(res, '发布聊天宪法失败'))
  return res.json()
}

export async function apiPreviewChatConstitution(
  token: string,
  payload: {
    content: string
    rules: ChatConstitutionRules
    expected_version?: number
    sample_input: string
  },
): Promise<ChatConstitutionPreview> {
  const res = await apiFetch('/admin/chat/constitution/preview', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await readApiError(res, '测试聊天宪法判定失败'))
  return res.json()
}

export async function apiListChatConstitutionHistory(
  token: string,
): Promise<ChatConstitutionHistoryItem[]> {
  const res = await apiFetch('/admin/chat/constitution/history', {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '读取聊天宪法版本失败'))
  return ((await res.json()).items ?? []) as ChatConstitutionHistoryItem[]
}

export async function apiRestoreChatConstitution(
  token: string,
  version: number,
  expectedVersion: number,
): Promise<ChatConstitutionData> {
  const res = await apiFetch(`/admin/chat/constitution/history/${version}/restore`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ expected_version: expectedVersion }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '恢复聊天宪法版本失败'))
  return res.json()
}

export async function apiListChatConstitutionAudits(
  token: string,
  limit = 30,
): Promise<ChatConstitutionAuditItem[]> {
  const res = await apiFetch(`/admin/chat/constitution/audits?limit=${limit}`, {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '读取聊天宪法审计失败'))
  return ((await res.json()).items ?? []) as ChatConstitutionAuditItem[]
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

export async function apiGetMessages(
  token: string,
  conversationId: string,
  signal?: AbortSignal,
): Promise<MessageItem[]> {
  const res = await apiFetchResponses(`/conversations/${conversationId}/messages`, {
    headers: authHeaders(token),
    signal,
  })
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
  callbacks: ResponseStreamCallbacks = {},
  signal?: AbortSignal,
): Promise<void> {
  const res = await apiFetchResponses(`/responses/${encodeURIComponent(responseId)}?stream=true&starting_after=${startingAfter}`, {
    headers: authHeaders(token),
    signal,
  })
  if (!res.ok) throw new Error(await readApiError(res, '恢复响应失败'))
  await streamSseResponse(res, callbacks, signal)
}

export async function apiResumeResponseWithRetry(
  token: string,
  responseId: string,
  startingAfter = -1,
  callbacks: ResponseStreamCallbacks = {},
  signal?: AbortSignal,
): Promise<void> {
  const tracker = trackResponseStream(callbacks, startingAfter)
  try {
    await apiResumeResponse(token, responseId, tracker.cursor(), tracker.callbacks, signal)
  } catch (error) {
    if (signal?.aborted || tracker.lifecycle() !== 'active') throw error
    await apiResumeResponse(token, responseId, tracker.cursor(), tracker.callbacks, signal)
  }
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
  const result = await res.json().catch(() => null) as any
  if (!result || result.error || !['approved', 'rejected'].includes(String(result.status || ''))) {
    throw new Error(String(result?.error || '审批失败'))
  }
  if (String(result.status) === 'approved' && result.approved !== true) {
    throw new Error('审批状态不一致，请刷新后重试')
  }
  if (!result.approval_id || !Number.isFinite(Number(result.starting_after))) {
    throw new Error('审批响应不完整，请刷新后重试')
  }
  return result
}

export interface EnterpriseOperationsOverview {
  generated_at: string
  scope: { tenant_id: string; workspace_id: string }
  health: {
    score: number
    status: 'healthy' | 'attention' | 'critical'
    dimensions: { reliability: number; governance: number; knowledge: number; adoption: number }
  }
  adoption: { active_users_30d: number; active_goals: number; completed_goals: number; scheduled_tasks: number; active_alerts: number }
  responses: {
    total_24h: number
    completed_24h: number
    failed_24h: number
    requires_action_24h: number
    active_24h: number
    success_rate: number
    pending_approvals: number
    model_calls_24h: number
    prompt_tokens_24h: number
    completion_tokens_24h: number
    avg_latency_ms: number
    p95_latency_ms: number
  }
  assets: {
    data_sources: number
    active_data_sources: number
    knowledge_spaces: number
    knowledge_sources: number
    published_knowledge: number
    due_reviews: number
    stale_knowledge: number
    pending_reviews: number
    unresolved_feedback: number
    cognitive_entities: number
    published_cognition: number
    due_cognitive_reviews: number
  }
  directory: { principals: number; memberships: number; last_sync?: DirectorySyncRunItem | null }
  alerts: { unacknowledged: number; critical: number }
  model_usage: Array<{ model: string; calls: number; prompt_tokens: number; completion_tokens: number; avg_latency_ms: number }>
  risks: Array<{ code: string; severity: string; count: number; title: string; route: string }>
}

export interface DirectoryPrincipalItem {
  id: string
  principal_type: 'department' | 'group' | 'role'
  external_id: string
  display_name: string
  parent_external_id?: string | null
  source: 'manual' | 'scim' | 'hr'
  status: 'active' | 'inactive'
  attributes: Record<string, unknown>
  last_synced_at?: string | null
}

export interface DirectoryMembershipItem {
  id: string
  user_id: string
  user_email?: string | null
  display_name?: string | null
  principal_id: string
  principal_type?: 'department' | 'group' | 'role' | null
  principal_external_id?: string | null
  principal_name?: string | null
  source: 'manual' | 'scim' | 'hr'
  status: 'active' | 'inactive'
  effective_from?: string | null
  effective_to?: string | null
  metadata: Record<string, unknown>
}

export interface DirectorySyncRunItem {
  id: string
  provider: 'manual' | 'scim' | 'hr'
  status: string
  cursor?: string | null
  authoritative: boolean
  stats: Record<string, number>
  requested_by: string
  error?: string | null
  started_at?: string | null
  completed_at?: string | null
}

export interface DirectorySyncPayload {
  provider: 'manual' | 'scim' | 'hr'
  cursor?: string | null
  authoritative?: boolean
  principals: Array<{
    principal_type: 'department' | 'group' | 'role'
    external_id: string
    display_name: string
    parent_external_id?: string | null
    status?: 'active' | 'inactive'
    attributes?: Record<string, unknown>
  }>
  memberships: Array<{
    user_email: string
    principal_type: 'department' | 'group' | 'role'
    principal_external_id: string
    status?: 'active' | 'inactive'
    metadata?: Record<string, unknown>
  }>
}

export interface EnterpriseCognitiveVersionItem {
  id: string
  entity_id: string
  version: number
  status: 'draft' | 'published' | 'archived'
  classification: 'public' | 'internal' | 'confidential' | 'restricted'
  summary: string
  mission: string
  vision: string
  values: string[]
  responsibilities: string[]
  products_services: string[]
  operating_principles: string[]
  terminology: Record<string, string>
  key_contacts: string[]
  source_refs: string[]
  metadata: Record<string, unknown>
  effective_from?: string | null
  effective_to?: string | null
  review_due_at?: string | null
  published_at?: string | null
}

export interface EnterpriseCognitiveEntityItem {
  id: string
  entity_type: 'company' | 'department'
  entity_key: string
  display_name: string
  directory_principal_id?: string | null
  department_external_id?: string | null
  department_name?: string | null
  knowledge_space_id?: string | null
  knowledge_space_name?: string | null
  status: 'active' | 'archived'
  current_version?: EnterpriseCognitiveVersionItem | null
  draft_version?: EnterpriseCognitiveVersionItem | null
}

export interface EnterpriseCognitiveDraftPayload {
  classification: EnterpriseCognitiveVersionItem['classification']
  summary: string
  mission: string
  vision: string
  values: string[]
  responsibilities: string[]
  products_services: string[]
  operating_principles: string[]
  terminology: Record<string, string>
  key_contacts: string[]
  source_refs: string[]
  metadata?: Record<string, unknown>
  effective_from?: string | null
  effective_to?: string | null
  review_due_at?: string | null
}

export async function apiGetEnterpriseOperations(token: string): Promise<EnterpriseOperationsOverview> {
  const res = await apiFetch('/admin/enterprise/operations/overview', { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取企业运营中心失败'))
  return res.json()
}

export async function apiListDirectoryPrincipals(token: string): Promise<DirectoryPrincipalItem[]> {
  const res = await apiFetch('/admin/enterprise/directory/principals?limit=2000', { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取企业目录失败'))
  return (await res.json()).items ?? []
}

export async function apiListDirectoryMemberships(token: string): Promise<DirectoryMembershipItem[]> {
  const res = await apiFetch('/admin/enterprise/directory/memberships?limit=5000', { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取目录成员失败'))
  return (await res.json()).items ?? []
}

export async function apiListDirectorySyncRuns(token: string): Promise<DirectorySyncRunItem[]> {
  const res = await apiFetch('/admin/enterprise/directory/sync-runs?limit=50', { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取目录同步记录失败'))
  return (await res.json()).items ?? []
}

export async function apiSyncEnterpriseDirectory(token: string, payload: DirectorySyncPayload): Promise<DirectorySyncRunItem> {
  const res = await apiFetch('/admin/enterprise/directory/sync', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, '同步企业目录失败'))
  return res.json()
}

export async function apiListEnterpriseCognitiveEntities(token: string): Promise<EnterpriseCognitiveEntityItem[]> {
  const res = await apiFetch('/admin/enterprise/cognition/entities', { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取企业认知失败'))
  return (await res.json()).items ?? []
}

export async function apiUpsertEnterpriseCognitiveEntity(token: string, payload: {
  entity_type: 'company' | 'department'
  display_name: string
  department_external_id?: string | null
  knowledge_space_id?: string | null
}): Promise<EnterpriseCognitiveEntityItem> {
  const res = await apiFetch('/admin/enterprise/cognition/entities', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, '创建企业认知实体失败'))
  return res.json()
}

export async function apiSaveEnterpriseCognitiveDraft(token: string, entityId: string, payload: EnterpriseCognitiveDraftPayload): Promise<EnterpriseCognitiveVersionItem> {
  const res = await apiFetch(`/admin/enterprise/cognition/entities/${encodeURIComponent(entityId)}/draft`, { method: 'PUT', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, '保存企业认知草稿失败'))
  return res.json()
}

export async function apiPublishEnterpriseCognitiveDraft(token: string, entityId: string): Promise<EnterpriseCognitiveVersionItem> {
  const res = await apiFetch(`/admin/enterprise/cognition/entities/${encodeURIComponent(entityId)}/publish`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '发布企业认知失败'))
  return res.json()
}

export async function apiListEnterpriseCognitiveVersions(token: string, entityId: string): Promise<EnterpriseCognitiveVersionItem[]> {
  const res = await apiFetch(`/admin/enterprise/cognition/entities/${encodeURIComponent(entityId)}/versions`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取企业认知版本失败'))
  return (await res.json()).items ?? []
}

export async function apiArchiveEnterpriseCognitiveEntity(token: string, entityId: string): Promise<EnterpriseCognitiveEntityItem> {
  const res = await apiFetch(`/admin/enterprise/cognition/entities/${encodeURIComponent(entityId)}/archive`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '归档企业认知实体失败'))
  return res.json()
}

export interface WorkbenchAttentionItem {
  id: string
  type: 'approval' | 'alert' | 'response' | 'knowledge' | string
  severity: 'info' | 'warning' | 'critical' | 'error' | string
  title: string
  description: string
  route: string
  resource_id?: string | null
  created_at?: string | null
}

export interface WorkbenchActivityItem {
  id: string
  type: 'response' | 'goal' | string
  status: string
  title: string
  description: string
  route: string
  created_at?: string | null
}

export interface EnterpriseWorkbenchScenario {
  id: string
  category: string
  title: string
  description: string
  status: 'ready' | 'setup_required' | 'active'
  recommended: boolean
  launch_mode: 'chat' | 'goal' | 'skills'
  action_route: string
  action_label: string
  starter_prompt: string
  capabilities: string[]
  tools: string[]
  memory_scope: 'conversation' | 'user' | 'project'
  risk: 'read' | 'mixed' | 'write'
  approval_policy: 'none' | 'required_before_write' | 'inherited'
  approval_required: boolean
  evidence_requirements: string[]
  deliverables: string[]
  blockers: Array<{ code: string; title: string; description: string; route: string }>
}

export interface EnterpriseWorkbenchOverview {
  generated_at: string
  scope: { tenant_id: string; workspace_id: string; user_id: string }
  readiness: {
    score: number
    status: 'ready' | 'attention' | 'foundation'
    dimensions: { context: number; knowledge: number; data: number; automation: number; governance: number }
    blockers: Array<{ code: string; title: string; description: string; route: string }>
  }
  summary: {
    projects: number
    active_goals: number
    running_responses: number
    pending_approvals: number
    unread_notifications: number
    scheduled_tasks: number
    active_alerts: number
    unacknowledged_alerts: number
    accessible_data_sources: number
    knowledge_spaces: number
    published_knowledge: number
    installed_skills: number
    company_skills: number
    available_work_scenarios: number
    active_work_scenarios: number
    enterprise_cognitive_entities?: number
    company_context_ready?: boolean
  }
  knowledge_health: KnowledgeGovernanceHealth
  scenarios: EnterpriseWorkbenchScenario[]
  attention_items: WorkbenchAttentionItem[]
  recent_activity: WorkbenchActivityItem[]
}

export async function apiGetEnterpriseWorkbench(
  token: string,
  recentLimit = 6,
  attentionLimit?: number,
): Promise<EnterpriseWorkbenchOverview> {
  const query = new URLSearchParams({ recent_limit: String(recentLimit) })
  if (attentionLimit !== undefined) query.set('attention_limit', String(attentionLimit))
  const res = await apiFetchResponses(`/workbench/overview?${query.toString()}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取企业 AI 工作台失败'))
  return res.json()
}

export interface ProjectItem {
  id: string
  name: string
  description: string
  instructions: string
  memory_mode: 'default' | 'project_only'
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

export async function apiUpdateProject(token: string, projectId: string, payload: Omit<ProjectItem, 'id'>): Promise<ProjectItem> {
  const res = await apiFetchResponses(`/projects/${encodeURIComponent(projectId)}`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify(payload) })
  if (!res.ok) throw new Error(await readApiError(res, '更新 Project 失败'))
  return res.json()
}

export interface AssistantProfileItem {
  id: string
  name: string
  personality: 'none' | 'friendly' | 'pragmatic' | 'cute' | 'romantic' | 'funny'
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
  starts_at?: string | null
  ends_at?: string | null
  status: string
  next_run_at?: string | null
  last_run_at?: string | null
  requires_confirmation: boolean
}

export interface ScheduledTaskRunItem {
  id: string
  status: string
  response_id?: string | null
  scheduled_for?: string | null
  output?: string | null
  error?: string | null
}

export interface ScheduledTaskDetail extends ScheduledTaskItem {
  runs: ScheduledTaskRunItem[]
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

export interface ScheduledTaskPreview {
  rrule: string
  timezone: string
  starts_at?: string | null
  ends_at?: string | null
  next_run_at?: string | null
  next_run_times: string[]
}

export async function apiPreviewScheduledTaskRule(
  token: string,
  payload: { rrule: string; timezone: string; starts_at?: string | null; ends_at?: string | null; count?: number },
): Promise<ScheduledTaskPreview> {
  const res = await apiFetchResponses('/scheduled-tasks/preview', {
    method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await readApiError(res, '无法预览执行时间'))
  return res.json()
}

export async function apiScheduledTaskAction(token: string, taskId: string, action: 'enable' | 'pause' | 'cancel'): Promise<ScheduledTaskItem> {
  const res = await apiFetchResponses(`/scheduled-tasks/${encodeURIComponent(taskId)}/actions/${action}`, { method: 'POST', headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '更新定时任务失败'))
  return res.json()
}

export async function apiGetScheduledTask(token: string, taskId: string): Promise<ScheduledTaskDetail> {
  const res = await apiFetchResponses(`/scheduled-tasks/${encodeURIComponent(taskId)}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取任务运行历史失败'))
  return res.json()
}

export async function apiRunScheduledTask(token: string, taskId: string): Promise<ScheduledTaskRunItem> {
  const res = await apiFetchResponses(`/scheduled-tasks/${encodeURIComponent(taskId)}/run`, {
    method: 'POST', headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '立即运行任务失败'))
  return res.json()
}

export interface NotificationItem {
  id: string
  task_id: string
  run_id?: string | null
  kind: 'scheduled_task' | 'alert' | 'calendar'
  level: 'info' | 'success' | 'warning' | 'error' | string
  title: string
  body?: string | null
  read: boolean
  created_at?: string | null
}

export async function apiListNotifications(token: string, limit = 50): Promise<{ items: NotificationItem[]; unread_count: number }> {
  const res = await apiFetchResponses(`/notifications?limit=${limit}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取通知失败'))
  return res.json()
}

export async function apiReadNotification(token: string, notificationId: string): Promise<void> {
  const res = await apiFetchResponses(`/notifications/${encodeURIComponent(notificationId)}/read`, {
    method: 'POST', headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '更新通知失败'))
}

export async function apiReadAllNotifications(token: string): Promise<number> {
  const res = await apiFetchResponses('/notifications/read-all', {
    method: 'POST', headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '更新通知失败'))
  return Number((await res.json()).updated || 0)
}

export interface AlertRuleItem {
  id: string
  name: string
  question: string
  data_source_id: string
  project_id?: string | null
  metric_column?: string | null
  aggregation: 'first' | 'sum' | 'avg' | 'min' | 'max' | 'count'
  operator: 'gt' | 'gte' | 'lt' | 'lte' | 'eq' | 'neq' | 'change_pct_gt' | 'change_pct_lt'
  threshold: number
  severity: 'info' | 'warning' | 'critical'
  rrule: string
  timezone: string
  status: string
  cooldown_seconds: number
  last_value?: number | null
  last_state: string
  last_error?: string | null
  last_run_at?: string | null
  last_triggered_at?: string | null
  next_run_at?: string | null
}

export interface AlertEventItem {
  id: string
  rule_id: string
  state: 'triggered' | 'resolved'
  severity: 'info' | 'warning' | 'critical'
  value?: number | null
  threshold?: number | null
  summary: string
  evidence: Record<string, unknown>
  acknowledged_at?: string | null
  created_at?: string | null
}

export async function apiListAlertRules(token: string, projectId?: string): Promise<AlertRuleItem[]> {
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
  const res = await apiFetchResponses(`/alerts/rules${query}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取预警规则失败'))
  return (await res.json()).items ?? []
}

export async function apiCreateAlertRule(token: string, payload: Record<string, unknown>): Promise<AlertRuleItem> {
  const res = await apiFetchResponses('/alerts/rules', {
    method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await readApiError(res, '创建预警规则失败'))
  return res.json()
}

export async function apiAlertRuleAction(
  token: string,
  ruleId: string,
  action: 'enable' | 'pause' | 'cancel',
): Promise<AlertRuleItem> {
  const res = await apiFetchResponses(`/alerts/rules/${encodeURIComponent(ruleId)}/actions/${action}`, {
    method: 'POST', headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '更新预警规则失败'))
  return res.json()
}

export async function apiTestAlertRule(token: string, ruleId: string): Promise<Record<string, unknown>> {
  const res = await apiFetchResponses(`/alerts/rules/${encodeURIComponent(ruleId)}/test`, {
    method: 'POST', headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '测试预警规则失败'))
  return res.json()
}

export async function apiListAlertEvents(token: string, ruleId?: string): Promise<AlertEventItem[]> {
  const query = ruleId ? `?rule_id=${encodeURIComponent(ruleId)}` : ''
  const res = await apiFetchResponses(`/alerts/events${query}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取预警事件失败'))
  return (await res.json()).items ?? []
}

export async function apiAcknowledgeAlertEvent(token: string, eventId: string): Promise<void> {
  const res = await apiFetchResponses(`/alerts/events/${encodeURIComponent(eventId)}/acknowledge`, {
    method: 'POST', headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '确认预警事件失败'))
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
            ...(Array.isArray(payload?.enabled_skills) ? { enabled_skills: payload.enabled_skills } : {}),
            project_id: typeof payload?.project_id === 'string' ? payload.project_id : undefined,
            data_source_ids: Array.isArray(payload?.data_source_ids) ? payload.data_source_ids : [],
            assistant_profile_id: typeof payload?.assistant_profile_id === 'string' ? payload.assistant_profile_id : undefined,
            attachment_ids: Array.isArray(payload?.attachment_ids) ? payload.attachment_ids : [],
            timezone: typeof payload?.timezone === 'string' ? payload.timezone : DEFAULT_TIMEZONE,
          },
          ...(typeof payload?.model === 'string' && payload.model.trim() ? { model: payload.model.trim() } : {}),
        }),
      }),
      signal,
    })

    // 错误响应也通常是 JSON；必须先走统一错误解析，不能把它误当成空的最终回答。
    if (!res.ok) throw new Error(await readApiError(res, 'Responses stream failed'))

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
    const tracker = trackResponseStream({
      ...callbacks,
      onEvent: (event: { sequence_number?: number; type?: string; data?: any }) => {
        responseId = String(event.data?.response_id || event.data?.id || responseId || '') || responseId
        callbacks.onEvent?.(event)
      },
    })
    try {
      await streamSseResponse(res, tracker.callbacks, signal)
    } catch (streamError) {
      if (!signal?.aborted && tracker.lifecycle() === 'active' && responseId) {
        try {
          await apiResumeResponseWithRetry(
            token,
            responseId,
            tracker.cursor(),
            tracker.callbacks,
            signal,
          )
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

export interface MemoryGraph {
  nodes: Array<{ id: string; label: string; kind: string; scope_type: string; salience: number }>
  edges: Array<{ id: string; source: string; target: string; relation: string; weight: number }>
}

export async function apiGetMemoryGraph(token: string): Promise<MemoryGraph> {
  const res = await apiFetchResponses('/memories/graph', { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to load memory graph')
  return res.json()
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
  personal_category: PersonalMemoryCategory
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
export async function apiAnalyzeDatabase(token: string, id: string): Promise<any> { const res = await apiFetch(`/databases/${id}/analysis`, { method: 'POST', headers: authHeaders(token), body: '{}' }); if (!res.ok) throw new Error(await readApiError(res, '数据分析失败')); return res.json() }
export async function apiDatabaseQuery(token: string, id: string, query: any): Promise<any> { const res = await apiFetch(`/databases/${id}/query`, { method: 'POST', headers: authHeaders(token), body: JSON.stringify(query) }); if (!res.ok) throw new Error('Failed to query database'); return res.json() }
export async function apiGetDatabaseSchema(token: string, id: string): Promise<any> { const res = await apiFetch(`/databases/${id}/schema`, { headers: authHeaders(token) }); if (!res.ok) throw new Error('Failed to get database schema'); return res.json() }
export async function apiSyncDatabaseSchema(token: string, id: string): Promise<any> { const res = await apiFetch(`/databases/${id}/sync-schema`, { method: 'POST', headers: authHeaders(token) }); if (!res.ok) throw new Error('Failed to sync database schema'); return res.json() }
export async function apiTestDatabaseConnection(token: string, databaseId: string): Promise<any> { const res = await apiFetch(`/databases/${databaseId}/test-connection`, { method: 'POST', headers: authHeaders(token) }); if (!res.ok) throw new Error('Failed to test database connection'); return res.json() }
export async function apiGetDatabaseWorkbench(token: string, databaseId: string): Promise<any> { const res = await apiFetch(`/databases/${databaseId}/workbench`, { headers: authHeaders(token) }); if (!res.ok) throw new Error(await readApiError(res, '读取数据工作台失败')); return res.json() }
export async function apiValidateDatabase(token: string, databaseId: string): Promise<any> { const res = await apiFetch(`/databases/${databaseId}/validate`, { method: 'POST', headers: authHeaders(token) }); if (!res.ok) throw new Error(await readApiError(res, '数据源验证失败')); return res.json() }

export interface ResourcePermissionItem { id: string; subject_user_id: string; subject_email: string; permission: 'view' | 'query' | 'edit' | 'admin'; expires_at?: string | null }
export async function apiListPermissionSubjects(token: string): Promise<Array<{ id: string; email: string; display_name?: string }>> { const res = await apiFetch('/resource-permissions/subjects', { headers: authHeaders(token) }); if (!res.ok) throw new Error(await readApiError(res, '读取用户失败')); return (await res.json()).items ?? [] }
export async function apiListResourcePermissions(token: string, resourceType: string, resourceId: string): Promise<ResourcePermissionItem[]> { const p = new URLSearchParams({ resource_type: resourceType, resource_id: resourceId }); const res = await apiFetch(`/resource-permissions?${p}`, { headers: authHeaders(token) }); if (!res.ok) throw new Error(await readApiError(res, '读取资源权限失败')); return (await res.json()).items ?? [] }
export async function apiGrantResourcePermission(token: string, payload: Record<string, unknown>): Promise<any> { const res = await apiFetch('/resource-permissions', { method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload) }); if (!res.ok) throw new Error(await readApiError(res, '授权失败')); return res.json() }
export async function apiRevokeResourcePermission(token: string, id: string): Promise<any> { const res = await apiFetch(`/resource-permissions/${encodeURIComponent(id)}`, { method: 'DELETE', headers: authHeaders(token) }); if (!res.ok) throw new Error(await readApiError(res, '撤销授权失败')); return res.json() }

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
  topK = 6,
  projectId?: string | null,
): Promise<SearchResult[]> {
  const res = await apiFetch('/documents/search', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ query, top_k: topK, project_id: projectId || null }),
  })
  if (!res.ok) throw new Error(await readApiError(res, 'Search failed'))
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
  personal_category?: PersonalMemoryCategory
  enabled?: boolean
  pinned?: boolean
  access_count?: number
  tags?: string[]
  metadata?: Record<string, unknown>
}

export type PersonalMemoryCategory = 'terminology' | 'response_style' | 'approval_habit' | 'template' | 'calendar' | 'task' | 'profile'

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

export interface SkillCatalogItem {
  id: string
  name: string
  description: string
  version?: string | null
  github_owner: string
  github_repo: string
  github_stars: number
  download_count: number
  security_score?: number | null
  security_status: string
  ai_score?: number | null
  is_verified: boolean
  source_url: string
  installed: boolean
  installation_id?: string | null
  installed_skill_id?: string | null
  status: 'active' | 'disabled' | string
  platform_disabled: boolean
  platform_note?: string
}

export interface SkillCatalogSyncPolicy {
  sync_enabled: boolean
  sync_interval_seconds: number
  sync_retry_seconds: number
  catalog_size: number
  retention: 'append_only' | string
}

export interface EnterpriseSkillItem {
  id: string
  runtime_id: string
  name: string
  description: string
  value_summary: string
  instructions: string
  source_files: Array<{ path: string; sha256: string; size: number; content_type: string }>
  use_cases: string[]
  classification: 'public' | 'internal' | 'confidential'
  status: 'published' | 'archived'
  published_at?: string | null
  publication: 'company'
}

export async function apiListSkillCatalog(token: string, sort: 'popular' | 'recent', q = ''): Promise<SkillCatalogItem[]> { const p = new URLSearchParams({ sort, limit: '30' }); if (q.trim()) p.set('q', q.trim()); const res = await apiFetch(`/skills/catalog?${p}`, { headers: authHeaders(token) }); if (!res.ok) throw new Error(await readApiError(res, '读取 SkillHub 失败')); return (await res.json()).items ?? [] }
export async function apiListMyInstalledSkills(token: string): Promise<SkillCatalogItem[]> { const res = await apiFetch('/skills/installed/me', { headers: authHeaders(token) }); if (!res.ok) throw new Error(await readApiError(res, '读取账户 Skills 失败')); return (await res.json()).items ?? [] }
export async function apiListAdminSkillCatalog(token: string): Promise<{ items: SkillCatalogItem[]; policy: SkillCatalogSyncPolicy }> { const res = await apiFetch('/skills/catalog/admin?limit=500', { headers: authHeaders(token) }); if (!res.ok) throw new Error(await readApiError(res, '读取 Skill 治理目录失败')); return res.json() }
export async function apiSyncSkillCatalog(token: string): Promise<any> { const res = await apiFetch('/skills/catalog/sync', { method: 'POST', headers: authHeaders(token) }); if (!res.ok) throw new Error(await readApiError(res, '同步 SkillHub 失败')); return res.json() }
export async function apiSetCatalogSkillAvailability(token: string, catalogSkillId: string, enabled: boolean, reason = ''): Promise<SkillCatalogItem> { const res = await apiFetch(`/skills/catalog/${encodeURIComponent(catalogSkillId)}/availability`, { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify({ enabled, reason }) }); if (!res.ok) throw new Error(await readApiError(res, enabled ? '恢复 Skill 失败' : '暂停 Skill 失败')); return (await res.json()).item }
export async function apiInstallCatalogSkill(token: string, catalogSkillId: string): Promise<any> { const res = await apiFetch('/skills/catalog/install', { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ catalog_skill_id: catalogSkillId }) }); if (!res.ok) throw new Error(await readApiError(res, '安装 Skill 失败')); return res.json() }
export async function apiUninstallCatalogSkill(token: string, installationId: string): Promise<any> { const res = await apiFetch(`/skills/installations/${encodeURIComponent(installationId)}`, { method: 'DELETE', headers: authHeaders(token) }); if (!res.ok) throw new Error(await readApiError(res, '卸载 Skill 失败')); return res.json() }
export async function apiListCompanySkills(token: string): Promise<EnterpriseSkillItem[]> { const res = await apiFetch('/skills/company', { headers: authHeaders(token) }); if (!res.ok) throw new Error(await readApiError(res, '读取公司 Skills 失败')); return (await res.json()).items ?? [] }
export async function apiDistillCompanySkill(token: string, payload: { name: string; description: string; classification: EnterpriseSkillItem['classification']; files: File[]; paths: string[] }): Promise<{ skill: EnterpriseSkillItem; deduplicated: boolean }> {
  const form = new FormData()
  form.append('name', payload.name)
  form.append('description', payload.description)
  form.append('classification', payload.classification)
  payload.files.forEach((file, index) => { form.append('files', file); form.append('paths', payload.paths[index] || file.name) })
  const res = await apiFetch('/skills/company/distill', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form })
  if (!res.ok) throw new Error(await readApiError(res, '蒸馏企业 Skill 失败'))
  return res.json()
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
  if (!res.ok) throw new Error(await readApiError(res, '读取 Skills 失败'))
  const data = await res.json()
  return Array.isArray(data) ? data : data.items ?? []
}

export async function apiInstallSkill(token: string, gitUrl: string, ref: string): Promise<any> {
  const res = await apiFetch('/skills/install', { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ git_url: gitUrl, ref }) })
  if (!res.ok) throw new Error(await readApiError(res, '安装 Skill 失败'))
  return res.json()
}

export async function apiUninstallSkill(token: string, id: string): Promise<any> {
  const res = await apiFetch('/skills/uninstall', { method: 'POST', headers: authHeaders(token), body: JSON.stringify({ skill_id: id }) })
  if (!res.ok) throw new Error(await readApiError(res, '卸载 Skill 失败'))
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
  if (!res.ok) throw new Error(await readApiError(res, '创建 Skill 失败'))
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
  const res = await apiFetch('/users/ui-settings', { headers: authHeaders(token) })
  if (!res.ok) throw new Error('Failed to get UI settings')
  return res.json()
}

export async function apiPatchUiSettings(token: string, payload: any): Promise<any> {
  const res = await apiFetch('/users/ui-settings', { method: 'PATCH', headers: authHeaders(token), body: JSON.stringify(payload) })
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
  media_kind?: 'image' | 'audio' | 'video' | null
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
  media_kind?: 'image' | 'audio' | 'video' | null
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

export interface CalendarEventItem {
  id: string
  occurrence_id: string
  title: string
  description: string
  location: string
  event_type: 'event' | 'meeting' | 'focus' | 'reminder'
  start_at: string
  end_at: string
  local_start_at: string
  local_end_at: string
  timezone: string
  view_timezone: string
  all_day: boolean
  recurrence_rule?: string | null
  reminder_minutes: number[]
  status: string
  source: 'manual' | 'assistant' | string
  source_response_id?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface CalendarEventPayload {
  title: string
  description?: string
  location?: string
  event_type?: CalendarEventItem['event_type']
  start_at: string
  end_at: string
  timezone: string
  all_day?: boolean
  recurrence_rule?: string | null
  reminder_minutes?: number[]
}

export async function apiListCalendarEvents(
  token: string,
  start: string,
  end: string,
  timezone: string,
): Promise<CalendarEventItem[]> {
  const query = new URLSearchParams({ start, end, timezone, limit: '200' })
  const res = await apiFetchResponses(`/calendar/events?${query.toString()}`, { headers: authHeaders(token) })
  if (!res.ok) throw new Error(await readApiError(res, '读取日历失败'))
  return (await res.json()).items ?? []
}

export async function apiCreateCalendarEvent(
  token: string,
  payload: CalendarEventPayload,
): Promise<CalendarEventItem> {
  const res = await apiFetchResponses('/calendar/events', {
    method: 'POST', headers: authHeaders(token), body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await readApiError(res, '创建日程失败'))
  return res.json()
}

export async function apiUpdateCalendarEvent(
  token: string,
  eventId: string,
  payload: Partial<CalendarEventPayload>,
): Promise<CalendarEventItem> {
  const res = await apiFetchResponses(`/calendar/events/${encodeURIComponent(eventId)}`, {
    method: 'PATCH', headers: authHeaders(token), body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await readApiError(res, '更新日程失败'))
  return res.json()
}

export async function apiCancelCalendarEvent(token: string, eventId: string): Promise<void> {
  const res = await apiFetchResponses(`/calendar/events/${encodeURIComponent(eventId)}`, {
    method: 'DELETE', headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '取消日程失败'))
}
