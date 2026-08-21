import { apiFetch, authHeaders, readApiError } from './transport'

export interface SQLAssetItem {
  id: string
  source_id: string
  title: string
  description: string
  sql: string
  asset_type: string
  statement_type: string
  executable: boolean
  status: 'draft' | 'published' | 'deprecated' | 'rejected'
  corpus_role: 'retrieval' | 'evaluation' | 'quarantine'
  quality_status: 'unverified' | 'verified' | 'failed' | 'deprecated'
  domain?: string | null
  owner?: string | null
  structure_hash: string
  dialect: string
  tables: string[]
  columns: string[]
  tags: string[]
  knowledge_metadata?: {
    questions?: string[]
    metrics?: Array<{ name: string; formula: string }>
    dimensions?: Array<{ name: string; table: string; column: string }>
    joins?: Array<Record<string, string>>
    time_columns?: string[]
    grain?: string
    filters?: string[]
    assumptions?: string[]
  }
  risk_flags: string[]
  retrieval_count: number
  lineage: Record<string, unknown>
  validation_report: {
    status?: string
    errors?: string[]
    warnings?: string[]
  }
  approved_by?: string | null
  approved_at?: string | null
  created_at?: string
  updated_at?: string
}

export interface SQLAssetSourceItem {
  id: string
  filename: string
  dialect: string
  status: string
  statement_count: number
  version: number
  parse_report: Record<string, unknown>
  created_at?: string
}

export interface SQLDataSourceCandidateItem {
  data_source_id: string
  name: string
  source_type: string
  score: number
  relevance_score: number
  trust_score: number
  blocked: boolean
  reasons: string[]
  evidence_ids: string[]
  matched_terms: string[]
}

export interface SQLDataSourceDecisionItem {
  status: 'selected' | 'needs_clarification' | 'no_source'
  question: string
  selected_data_source_id?: string | null
  selected_data_source_name?: string | null
  confidence: number
  reason: string
  candidates: SQLDataSourceCandidateItem[]
}

export interface SQLAnswerCitationItem {
  label: string
  evidence_id: string
  evidence_type: string
  title: string
  authority: string
  version?: string | null
  citation?: string | null
  reason: string
  excerpt: string
}

export interface SQLLearningRecordItem {
  pattern_key: string
  status: 'ineligible' | 'observed' | 'trusted' | 'rejected' | 'stale'
  confidence: number
  observation_count: number
  success_count: number
  failure_count: number
  reusable: boolean
  reasons: string[]
  evidence_ids: string[]
}

export interface SQLQueryExecutionSummary {
  data_agent_run_id?: string
  state?: string
  answer?: string | null
  answer_citations?: SQLAnswerCitationItem[]
  answer_metadata?: Record<string, unknown>
  learning?: SQLLearningRecordItem
  source_decision?: SQLDataSourceDecisionItem
  warnings?: string[]
  preflight?: Record<string, unknown>
  result_validation?: Record<string, unknown>
  requested?: number
  succeeded?: number
  failed?: number
  requires_reconciliation?: boolean
  reconciliation_count?: number
  unknown_candidate_ids?: string[]
  last_execution_started_at?: string | null
  reconciliation_required_at?: string
}

export interface SQLQueryCandidateItem {
  id: string
  position: number
  title: string
  description: string
  sql: string
  sql_hash: string
  asset_ids: string[]
  tables: string[]
  columns: string[]
  validation_report?: {
    status?: string
    issues?: Array<{ code?: string; message?: string; severity?: string }>
    preflight?: Record<string, unknown>
    result_validation?: Record<string, unknown>
    supporting_memory_ids?: string[]
  }
  execution_status: 'pending' | 'executing' | 'completed' | 'failed' | 'unknown'
  rows: Array<Record<string, unknown>>
  row_count: number
  returned_row_count: number
  result_truncated: boolean
  error_message?: string | null
}

export interface SQLQueryDraftItem {
  id: string
  status: string
  group_type: 'alternative' | 'batch'
  candidates: SQLQueryCandidateItem[]
  execution_summary?: SQLQueryExecutionSummary
  output_mode: 'sql_only' | 'execute_and_answer'
  query_plan: Record<string, unknown>
  needs_clarification: boolean
  clarification: Record<string, unknown>
}

export interface DataAgentGovernanceOverview {
  window_days: number
  runs: {
    total: number
    analyzed: number
    truncated: boolean
    completed: number
    verified: number
    success_rate?: number | null
    verified_answer_rate?: number | null
    evidence_complete_rate?: number | null
    p95_execution_ms?: number | null
    states: Record<string, number>
    failure_stages: Record<string, number>
  }
  governance: {
    open_feedback: number
    open_failure_patterns: number
    learning: Record<string, number>
    golden_cases: Record<string, number>
  }
  release_gate?: DataAgentEvaluationSuiteItem | null
}

