import { apiFetchResponses, authHeaders, readApiError } from './transport'

export type ProductionAssetType =
  | 'business_domain' | 'service' | 'repository' | 'deployment' | 'config'
  | 'database' | 'table' | 'dashboard' | 'alert' | 'owner' | 'runbook' | 'business_api'

export interface ProductionAsset {
  id: string
  asset_type: ProductionAssetType
  external_key: string
  name: string
  description: string
  environment: string
  status: 'active' | 'degraded' | 'retired'
  criticality: 'low' | 'medium' | 'high' | 'critical'
  classification: 'public' | 'internal' | 'confidential' | 'restricted'
  connector_id?: string | null
  source_kind: string
  source_key?: string | null
  last_seen_at?: string | null
  last_sync_run_id?: string | null
  attributes: Record<string, unknown>
  updated_at?: string | null
}

export interface ProductionAssetRelation {
  id: string
  source_asset_id: string
  target_asset_id: string
  relation_type: string
  confidence: number
  source_kind: string
  source_key?: string | null
  last_seen_at?: string | null
  last_sync_run_id?: string | null
  attributes: Record<string, unknown>
}

export interface ProductionAssetSyncRun {
  id: string
  source_key: string
  connector_id?: string | null
  status: 'running' | 'completed' | 'failed'
  idempotency_key: string
  input_hash: string
  cursor_before?: string | null
  cursor_after?: string | null
  authoritative: boolean
  attempt_count: number
  lease_expires_at: string
  heartbeat_at: string
  stats: Record<string, number>
  error?: string | null
  started_at: string
  completed_at?: string | null
}

export interface ProductionAssetGraph {
  root_asset_id: string
  nodes: ProductionAsset[]
  edges: ProductionAssetRelation[]
  depth: number
  truncated: boolean
}

export interface EnterpriseConnector {
  id: string
  name: string
  connector_kind: string
  transport: 'mcp' | 'native' | 'rest' | 'rpc'
  endpoint?: string | null
  has_secret_ref: boolean
  status: 'disabled' | 'enabled' | 'degraded'
  allowed_operations: string[]
  allowed_environments: string[]
  data_classification: string
  config: Record<string, unknown>
  updated_at?: string | null
}

export interface CapabilityPolicyProjection {
  role: string
  read_domains: Record<string, string>
  write_domains: string[]
  default: 'deny'
  production_writes_require_approval: boolean
  destructive_writes_required_approvals: number
}

export interface PendingProductionApproval {
  id: string
  response_id: string
  call_id: string
  tool_name: string
  side_effect: 'destructive'
  operation_class: string
  arguments: Record<string, unknown>
  status: 'pending' | 'pending_secondary'
  required_approvals: number
  received_approvals: number
  current_user_decision?: 'approved' | 'rejected' | null
  requested_by: string
  response_created_at?: string | null
  created_at?: string | null
}

export interface ProductionConfigPolicy {
  id: string
  asset_id: string
  version: number
  status: 'draft' | 'published' | 'retired'
  schema: Record<string, unknown>
  reference_rules: Record<string, unknown>[]
  business_rules: Record<string, unknown>[]
  history_rules: Record<string, unknown>[]
  capacity_rules: Record<string, unknown>[]
  conflict_rules: Record<string, unknown>[]
  dry_run_operation?: string | null
  published_at?: string | null
}

export interface ProductionConfigSnapshot {
  id: string
  asset_id: string
  policy_id?: string | null
  environment: string
  version_ref: string
  source_ref: string
  status: string
  content_hash: string
  observed_at: string
  content?: Record<string, unknown>
}

export interface ProductionConfigValidationRun {
  id: string
  asset_id: string
  policy_id: string
  snapshot_id?: string | null
  candidate_hash: string
  status: 'pass' | 'warn' | 'fail'
  risk_level: 'low' | 'medium' | 'high' | 'critical'
  checks: Array<{
    check_id: string
    category: string
    status: 'pass' | 'fail' | 'skipped'
    severity: 'error' | 'warning'
    path?: string
    message: string
  }>
  dry_run: Record<string, unknown>
  summary: Record<string, number | string>
  created_at?: string | null
}

async function productionFetch<T>(
  token: string,
  path: string,
  fallback: string,
  init?: RequestInit,
): Promise<T> {
  const response = await apiFetchResponses(path, {
    ...init,
    headers: { ...authHeaders(token), ...(init?.headers || {}) },
  })
  if (!response.ok) throw new Error(await readApiError(response, fallback))
  return response.json() as Promise<T>
}

export async function apiListProductionAssets(
  token: string,
  query = '',
): Promise<ProductionAsset[]> {
  const params = query ? `?q=${encodeURIComponent(query)}&limit=500` : '?limit=500'
  const result = await productionFetch<{ items: ProductionAsset[] }>(
    token, `/production/assets${params}`, '读取生产资产失败',
  )
  return result.items ?? []
}

export async function apiCreateProductionAsset(
  token: string,
  payload: Record<string, unknown>,
): Promise<ProductionAsset> {
  return productionFetch(token, '/production/assets', '创建生产资产失败', {
    method: 'POST', body: JSON.stringify(payload),
  })
}

export async function apiGetProductionAssetGraph(
  token: string,
  assetId: string,
  depth = 2,
): Promise<ProductionAssetGraph> {
  return productionFetch(
    token,
    `/production/asset-graph?asset_id=${encodeURIComponent(assetId)}&depth=${depth}`,
    '读取生产资产关系失败',
  )
}

