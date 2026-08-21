import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  ArrowLeft,
  Boxes,
  Cable,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  FileCheck2,
  Plus,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import {
  apiCreateConfigPolicy,
  apiCreateConfigSnapshot,
  apiCreateEnterpriseConnector,
  apiCreateProductionAsset,
  apiGetCapabilityPolicy,
  apiGetProductionAssetGraph,
  apiImportProductionAssetGraph,
  apiListConfigPolicies,
  apiListConfigSnapshots,
  apiListConfigValidationRuns,
  apiListEnterpriseConnectors,
  apiListPendingProductionApprovals,
  apiListProductionAssetSyncRuns,
  apiListProductionAssets,
  apiPublishConfigPolicy,
  apiResolveProductionApproval,
  apiSyncProductionAssetGraph,
  apiUpdateEnterpriseConnector,
  apiValidateConfigCandidate,
  type CapabilityPolicyProjection,
  type EnterpriseConnector,
  type PendingProductionApproval,
  type ProductionAsset,
  type ProductionAssetGraph,
  type ProductionAssetSyncRun,
  type ProductionConfigPolicy,
  type ProductionConfigSnapshot,
  type ProductionConfigValidationRun,
} from '../api/productionIntelligence'
import { useAuthStore } from '../store/auth'

type Tab = 'overview' | 'assets' | 'connectors' | 'config'

const ASSET_LABELS: Record<string, string> = {
  business_domain: '业务域', service: '服务', repository: '代码仓库', deployment: '部署',
  config: '配置', database: '数据库', table: '数据表', dashboard: '看板', alert: '告警',
  owner: '负责人', runbook: '运行手册', business_api: '业务接口',
}

const CONNECTOR_LABELS: Record<string, string> = {
  data: '数据', observability: '可观测', knowledge: '知识', code: '代码', business: '业务',
  config: '配置', cicd: '持续交付', cmdb: '资产目录', kubernetes: '容器平台',
}

const DEFAULT_OPERATION_SPECS = JSON.stringify([
  {
    name: 'query_status',
    description: '按资产查询当前状态',
    domain: 'observability',
    risk: 'read',
    input_schema: {
      type: 'object',
      properties: {
        query: { type: 'string', maxLength: 2000 },
        environment: { type: 'string', maxLength: 32 },
      },
      required: ['query', 'environment'],
      additionalProperties: false,
    },
    evidence_types: ['metric', 'alert'],
  },
], null, 2)

const DEFAULT_POLICY = JSON.stringify({
  schema: {
    type: 'object',
    properties: {},
    additionalProperties: false,
  },
  reference_rules: [],
  business_rules: [],
  history_rules: [],
  capacity_rules: [],
  conflict_rules: [],
  dry_run_operation: null,
}, null, 2)

const DEFAULT_GRAPH_IMPORT = JSON.stringify({
  assets: [
    { asset_type: 'business_domain', external_key: 'payment', name: '支付业务', environment: 'prod', source_kind: 'import' },
    { asset_type: 'service', external_key: 'payment-service', name: 'Payment Service', environment: 'prod', source_kind: 'import' },
  ],
  relations: [
    {
      source_asset_type: 'business_domain', source_external_key: 'payment',
      target_asset_type: 'service', target_external_key: 'payment-service',
      relation_type: 'contains', source_kind: 'import',
    },
  ],
  upsert: true,
  source: 'cmdb_import',
}, null, 2)

const DEFAULT_GRAPH_SYNC = JSON.stringify({
  source_key: 'cmdb:primary',
  connector_id: null,
  cursor_before: null,
  cursor_after: null,
  authoritative: false,
  adopt_existing: false,
  assets: [
    { asset_type: 'service', external_key: 'payment-service', name: 'Payment Service', environment: 'prod', source_kind: 'sync' },
  ],
  relations: [],
}, null, 2)