export interface DataAgentFailurePatternItem {
  id: string
  failure_stage: string
  error_codes: string[]
  question_examples: string[]
  failure_count: number
  status: 'open' | 'resolved' | 'ignored'
  last_failure_at?: string | null
  resolution_note?: string | null
}

export interface DataAgentFeedbackItem {
  id: string
  run_id: string
  verdict: string
  corrected_sql?: string | null
  comment?: string | null
  status: 'open' | 'resolved' | 'ignored'
  created_at?: string | null
  resolution_note?: string | null
}

export interface DataAgentEvaluationCaseItem {
  id: string
  question: string
  business_domain?: string | null
  tags: string[]
  status: 'draft' | 'published' | 'retired'
  pass_count: number
  failure_count: number
  schema_fingerprint?: string | null
  last_evaluation?: Record<string, unknown>
}

export interface DataAgentEvaluationSuiteItem {
  id: string
  name: string
  status: 'running' | 'passed' | 'failed'
  case_count: number
  passed_count: number
  failed_count: number
  pass_rate: number
  minimum_pass_rate: number
  completed_at?: string | null
}

export interface SQLAssetListParams {
  status?: SQLAssetItem['status'] | ''
  corpus_role?: SQLAssetItem['corpus_role'] | ''
  quality_status?: SQLAssetItem['quality_status'] | ''
  domain?: string
  search?: string
  offset?: number
  limit?: number
}

export interface SQLAssetListResponse {
  sources: SQLAssetSourceItem[]
  assets: SQLAssetItem[]
  pagination: {
    offset: number
    limit: number
    total: number
    has_more: boolean
  }
  facets?: {
    corpus_roles: Record<string, number>
    quality_statuses: Record<string, number>
  }
}

export async function apiListSQLAssets(token: string, databaseId: string, params: SQLAssetListParams = {}): Promise<SQLAssetListResponse> {
  const query = new URLSearchParams()
  if (params.status) query.set('status', params.status)
  if (params.corpus_role) query.set('corpus_role', params.corpus_role)
  if (params.quality_status) query.set('quality_status', params.quality_status)
  if (params.domain?.trim()) query.set('domain', params.domain.trim())
  if (params.search?.trim()) query.set('search', params.search.trim())
  if (params.offset !== undefined) query.set('offset', String(params.offset))
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  const suffix = query.size ? `?${query.toString()}` : ''
  const res = await apiFetch(`/databases/${databaseId}/sql-assets${suffix}`, {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '读取 SQL 资产失败'))
  return res.json()
}

export async function apiUploadSQLAsset(token: string, databaseId: string, file: File): Promise<unknown> {
  const form = new FormData()
  form.append('file', file)
  const res = await apiFetch(`/databases/${databaseId}/sql-assets/upload`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!res.ok) throw new Error(await readApiError(res, '上传 SQL 资产失败'))
  return res.json()
}

export async function apiBatchUploadSQLAssets(
  token: string,
  databaseId: string,
  files: File[],
  metadata: {
    corpus_role: SQLAssetItem['corpus_role']
    domain?: string
    owner?: string
  },
): Promise<{
  summary: {
    total: number
    imported: number
    deduplicated: number
    failed: number
  }
  results: Array<{ filename: string; status: string; error?: string }>
}> {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  form.append('corpus_role', metadata.corpus_role)
  if (metadata.domain?.trim()) form.append('domain', metadata.domain.trim())
  if (metadata.owner?.trim()) form.append('owner', metadata.owner.trim())
  const res = await apiFetch(`/databases/${databaseId}/sql-assets/batch-upload`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!res.ok) throw new Error(await readApiError(res, '批量上传 SQL 资产失败'))
  return res.json()
}