export async function apiImportProductionAssetGraph(
  token: string,
  payload: Record<string, unknown>,
): Promise<{
  created_assets: number
  updated_assets: number
  created_relations: number
  updated_relations: number
  asset_ids: Record<string, string>
}> {
  return productionFetch(token, '/production/asset-graph/import', '导入生产资产图失败', {
    method: 'POST', body: JSON.stringify(payload),
  })
}

export async function apiSyncProductionAssetGraph(
  token: string,
  payload: Record<string, unknown>,
  idempotencyKey: string,
): Promise<ProductionAssetSyncRun> {
  return productionFetch(token, '/production/asset-graph/sync', '同步生产资产图失败', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(payload),
  })
}

export async function apiListProductionAssetSyncRuns(
  token: string,
  sourceKey = '',
): Promise<ProductionAssetSyncRun[]> {
  const query = sourceKey ? `?source_key=${encodeURIComponent(sourceKey)}` : ''
  const result = await productionFetch<{ items: ProductionAssetSyncRun[] }>(
    token,
    `/production/asset-sync-runs${query}`,
    '读取生产资产同步记录失败',
  )
  return result.items ?? []
}

export async function apiListEnterpriseConnectors(token: string): Promise<EnterpriseConnector[]> {
  const result = await productionFetch<{ items: EnterpriseConnector[] }>(
    token, '/production/connectors', '读取连接器失败',
  )
  return result.items ?? []
}

export async function apiCreateEnterpriseConnector(
  token: string,
  payload: Record<string, unknown>,
): Promise<EnterpriseConnector> {
  return productionFetch(token, '/production/connectors', '创建连接器失败', {
    method: 'POST', body: JSON.stringify(payload),
  })
}

export async function apiUpdateEnterpriseConnector(
  token: string,
  connectorId: string,
  payload: Record<string, unknown>,
): Promise<EnterpriseConnector> {
  return productionFetch(
    token,
    `/production/connectors/${encodeURIComponent(connectorId)}`,
    '更新连接器失败',
    { method: 'PATCH', body: JSON.stringify(payload) },
  )
}

export async function apiGetCapabilityPolicy(token: string): Promise<CapabilityPolicyProjection> {
  return productionFetch(token, '/production/capability-policy', '读取能力策略失败')
}

export async function apiListPendingProductionApprovals(
  token: string,
): Promise<PendingProductionApproval[]> {
  const result = await productionFetch<{ items: PendingProductionApproval[] }>(
    token,
    '/response-approvals/pending',
    '读取生产变更复核队列失败',
  )
  return result.items ?? []
}

export async function apiResolveProductionApproval(
  token: string,
  approval: Pick<PendingProductionApproval, 'id' | 'response_id'>,
  approved: boolean,
): Promise<{
  status: 'pending_secondary' | 'approved' | 'rejected'
  required_approvals: number
  received_approvals: number
}> {
  return productionFetch(
    token,
    `/responses/${encodeURIComponent(approval.response_id)}/approvals/${encodeURIComponent(approval.id)}/resolve`,
    '复核生产变更失败',
    { method: 'POST', body: JSON.stringify({ approved }) },
  )
}

export async function apiListConfigPolicies(
  token: string,
  assetId: string,
): Promise<ProductionConfigPolicy[]> {
  const result = await productionFetch<{ items: ProductionConfigPolicy[] }>(
    token,
    `/production/config-assets/${encodeURIComponent(assetId)}/policies`,
    '读取配置策略失败',
  )
  return result.items ?? []
}

export async function apiCreateConfigPolicy(
  token: string,
  assetId: string,
  payload: Record<string, unknown>,
): Promise<ProductionConfigPolicy> {
  return productionFetch(
    token,
    `/production/config-assets/${encodeURIComponent(assetId)}/policies`,
    '创建配置策略失败',
    { method: 'POST', body: JSON.stringify(payload) },
  )
}

export async function apiPublishConfigPolicy(
  token: string,
  policyId: string,
): Promise<ProductionConfigPolicy> {
  return productionFetch(
    token,
    `/production/config-policies/${encodeURIComponent(policyId)}/publish`,
    '发布配置策略失败',
    { method: 'POST' },
  )
}

export async function apiListConfigSnapshots(
  token: string,
  assetId: string,
  environment: string,
): Promise<ProductionConfigSnapshot[]> {
  const result = await productionFetch<{ items: ProductionConfigSnapshot[] }>(
    token,
    `/production/config-assets/${encodeURIComponent(assetId)}/snapshots?environment=${encodeURIComponent(environment)}`,
    '读取配置快照失败',
  )
  return result.items ?? []
}

export async function apiCreateConfigSnapshot(
  token: string,
  assetId: string,
  payload: Record<string, unknown>,
): Promise<ProductionConfigSnapshot> {
  return productionFetch(
    token,
    `/production/config-assets/${encodeURIComponent(assetId)}/snapshots`,
    '记录配置快照失败',
    { method: 'POST', body: JSON.stringify(payload) },
  )
}

export async function apiValidateConfigCandidate(
  token: string,
  assetId: string,
  payload: Record<string, unknown>,
): Promise<{ run: ProductionConfigValidationRun; report: Record<string, unknown> }> {
  return productionFetch(
    token,
    `/production/config-assets/${encodeURIComponent(assetId)}/validate`,
    '验证候选配置失败',
    { method: 'POST', body: JSON.stringify(payload) },
  )
}

export async function apiListConfigValidationRuns(
  token: string,
  assetId: string,
): Promise<ProductionConfigValidationRun[]> {
  const result = await productionFetch<{ items: ProductionConfigValidationRun[] }>(
    token,
    `/production/config-assets/${encodeURIComponent(assetId)}/validation-runs`,
    '读取配置验证记录失败',
  )
  return result.items ?? []
}