function parseObject(text: string, label: string): Record<string, unknown> {
  const value = JSON.parse(text)
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label}必须是 JSON 对象`)
  }
  return value as Record<string, unknown>
}

function StatusPill({ status }: { status: string }) {
  const tone = status === 'active' || status === 'enabled' || status === 'published' || status === 'pass'
    ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300'
    : status === 'degraded' || status === 'warn' || status === 'draft'
      ? 'bg-amber-500/15 text-amber-600 dark:text-amber-300'
      : 'bg-slate-500/15 text-[var(--text-secondary)]'
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${tone}`}>{status}</span>
}

function SectionTitle({ title, description }: { title: string; description: string }) {
  return <div><h2 className="text-base font-semibold text-[var(--text)]">{title}</h2><p className="mt-1 text-xs text-[var(--text-secondary)]">{description}</p></div>
}

function EmptyState({ text }: { text: string }) {
  return <div className="rounded-2xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--text-secondary)]">{text}</div>
}

export default function ProductionIntelligencePage({ onBack }: { onBack?: () => void }) {
  const token = useAuthStore((state) => state.token) || ''
  const [tab, setTab] = useState<Tab>('overview')
  const [assets, setAssets] = useState<ProductionAsset[]>([])
  const [connectors, setConnectors] = useState<EnterpriseConnector[]>([])
  const [policy, setPolicy] = useState<CapabilityPolicyProjection | null>(null)
  const [graph, setGraph] = useState<ProductionAssetGraph | null>(null)
  const [selectedAssetId, setSelectedAssetId] = useState('')
  const [selectedConfigId, setSelectedConfigId] = useState('')
  const [configPolicies, setConfigPolicies] = useState<ProductionConfigPolicy[]>([])
  const [snapshots, setSnapshots] = useState<ProductionConfigSnapshot[]>([])
  const [validationRuns, setValidationRuns] = useState<ProductionConfigValidationRun[]>([])
  const [syncRuns, setSyncRuns] = useState<ProductionAssetSyncRun[]>([])
  const [pendingApprovals, setPendingApprovals] = useState<PendingProductionApproval[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const [assetForm, setAssetForm] = useState({
    asset_type: 'service', external_key: '', name: '', environment: 'prod', description: '',
  })
  const [connectorForm, setConnectorForm] = useState({
    name: '', connector_kind: 'observability', endpoint: '', secret_ref: '',
    environments: 'prod', operation_specs: DEFAULT_OPERATION_SPECS,
  })
  const [policyText, setPolicyText] = useState(DEFAULT_POLICY)
  const [snapshotText, setSnapshotText] = useState('{}')
  const [candidateText, setCandidateText] = useState('{}')
  const [graphImportText, setGraphImportText] = useState(DEFAULT_GRAPH_IMPORT)
  const [graphSyncText, setGraphSyncText] = useState(DEFAULT_GRAPH_SYNC)
  const [syncIdempotencyKey, setSyncIdempotencyKey] = useState(`asset-sync-${Date.now()}`)

  const configAssets = useMemo(() => assets.filter((item) => item.asset_type === 'config'), [assets])
  const selectedConfig = configAssets.find((item) => item.id === selectedConfigId)

  async function loadAll() {
    if (!token) return
    setLoading(true)
    setError('')
    try {
      const [nextAssets, nextConnectors, nextPolicy, nextSyncRuns, nextApprovals] = await Promise.all([
        apiListProductionAssets(token),
        apiListEnterpriseConnectors(token),
        apiGetCapabilityPolicy(token),
        apiListProductionAssetSyncRuns(token),
        apiListPendingProductionApprovals(token),
      ])
      setAssets(nextAssets)
      setConnectors(nextConnectors)
      setPolicy(nextPolicy)
      setSyncRuns(nextSyncRuns)
      setPendingApprovals(nextApprovals)
      setSelectedAssetId((current) => current || nextAssets[0]?.id || '')
      setSelectedConfigId((current) => current || nextAssets.find((item) => item.asset_type === 'config')?.id || '')
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : '加载生产智能工作台失败')
    } finally {
      setLoading(false)
    }
  }

  async function loadGraph(assetId: string) {
    if (!assetId) return setGraph(null)
    try {
      setGraph(await apiGetProductionAssetGraph(token, assetId))
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : '读取资产关系失败')
    }
  }

  async function loadConfig(assetId: string) {
    if (!assetId) {
      setConfigPolicies([]); setSnapshots([]); setValidationRuns([]); return
    }
    const environment = configAssets.find((item) => item.id === assetId)?.environment || 'shared'
    try {
      const [nextPolicies, nextSnapshots, nextRuns] = await Promise.all([
        apiListConfigPolicies(token, assetId),
        apiListConfigSnapshots(token, assetId, environment),
        apiListConfigValidationRuns(token, assetId),
      ])
      setConfigPolicies(nextPolicies); setSnapshots(nextSnapshots); setValidationRuns(nextRuns)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : '读取配置智能资产失败')
    }
  }

  useEffect(() => { void loadAll() }, [token])
  useEffect(() => { void loadGraph(selectedAssetId) }, [selectedAssetId, token])
  useEffect(() => { void loadConfig(selectedConfigId) }, [selectedConfigId, token, configAssets.length])

  async function runAction(action: () => Promise<string | void>, success: string) {
    setSaving(true); setError(''); setMessage('')
    try {
      const resultMessage = await action(); setMessage(resultMessage || success)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : '操作失败')
    } finally {
      setSaving(false)
    }
  }

  async function createAsset() {
    await runAction(async () => {
      const created = await apiCreateProductionAsset(token, {
        ...assetForm, status: 'active', criticality: 'medium', classification: 'internal',
        source_kind: 'manual', attributes: {},
      })
      setAssetForm({ ...assetForm, external_key: '', name: '', description: '' })
      await loadAll(); setSelectedAssetId(created.id)
    }, '生产资产已创建')
  }

  async function createConnector() {
    await runAction(async () => {
      const specs = JSON.parse(connectorForm.operation_specs)
      if (!Array.isArray(specs) || specs.length === 0) throw new Error('至少声明一个受治理操作')
      const endpoint = new URL(connectorForm.endpoint.trim())
      await apiCreateEnterpriseConnector(token, {
        name: connectorForm.name,
        connector_kind: connectorForm.connector_kind,
        transport: 'mcp', endpoint: endpoint.toString(),
        secret_ref: connectorForm.secret_ref || null, status: 'disabled',
        allowed_operations: specs.map((item) => String(item.name || '')),
        allowed_environments: connectorForm.environments.split(',').map((item) => item.trim()).filter(Boolean),
        data_classification: 'internal',
        config: {
          adapter_key: 'mcp',
          allowed_hosts: [endpoint.hostname],
          operation_specs: specs,
          runtime_policy: {
            enabled: true, requests_per_minute: 120, max_concurrency: 8,
            failure_threshold: 5, recovery_seconds: 60, half_open_max_calls: 1,
            lease_grace_seconds: 5, read_fail_open: true,
          },
        },
      })
      setConnectorForm({ ...connectorForm, name: '', endpoint: '', secret_ref: '' })
      await loadAll()
    }, '连接器已保存为停用状态，请核对权限后再启用')
  }

  async function importGraph() {
    await runAction(async () => {
      const payload = parseObject(graphImportText, '资产图导入内容')
      const result = await apiImportProductionAssetGraph(token, payload)
      await loadAll()
      return `资产图导入完成：新增 ${result.created_assets} 个节点、${result.created_relations} 条关系；更新 ${result.updated_assets} 个节点、${result.updated_relations} 条关系`
    }, '资产图导入完成')
  }

  async function syncGraph() {
    await runAction(async () => {
      if (!syncIdempotencyKey.trim()) throw new Error('必须提供稳定的同步幂等键')
      const payload = parseObject(graphSyncText, '资产图同步内容')
      const run = await apiSyncProductionAssetGraph(token, payload, syncIdempotencyKey.trim())
      await loadAll()
      if (run.status === 'completed') setSyncIdempotencyKey(`asset-sync-${Date.now()}`)
      return `资产同步 ${run.status}：第 ${run.attempt_count} 次尝试，新增 ${run.stats.created_assets || 0} 个、更新 ${run.stats.updated_assets || 0} 个、退役 ${run.stats.retired_assets || 0} 个资产`
    }, '资产图同步完成')
  }

  async function toggleConnector(connector: EnterpriseConnector) {
    const next = connector.status === 'enabled' ? 'disabled' : 'enabled'
    if (next === 'enabled' && !confirm(`确认启用连接器“${connector.name}”？启用后只会开放已声明的操作。`)) return
    await runAction(async () => {
      await apiUpdateEnterpriseConnector(token, connector.id, { status: next })
      await loadAll()
    }, next === 'enabled' ? '连接器已启用' : '连接器已停用')
  }

  async function resolveProductionApproval(item: PendingProductionApproval, approved: boolean) {
    if (approved && !confirm('这是高风险生产变更。你将作为独立复核人提交决定，系统要求两个不同账号批准。确认继续吗？')) return
    await runAction(async () => {
      const result = await apiResolveProductionApproval(token, item, approved)
      await loadAll()
      if (result.status === 'pending_secondary') {
        return `已记录 ${result.received_approvals}/${result.required_approvals} 份批准，仍在等待另一位复核人`
      }
      return approved ? '四眼审批已满足，Response 已恢复执行' : '生产变更已拒绝，Response 将恢复并解释拒绝结果'
    }, approved ? '生产变更已批准' : '生产变更已拒绝')
  }

  async function createPolicy() {
    if (!selectedConfigId) return
    await runAction(async () => {
      await apiCreateConfigPolicy(token, selectedConfigId, parseObject(policyText, '配置策略'))
      await loadConfig(selectedConfigId)
    }, '配置策略草稿已创建')
  }

  async function publishPolicy(item: ProductionConfigPolicy) {
    if (!confirm(`确认发布配置策略 v${item.version}？当前已发布版本会自动退役。`)) return
    await runAction(async () => {
      await apiPublishConfigPolicy(token, item.id); await loadConfig(selectedConfigId)
    }, `配置策略 v${item.version} 已发布`)
  }

  async function createSnapshot() {
    if (!selectedConfig) return
    await runAction(async () => {
      await apiCreateConfigSnapshot(token, selectedConfig.id, {
        environment: selectedConfig.environment,
        version_ref: `manual-${new Date().toISOString()}`,
        source_ref: `manual://${selectedConfig.external_key}`,
        status: 'current', content: parseObject(snapshotText, '配置快照'),
      })
      await loadConfig(selectedConfig.id)
    }, '配置快照已记录')
  }

  async function validateCandidate() {
    if (!selectedConfig) return
    await runAction(async () => {
      await apiValidateConfigCandidate(token, selectedConfig.id, {
        environment: selectedConfig.environment,
        candidate: parseObject(candidateText, '候选配置'),
      })
      await loadConfig(selectedConfig.id)
    }, '候选配置已完成确定性校验')
  }

  const tabs: Array<{ key: Tab; label: string; icon: React.ReactNode }> = [
    { key: 'overview', label: '总览', icon: <Activity size={15} /> },
    { key: 'assets', label: '生产资产', icon: <Boxes size={15} /> },
    { key: 'connectors', label: '连接器', icon: <Cable size={15} /> },
    { key: 'config', label: '配置智能', icon: <FileCheck2 size={15} /> },
  ]

  return <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
    <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--bg)]/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3 md:px-6">
        <button onClick={onBack} aria-label="返回提问" className="rounded-xl p-2 text-[var(--text-secondary)] hover:bg-[var(--surface)]"><ArrowLeft size={18} /></button>
        <div className="min-w-0 flex-1"><h1 className="truncate text-lg font-semibold">生产智能控制台</h1><p className="text-xs text-[var(--text-secondary)]">资产、连接器、策略和证据的统一治理入口</p></div>
        <button onClick={() => void loadAll()} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] px-3 py-2 text-xs hover:bg-[var(--surface)] disabled:opacity-50"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />刷新</button>
      </div>
      <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 pb-3 md:px-6" aria-label="生产智能模块">
        {tabs.map((item) => <button key={item.key} onClick={() => setTab(item.key)} className={`inline-flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-sm ${tab === item.key ? 'bg-[var(--accent-dim)] text-[var(--accent)]' : 'text-[var(--text-secondary)] hover:bg-[var(--surface)]'}`}>{item.icon}{item.label}</button>)}
      </nav>
    </header>

    <main className="mx-auto max-w-7xl space-y-5 p-4 md:p-6">
      {(message || error) && <div role={error ? 'alert' : 'status'} className={`rounded-xl border px-4 py-3 text-sm ${error ? 'border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-300' : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'}`}>{error || message}</div>}

      {tab === 'overview' && <>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: '生产资产', value: assets.length, icon: <Boxes size={16} /> },
            { label: '已启用连接器', value: connectors.filter((item) => item.status === 'enabled').length, icon: <Cable size={16} /> },
            { label: '配置资产', value: configAssets.length, icon: <FileCheck2 size={16} /> },
            { label: '关键资产', value: assets.filter((item) => item.criticality === 'critical').length, icon: <CircleAlert size={16} /> },
          ].map((item) => <section key={item.label} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-center justify-between text-[var(--text-secondary)]"><span className="text-xs">{item.label}</span>{item.icon}</div><div className="mt-3 text-2xl font-semibold">{item.value}</div></section>)}
        </div>
        <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <div className="flex items-start gap-3"><ShieldCheck className="mt-0.5 text-[var(--accent)]" size={20} /><div><h2 className="font-semibold">当前能力策略</h2><p className="mt-1 text-sm text-[var(--text-secondary)]">默认拒绝；生产写入必须进入持久审批，破坏性操作固定要求 {policy?.destructive_writes_required_approvals || 2} 个不同账号。当前角色：{policy?.role || '读取中'}</p></div></div>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{Object.entries(policy?.read_domains || {}).map(([domain, mode]) => <div key={domain} className="flex items-center justify-between rounded-xl bg-[var(--bg-secondary)] px-3 py-2 text-xs"><span>{CONNECTOR_LABELS[domain] || domain}</span><span className="text-[var(--text-secondary)]">{mode}</span></div>)}</div>
        </section>
        <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <SectionTitle title="高风险生产变更复核" description="回滚、删除和生产变更必须由两个不同账号批准；任一复核人拒绝即终止执行。" />
          <div className="mt-4 space-y-3">
            {pendingApprovals.length === 0 ? <EmptyState text="当前没有等待四眼复核的生产变更" /> : pendingApprovals.map((item) => <article key={item.id} className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><div className="text-sm font-medium">{item.tool_name}</div><div className="mt-1 text-xs text-[var(--text-secondary)]">Response {item.response_id} · 已批准 {item.received_approvals}/{item.required_approvals}</div></div><StatusPill status={item.status} /></div><pre className="mt-3 max-h-40 overflow-auto rounded-xl bg-[var(--bg)] p-3 text-xs">{JSON.stringify(item.arguments, null, 2)}</pre><div className="mt-3 flex gap-2"><button disabled={saving || item.current_user_decision === 'approved'} onClick={() => void resolveProductionApproval(item, true)} className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm text-white disabled:opacity-50">{item.current_user_decision === 'approved' ? '已批准，等待他人' : '独立批准'}</button><button disabled={saving || Boolean(item.current_user_decision)} onClick={() => void resolveProductionApproval(item, false)} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm disabled:opacity-50">拒绝</button></div></article>)}
          </div>
        </section>
      </>}

      {tab === 'assets' && <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.8fr)]">
        <section className="space-y-3"><SectionTitle title="生产资产目录" description="业务、服务、代码、部署、配置、数据与负责人在同一张图中关联。" />
          {assets.length === 0 ? <EmptyState text="尚未创建生产资产" /> : <div className="space-y-2">{assets.map((item) => <button key={item.id} onClick={() => setSelectedAssetId(item.id)} className={`flex w-full items-center gap-3 rounded-2xl border p-3 text-left ${selectedAssetId === item.id ? 'border-[var(--accent)] bg-[var(--accent-dim)]' : 'border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--surface-raised)]'}`}><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><span className="truncate text-sm font-medium">{item.name}</span><StatusPill status={item.status} /></div><div className="mt-1 truncate text-xs text-[var(--text-secondary)]">{ASSET_LABELS[item.asset_type] || item.asset_type} · {item.external_key} · {item.environment}</div></div><ChevronRight size={15} className="text-[var(--text-secondary)]" /></button>)}</div>}
        </section>
        <div className="space-y-5">
          <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><SectionTitle title="资产关系" description="从当前资产向外展开两层依赖。" />{graph ? <div className="mt-4 space-y-3"><div className="flex gap-4 text-xs text-[var(--text-secondary)]"><span>{graph.nodes.length} 个节点</span><span>{graph.edges.length} 条关系</span>{graph.truncated && <span className="text-amber-500">结果已截断</span>}</div><div className="max-h-72 space-y-2 overflow-y-auto">{graph.edges.map((edge) => <div key={edge.id} className="rounded-xl bg-[var(--bg-secondary)] px-3 py-2 text-xs"><div className="font-medium">{edge.relation_type}</div><div className="mt-1 truncate text-[var(--text-secondary)]">{edge.source_asset_id} → {edge.target_asset_id}</div></div>)}</div></div> : <p className="mt-4 text-sm text-[var(--text-secondary)]">选择资产后显示关系。</p>}</section>
          <details className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><summary className="cursor-pointer text-sm font-medium">新增生产资产</summary><div className="mt-4 space-y-3"><select value={assetForm.asset_type} onChange={(event) => setAssetForm({ ...assetForm, asset_type: event.target.value })} className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm">{Object.entries(ASSET_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><input value={assetForm.name} onChange={(event) => setAssetForm({ ...assetForm, name: event.target.value })} placeholder="资产名称" className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" /><input value={assetForm.external_key} onChange={(event) => setAssetForm({ ...assetForm, external_key: event.target.value })} placeholder="系统内唯一标识" className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" /><div className="grid grid-cols-2 gap-3"><input value={assetForm.environment} onChange={(event) => setAssetForm({ ...assetForm, environment: event.target.value })} placeholder="环境" className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" /><input value={assetForm.description} onChange={(event) => setAssetForm({ ...assetForm, description: event.target.value })} placeholder="说明" className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" /></div><button disabled={saving || !assetForm.name || !assetForm.external_key} onClick={() => void createAsset()} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-50"><Plus size={15} />创建资产</button></div></details>
          <details className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><summary className="cursor-pointer text-sm font-medium">原子批量导入资产图</summary><p className="mt-2 text-xs text-[var(--text-secondary)]">适用于一次性迁移或人工批量维护；任一节点或关系不合法时整批回滚。持续外部同步请使用下方持久化入口。</p><textarea rows={16} value={graphImportText} onChange={(event) => setGraphImportText(event.target.value)} className="mt-3 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 font-mono text-xs" /><button disabled={saving} onClick={() => void importGraph()} className="mt-3 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-50">导入资产图</button></details>
          <details className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><summary className="cursor-pointer text-sm font-medium">持久化资产源同步</summary><p className="mt-2 text-xs text-[var(--text-secondary)]">使用来源所有权、游标、租约和幂等记录同步 CMDB/Git/Kubernetes。权威同步会退役同源缺失资产；转移既有资产所有权需显式开启。</p><input value={syncIdempotencyKey} onChange={(event) => setSyncIdempotencyKey(event.target.value)} placeholder="稳定 Idempotency-Key" className="mt-3 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-xs" /><textarea rows={18} value={graphSyncText} onChange={(event) => setGraphSyncText(event.target.value)} className="mt-3 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 font-mono text-xs" /><button disabled={saving || !syncIdempotencyKey.trim()} onClick={() => void syncGraph()} className="mt-3 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-50">执行受治理同步</button></details>
          <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><SectionTitle title="最近同步运行" description="运行、失败和重试均保留持久事实；相同幂等键只接受完全相同的输入。" />{syncRuns.length === 0 ? <p className="mt-4 text-sm text-[var(--text-secondary)]">尚无资产同步记录。</p> : <div className="mt-4 max-h-80 space-y-2 overflow-y-auto">{syncRuns.slice(0, 20).map((run) => <article key={run.id} className="rounded-xl bg-[var(--bg-secondary)] p-3 text-xs"><div className="flex items-center justify-between gap-2"><span className="truncate font-mono">{run.source_key}</span><StatusPill status={run.status} /></div><div className="mt-2 text-[var(--text-secondary)]">尝试 {run.attempt_count} · 输入 {run.stats.assets_received || 0} 个资产 · 退役 {run.stats.retired_assets || 0} 个</div>{run.error && <div className="mt-2 break-all text-red-500">{run.error}</div>}</article>)}</div>}</section>
        </div>
      </div>}

      {tab === 'connectors' && <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_420px]">
        <section className="space-y-3"><SectionTitle title="企业连接器" description="凭据只保存为 Vault、KMS 或环境变量引用；远端发现不能扩大本地允许操作。" />{connectors.length === 0 ? <EmptyState text="尚未配置连接器" /> : connectors.map((item) => <article key={item.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-start justify-between gap-3"><div><div className="flex items-center gap-2"><h3 className="font-medium">{item.name}</h3><StatusPill status={item.status} /></div><p className="mt-1 text-xs text-[var(--text-secondary)]">{CONNECTOR_LABELS[item.connector_kind] || item.connector_kind} · {item.transport.toUpperCase()} · {item.allowed_environments.join('、') || '共享环境'}</p></div><button onClick={() => void toggleConnector(item)} disabled={saving} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--surface-raised)]">{item.status === 'enabled' ? '停用' : '启用'}</button></div><div className="mt-3 flex flex-wrap gap-2">{item.allowed_operations.map((operation) => <span key={operation} className="rounded-lg bg-[var(--bg-secondary)] px-2 py-1 font-mono text-[11px]">{operation}</span>)}</div><p className="mt-3 truncate text-xs text-[var(--text-secondary)]">{item.endpoint || '原生适配器'} · {item.has_secret_ref ? '已配置凭据引用' : '未配置凭据'}</p></article>)}</section>
        <section className="h-fit rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><SectionTitle title="新增 MCP 连接器" description="新连接器默认停用；写操作还必须声明验证证据，并始终进入持久审批。" /><div className="mt-4 space-y-3"><input value={connectorForm.name} onChange={(event) => setConnectorForm({ ...connectorForm, name: event.target.value })} placeholder="连接器名称" className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" /><select value={connectorForm.connector_kind} onChange={(event) => setConnectorForm({ ...connectorForm, connector_kind: event.target.value })} className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm">{Object.entries(CONNECTOR_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><input value={connectorForm.endpoint} onChange={(event) => setConnectorForm({ ...connectorForm, endpoint: event.target.value })} placeholder="https://example.com/mcp" className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" /><input value={connectorForm.secret_ref} onChange={(event) => setConnectorForm({ ...connectorForm, secret_ref: event.target.value })} placeholder="env://MCP_TOKEN 或 vault://…" className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-sm" /><input value={connectorForm.environments} onChange={(event) => setConnectorForm({ ...connectorForm, environments: event.target.value })} placeholder="prod,staging" className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" /><label className="block text-xs text-[var(--text-secondary)]">操作与证据声明<textarea rows={14} value={connectorForm.operation_specs} onChange={(event) => setConnectorForm({ ...connectorForm, operation_specs: event.target.value })} className="mt-1 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 font-mono text-xs" /></label><button onClick={() => void createConnector()} disabled={saving || !connectorForm.name || !connectorForm.endpoint} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-50"><Plus size={15} />保存连接器</button></div></section>
      </div>}

      {tab === 'config' && <div className="space-y-5">
        <section className="flex flex-wrap items-end gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="min-w-64 flex-1"><label className="text-xs text-[var(--text-secondary)]">配置资产</label><select value={selectedConfigId} onChange={(event) => setSelectedConfigId(event.target.value)} className="mt-1 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"><option value="">请选择</option>{configAssets.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.environment}</option>)}</select></div>{selectedConfig && <div className="text-xs text-[var(--text-secondary)]">{selectedConfig.external_key} · {selectedConfig.classification}</div>}</section>
        {!selectedConfig ? <EmptyState text="先在生产资产中创建并选择一个配置资产" /> : <div className="grid gap-5 xl:grid-cols-3">
          <section className="space-y-3"><SectionTitle title="校验策略" description="策略先保存为草稿，发布后才会被 Config Agent 使用。" />{configPolicies.map((item) => <article key={item.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-center justify-between"><div className="font-medium">版本 v{item.version}</div><StatusPill status={item.status} /></div><div className="mt-2 text-xs text-[var(--text-secondary)]">{item.business_rules.length} 条业务规则 · {item.conflict_rules.length} 条冲突规则 · {item.dry_run_operation ? '已声明 dry-run' : '无 dry-run'}</div>{item.status === 'draft' && <button onClick={() => void publishPolicy(item)} className="mt-3 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--surface-raised)]">发布策略</button>}</article>)}<details className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><summary className="cursor-pointer text-sm font-medium">创建策略草稿</summary><textarea rows={18} value={policyText} onChange={(event) => setPolicyText(event.target.value)} className="mt-3 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 font-mono text-xs" /><button onClick={() => void createPolicy()} disabled={saving} className="mt-3 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-50">保存草稿</button></details></section>
          <section className="space-y-3"><SectionTitle title="配置快照" description="当前、历史和候选配置只保存受控投影与内容哈希。" />{snapshots.length === 0 ? <EmptyState text="尚未记录配置快照" /> : snapshots.map((item) => <article key={item.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-center justify-between"><span className="truncate font-mono text-xs">{item.version_ref}</span><StatusPill status={item.status} /></div><p className="mt-2 truncate text-xs text-[var(--text-secondary)]">{item.content_hash}</p></article>)}<details className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><summary className="cursor-pointer text-sm font-medium">记录当前快照</summary><textarea rows={14} value={snapshotText} onChange={(event) => setSnapshotText(event.target.value)} className="mt-3 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 font-mono text-xs" /><button onClick={() => void createSnapshot()} disabled={saving} className="mt-3 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-50">记录快照</button></details></section>
          <section className="space-y-3"><SectionTitle title="验证运行" description="按 Schema、引用、业务规则、历史、容量、冲突和 dry-run 分层显示。" />{validationRuns.length === 0 ? <EmptyState text="尚未执行配置验证" /> : validationRuns.map((item) => <article key={item.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-center justify-between"><div className="flex items-center gap-2">{item.status === 'pass' ? <CheckCircle2 size={16} className="text-emerald-500" /> : <CircleAlert size={16} className="text-amber-500" />}<span className="font-medium">{item.risk_level} 风险</span></div><StatusPill status={item.status} /></div><div className="mt-3 space-y-1">{item.checks.filter((check) => check.status !== 'pass').slice(0, 6).map((check) => <div key={check.check_id} className="rounded-lg bg-[var(--bg-secondary)] px-2 py-1.5 text-xs"><span className="font-medium">{check.category}</span><span className="ml-2 text-[var(--text-secondary)]">{check.message}</span></div>)}</div></article>)}<details className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><summary className="cursor-pointer text-sm font-medium">验证候选配置</summary><textarea rows={14} value={candidateText} onChange={(event) => setCandidateText(event.target.value)} className="mt-3 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 font-mono text-xs" /><button onClick={() => void validateCandidate()} disabled={saving || configPolicies.every((item) => item.status !== 'published')} className="mt-3 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-white disabled:opacity-50">开始验证</button></details></section>
        </div>}
      </div>}
    </main>
  </div>
}