export async function apiUpdateSQLAsset(token: string, databaseId: string, assetId: string, payload: Record<string, unknown>): Promise<SQLAssetItem> {
  const res = await apiFetch(`/databases/${databaseId}/sql-assets/${assetId}`, {
    method: 'PATCH',
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await readApiError(res, '更新 SQL 资产失败'))
  return res.json()
}

export async function apiDeleteSQLAssetSource(token: string, databaseId: string, sourceId: string): Promise<void> {
  const res = await apiFetch(`/databases/${databaseId}/sql-assets/sources/${sourceId}`, {
    method: 'DELETE',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '删除 SQL 资产源失败'))
}

export async function apiGetSQLDraft(token: string, databaseId: string, draftId: string): Promise<SQLQueryDraftItem> {
  const res = await apiFetch(`/databases/${databaseId}/sql-drafts/${draftId}`, {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '读取 SQL 草案失败'))
  return res.json()
}

export async function apiExecuteSQLDraft(
  token: string,
  databaseId: string,
  draftId: string,
  payload: {
    candidate_ids?: string[]
    execute_all?: boolean
    retry_failed?: boolean
  },
): Promise<SQLQueryDraftItem> {
  const res = await apiFetch(`/databases/${databaseId}/sql-drafts/${draftId}/execute`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({
      candidate_ids: payload.candidate_ids || [],
      execute_all: !!payload.execute_all,
      retry_failed: !!payload.retry_failed,
    }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '执行 SQL 草案失败'))
  return res.json()
}

export async function apiGetDataAgentGovernanceOverview(token: string, databaseId: string): Promise<DataAgentGovernanceOverview> {
  const query = new URLSearchParams({ data_source_id: databaseId })
  const res = await apiFetch(`/data-agent/governance/overview?${query.toString()}`, {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '读取问数质量失败'))
  return res.json()
}

export async function apiListDataAgentFailurePatterns(token: string, databaseId: string): Promise<DataAgentFailurePatternItem[]> {
  const query = new URLSearchParams({
    data_source_id: databaseId,
    status: 'open',
  })
  const res = await apiFetch(`/data-agent/governance/failure-patterns?${query.toString()}`, {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '读取失败模式失败'))
  const payload = await res.json()
  return payload.items || []
}

export async function apiResolveDataAgentFailurePattern(token: string, patternId: string, resolutionNote: string): Promise<DataAgentFailurePatternItem> {
  const res = await apiFetch(`/data-agent/governance/failure-patterns/${patternId}/resolve`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({
      status: 'resolved',
      resolution_note: resolutionNote,
    }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '处置失败模式失败'))
  const payload = await res.json()
  return payload.item
}

export async function apiListDataAgentFeedback(token: string, databaseId: string): Promise<DataAgentFeedbackItem[]> {
  const query = new URLSearchParams({
    data_source_id: databaseId,
    status: 'open',
  })
  const res = await apiFetch(`/data-agent/governance/feedback?${query.toString()}`, {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '读取问数反馈失败'))
  const payload = await res.json()
  return payload.items || []
}

export async function apiResolveDataAgentFeedback(token: string, feedbackId: string, resolutionNote: string): Promise<DataAgentFeedbackItem> {
  const res = await apiFetch(`/data-agent/governance/feedback/${feedbackId}/resolve`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({
      status: 'resolved',
      resolution_note: resolutionNote,
    }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '处置问数反馈失败'))
  const payload = await res.json()
  return payload.item
}

export async function apiListDataAgentEvaluationCases(token: string, databaseId: string): Promise<DataAgentEvaluationCaseItem[]> {
  const query = new URLSearchParams({ data_source_id: databaseId })
  const res = await apiFetch(`/data-agent/evaluation-cases?${query.toString()}`, {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '读取 Golden Case 失败'))
  const payload = await res.json()
  return payload.items || []
}

export async function apiCreateDataAgentEvaluationCase(
  token: string,
  databaseId: string,
  payload: {
    question: string
    expected_sql?: string | null
    schema_fingerprint: string
    business_domain?: string | null
    tags?: string[]
  },
): Promise<DataAgentEvaluationCaseItem> {
  const res = await apiFetch('/data-agent/evaluation-cases', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({
      data_source_id: databaseId,
      question: payload.question,
      expected_sql: payload.expected_sql || null,
      expected_plan: {},
      expected_result: [],
      schema_fingerprint: payload.schema_fingerprint,
      business_domain: payload.business_domain || null,
      tags: payload.tags || [],
    }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '创建 Golden Case 失败'))
  const result = await res.json()
  return result.case
}

export async function apiPublishDataAgentEvaluationCase(token: string, caseId: string): Promise<DataAgentEvaluationCaseItem> {
  const res = await apiFetch(`/data-agent/evaluation-cases/${caseId}/publish`, {
    method: 'POST',
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '发布 Golden Case 失败'))
  const result = await res.json()
  return result.case
}

export async function apiRunDataAgentEvaluationSuite(token: string, databaseId: string, execute = false): Promise<DataAgentEvaluationSuiteItem> {
  const res = await apiFetch('/data-agent/evaluation-suites/run', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({
      data_source_id: databaseId,
      name: execute ? '真实执行发布门禁' : '计划与 SQL 发布门禁',
      execute,
      minimum_pass_rate: 1,
    }),
  })
  if (!res.ok) throw new Error(await readApiError(res, '运行发布门禁失败'))
  const payload = await res.json()
  return payload.suite
}
