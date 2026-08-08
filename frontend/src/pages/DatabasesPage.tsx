import { useEffect, useMemo, useRef, useState } from 'react'
import { Archive, BarChart3, CheckCircle2, ChevronLeft, Circle, Database, FileCode2, Gauge, Pencil, PlayCircle, Plus, RefreshCw, Search, Settings2, ShieldCheck, Table2, Trash2, Upload, Users, Zap } from 'lucide-react'
import DatabaseTypeSelect, { DATABASE_HOST_MODE_OPTIONS, type DatabaseHostMode, type DatabaseType } from '../components/DatabaseTypeSelect'
import MarkdownMessage from '../components/MarkdownMessage'
import { useAuthStore } from '../store/auth'
import { useChatPreferences } from '../store/chatPreferences'
import {
  buildJdbc,
  getDefaultHostForMode,
  getDefaultJdbcParams,
  isAllowedDatabaseHost,
  isLocalHost,
  parseJdbc,
  parseJdbcLikeHostInput,
} from '../lib/databaseConnection'
import {
  apiAnalyzeDatabase,
  apiCreateDatabase,
  apiDatabaseQuery,
  apiDeleteDatabase,
  apiGetDatabaseSchema,
  apiListDatabases,
  apiSyncDatabaseSchema,
  apiTestDatabaseConnection,
  apiUpdateDatabase,
  apiGetSemanticConfig,
  apiUpdateSemanticConfig,
  apiAutoExtractSemantic,
  apiGetDatabaseWorkbench,
  apiDeleteSQLAssetSource,
  apiExecuteSQLDraft,
  apiGetSQLDraft,
  apiValidateDatabase,
  apiListSQLAssets,
  apiListPermissionSubjects,
  apiListResourcePermissions,
  apiGrantResourcePermission,
  apiRevokeResourcePermission,
  apiUpdateSQLAsset,
  apiUploadSQLAsset,
  type DataSourceItem,
  type DatabaseSchemaPagination,
  type DatabaseSchemaPayload,
  type ResourcePermissionItem,
  type SQLAssetItem,
  type SQLAssetSourceItem,
  type SQLQueryCandidateItem,
} from '../api/client'

type TabKey = 'overview' | 'tables' | 'query' | 'sql_assets' | 'analysis' | 'settings' | 'metrics' | 'relationships' | 'skills'

const SQL_ASSET_PAGE_SIZE = 20
const SCHEMA_TABLE_PAGE_SIZE = 100
const SQL_ASSET_STATUS_LABELS: Record<SQLAssetItem['status'], string> = {
  draft: '草稿',
  published: '已发布',
  deprecated: '已废弃',
  rejected: '已驳回',
}
const SQL_EXECUTION_STATUS_LABELS: Record<SQLQueryCandidateItem['execution_status'], string> = {
  pending: '待确认',
  executing: '执行中',
  completed: '已完成',
  failed: '失败',
}

export default function DatabasesPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((s) => s.token)!
  const requestPrefill = useChatPreferences((state) => state.requestPrefill)
  const [items, setItems] = useState<DataSourceItem[]>([])
  const [selected, setSelected] = useState<DataSourceItem | null>(null)
  const [activeTab, setActiveTab] = useState<TabKey>('overview')
  const [question, setQuestion] = useState('过去30天订单趋势')
  const [queryOutput, setQueryOutput] = useState<{
    answer?: string
    summary: string
    sql: string
    rows: Array<Record<string, unknown>>
    insights?: Record<string, any>
    statistical_report?: Record<string, any>
    visualization_config?: Record<string, any>
    verification_report?: Record<string, any>
    confidence?: number
    session_id?: string
    needs_clarification?: boolean
    clarification?: {
      question_id: string
      question_text: string
      missing_entities: string[]
      suggested_options: string[]
    }
    draft_id?: string
    draft_status?: string
    candidates?: SQLQueryCandidateItem[]
  } | null>(null)
  const [querySessionId, setQuerySessionId] = useState<string | null>(null)
  const [sessionContext, setSessionContext] = useState<Record<string, any> | null>(null)
  const [queryHistory, setQueryHistory] = useState<Array<{
    question: string
    answer: string
    isClarification: boolean
  }>>([])
  const [schema, setSchema] = useState<DatabaseSchemaPayload | null>(null)
  const [schemaPagination, setSchemaPagination] = useState<DatabaseSchemaPagination | null>(null)
  const [schemaSearch, setSchemaSearch] = useState('')
  const [schemaAppliedSearch, setSchemaAppliedSearch] = useState('')
  const [schemaDatabase, setSchemaDatabase] = useState('')
  const [schemaLoading, setSchemaLoading] = useState(false)
  const [schemaError, setSchemaError] = useState('')
  const schemaRequestId = useRef(0)
  const [analysis, setAnalysis] = useState<{ summary: string; charts: any[]; tables: any[]; insights: string[] } | null>(null)
  const [creating, setCreating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [schemaSyncing, setSchemaSyncing] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)

  // semantic layer state
  const [semanticConfig, setSemanticConfig] = useState<{
    dimensions: Record<string, { column: string; table: string; enums?: Record<string, string> }>
    metrics: Record<string, string>
    time_macros: Array<{ keyword: string; column: string; days: number }>
  }>({ dimensions: {}, metrics: {}, time_macros: [] })
  const [editingDimension, setEditingDimension] = useState<{ name: string; column: string; table: string }>({ name: '', column: '', table: '' })
  const [editingMetric, setEditingMetric] = useState<{ name: string; expression: string }>({ name: '', expression: '' })
  const [editingTimeMacro, setEditingTimeMacro] = useState<{ keyword: string; column: string; days: number }>({ keyword: '', column: '', days: 7 })

  // DataAgent V2 knowledge asset state
  const [metricsList, setMetricsList] = useState<any[]>([])
  const [relationshipsList, setRelationshipsList] = useState<any[]>([])
  const [skillsList, setSkillsList] = useState<any[]>([])
  const [workbench, setWorkbench] = useState<any>(null)
  const [validating, setValidating] = useState(false)
  const [permissions, setPermissions] = useState<ResourcePermissionItem[]>([])
  const [subjects, setSubjects] = useState<Array<{ id: string; email: string; display_name?: string }>>([])
  const [grantUserId, setGrantUserId] = useState('')
  const [grantLevel, setGrantLevel] = useState<'view' | 'query' | 'edit' | 'admin'>('query')
  const [sqlAssets, setSqlAssets] = useState<SQLAssetItem[]>([])
  const [sqlAssetSources, setSqlAssetSources] = useState<SQLAssetSourceItem[]>([])
  const [uploadingSQL, setUploadingSQL] = useState(false)
  const [executingCandidate, setExecutingCandidate] = useState<string | null>(null)
  const [sqlAssetSearch, setSqlAssetSearch] = useState('')
  const [sqlAssetStatus, setSqlAssetStatus] = useState<SQLAssetItem['status'] | ''>('')
  const [sqlAssetOffset, setSqlAssetOffset] = useState(0)
  const [sqlAssetTotal, setSqlAssetTotal] = useState(0)
  const [editingSQLAsset, setEditingSQLAsset] = useState<{
    id: string
    title: string
    description: string
    tags: string
  } | null>(null)

  const [form, setForm] = useState({
    name: '',
    source_type: 'postgres' as DatabaseType,
    host_mode: 'local' as DatabaseHostMode,
    host: '127.0.0.1',
    port: 5432,
    database: '',
    username: '',
    password: '',
    jdbc: '',
  })

  const DB_PORTS: Record<DatabaseType, number> = {
    mysql: 3306,
    clickhouse: 9000,
    doris: 9030,
    postgres: 5432,
  }

  const load = async () => {
    try {
      const list = await apiListDatabases(token)
      setItems(Array.isArray(list) ? list : [])
      if (selected) {
        const refreshed = (Array.isArray(list) ? list : []).find((x) => x.id === selected.id)
        if (refreshed) setSelected(refreshed)
      } else if (Array.isArray(list) && list.length) {
        setSelected(list[0])
      }
    } catch (e) {
      console.error('load databases failed', e)
      setItems([])
    }
  }

  const loadSchemaPage = async (
    databaseId: string,
    options: { search?: string; database?: string; offset?: number; append?: boolean } = {},
  ) => {
    const requestId = schemaRequestId.current + 1
    schemaRequestId.current = requestId
    setSchemaLoading(true)
    setSchemaError('')
    try {
      const result = await apiGetDatabaseSchema(token, databaseId, {
        search: options.search,
        database: options.database,
        offset: options.offset || 0,
        limit: SCHEMA_TABLE_PAGE_SIZE,
      })
      if (requestId !== schemaRequestId.current) return
      setSchema((previous) => options.append && previous
        ? { ...result.schema, tables: [...previous.tables, ...(result.schema.tables || [])] }
        : result.schema)
      setSchemaPagination(result.pagination)
    } catch (error) {
      if (requestId !== schemaRequestId.current) return
      setSchemaError(error instanceof Error ? error.message : '读取数据库 Schema 失败')
      if (!options.append) {
        setSchema({ tables: [] })
        setSchemaPagination(null)
      }
    } finally {
      if (requestId === schemaRequestId.current) setSchemaLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  useEffect(() => {
    if (!selected?.id) return
    setSqlAssetSearch('')
    setSqlAssetStatus('')
    setSqlAssetOffset(0)
    setSchemaSearch('')
    setSchemaAppliedSearch('')
    setSchemaDatabase('')
    setSchema(null)
    setSchemaPagination(null)
    void loadSchemaPage(selected.id)
    void apiGetSemanticConfig(token, selected.id)
      .then((x) => setSemanticConfig({
        dimensions: x?.dimensions || {},
        metrics: x?.metrics || {},
        time_macros: x?.time_macros || [],
      }))
      .catch(() => setSemanticConfig({ dimensions: {}, metrics: {}, time_macros: [] }))
    // Load DataAgent V2 knowledge assets
    apiFetch(`/api/v1/metrics?data_source_id=${selected.id}`, token).then((x) => setMetricsList(Array.isArray(x) ? x : (x?.items || []))).catch(() => setMetricsList([]))
    apiFetch(`/api/v1/table-relationships?data_source_id=${selected.id}`, token).then((x) => setRelationshipsList(Array.isArray(x) ? x : (x?.items || []))).catch(() => setRelationshipsList([]))
    apiFetch(`/api/v1/analytical-skills`, token).then((x) => setSkillsList(Array.isArray(x) ? x : (x?.items || []))).catch(() => setSkillsList([]))
    apiGetDatabaseWorkbench(token, selected.id).then(setWorkbench).catch(() => setWorkbench(null))
    apiListResourcePermissions(token, 'data_source', selected.id).then(setPermissions).catch(() => setPermissions([]))
    apiListPermissionSubjects(token).then(setSubjects).catch(() => setSubjects([]))
    apiListSQLAssets(token, selected.id, { limit: SQL_ASSET_PAGE_SIZE })
      .then((result) => {
        setSqlAssets(result.assets || [])
        setSqlAssetSources(result.sources || [])
        setSqlAssetOffset(result.pagination?.offset || 0)
        setSqlAssetTotal(result.pagination?.total || 0)
      })
      .catch(() => {
        setSqlAssets([])
        setSqlAssetSources([])
        setSqlAssetOffset(0)
        setSqlAssetTotal(0)
      })
  }, [selected?.id, token])

  const reloadSQLAssets = async (overrides: { search?: string; status?: SQLAssetItem['status'] | ''; offset?: number } = {}) => {
    if (!selected) return
    const nextSearch = overrides.search ?? sqlAssetSearch
    const nextStatus = overrides.status ?? sqlAssetStatus
    const nextOffset = overrides.offset ?? sqlAssetOffset
    const result = await apiListSQLAssets(token, selected.id, {
      search: nextSearch,
      status: nextStatus,
      offset: nextOffset,
      limit: SQL_ASSET_PAGE_SIZE,
    })
    setSqlAssets(result.assets || [])
    setSqlAssetSources(result.sources || [])
    setSqlAssetOffset(result.pagination?.offset || 0)
    setSqlAssetTotal(result.pagination?.total || 0)
  }

  const uploadSQLAsset = async (file?: File) => {
    if (!selected || !file) return
    setUploadingSQL(true)
    try {
      await apiUploadSQLAsset(token, selected.id, file)
      await reloadSQLAssets({ offset: 0 })
    } catch (error: any) {
      alert(error?.message || '上传 SQL 资产失败')
    } finally {
      setUploadingSQL(false)
    }
  }

  const changeSQLAssetStatus = async (asset: SQLAssetItem, status: SQLAssetItem['status']) => {
    if (!selected) return
    try {
      await apiUpdateSQLAsset(token, selected.id, asset.id, {
        status,
        expected_updated_at: asset.updated_at,
      })
      await reloadSQLAssets()
    } catch (error: any) {
      alert(error?.message || '更新 SQL 资产失败')
    }
  }

  const saveSQLAssetMetadata = async (asset: SQLAssetItem) => {
    if (!selected || editingSQLAsset?.id !== asset.id) return
    try {
      await apiUpdateSQLAsset(token, selected.id, asset.id, {
        title: editingSQLAsset.title,
        description: editingSQLAsset.description,
        tags: editingSQLAsset.tags.split(',').map((item) => item.trim()).filter(Boolean),
        expected_updated_at: asset.updated_at,
      })
      setEditingSQLAsset(null)
      await reloadSQLAssets()
    } catch (error: any) {
      alert(error?.message || '更新 SQL 资产失败')
    }
  }

  const removeSQLAssetSource = async (sourceId: string) => {
    if (!selected) return
    if (!window.confirm('删除该源文件及其全部 SQL 资产？')) return
    await apiDeleteSQLAssetSource(token, selected.id, sourceId)
    await reloadSQLAssets()
  }

  const validateWorkbench = async () => {
    if (!selected) return
    setValidating(true)
    try { setWorkbench(await apiValidateDatabase(token, selected.id)); await load() }
    catch (e: any) { alert(e?.message || '验证失败') }
    finally { setValidating(false) }
  }

  const grantPermission = async () => {
    if (!selected || !grantUserId) return
    await apiGrantResourcePermission(token, { subject_user_id: grantUserId, resource_type: 'data_source', resource_id: selected.id, permission: grantLevel })
    setPermissions(await apiListResourcePermissions(token, 'data_source', selected.id))
  }

  useEffect(() => {
    setForm((f) => ({
      ...f,
      port: DB_PORTS[f.source_type],
      host: f.host_mode === 'local' && !f.host.trim() ? getDefaultHostForMode('local') : f.host,
      jdbc: buildJdbc(f.source_type, f.host || getDefaultHostForMode(f.host_mode), DB_PORTS[f.source_type], f.database, getDefaultJdbcParams(f.source_type)),
    }))
  }, [form.source_type])

  const beginCreate = () => {
    setEditingId(null)
    setForm({ name: '', source_type: 'mysql', host_mode: 'local', host: getDefaultHostForMode('local'), port: DB_PORTS.mysql, database: '', username: '', password: '', jdbc: buildJdbc('mysql', getDefaultHostForMode('local'), DB_PORTS.mysql, '', getDefaultJdbcParams('mysql')) })
    setCreating((v) => !v)
  }

  const beginEdit = (item: DataSourceItem) => {
    setEditingId(item.id)
    setCreating(true)
    const host = item.host || getDefaultHostForMode('local')
    const port = item.port || DB_PORTS[item.type as DatabaseType] || 5432
    const database = item.database || ''
    setForm({
      name: item.name || '',
      source_type: (item.type as DatabaseType) || 'mysql',
      host_mode: isLocalHost(host) ? 'local' : 'external',
      host,
      port,
      database,
      username: item.username || '',
      password: '',
      jdbc: buildJdbc((item.type as DatabaseType) || 'mysql', host, port, database),
    })
  }

  const saveAndTest = async () => {
    const parsedHostInput = parseJdbcLikeHostInput(form.host, {
      source_type: form.source_type,
      port: form.port || DB_PORTS[form.source_type],
      database: form.database.trim(),
    })
    const parsedJdbc = parseJdbc(form.jdbc) || parsedHostInput
    const normalizedHost = parsedJdbc?.host?.trim() || form.host.trim() || getDefaultHostForMode(form.host_mode)
    const nextSourceType = parsedJdbc?.source_type || form.source_type
    const nextPort = parsedJdbc?.port || form.port || DB_PORTS[nextSourceType]
    const nextDatabase = parsedJdbc?.database?.trim() || form.database.trim()
    if (!form.name.trim() || !normalizedHost || !form.username.trim() || !form.password.trim() || (nextSourceType !== 'clickhouse' && !nextDatabase)) {
      alert(nextSourceType === 'clickhouse' ? '请填写连接别名、主机、端口、账号和密码；ClickHouse 可不指定数据库' : '请填写完整的本机 / 宿主机 / 外部数据库连接信息')
      return
    }
    if (!isAllowedDatabaseHost(normalizedHost)) {
      alert('仅支持本机 / 宿主机 / 外部数据库地址，不能使用 Docker 内部主机名')
      return
    }
    setSaving(true)
    try {
      const payload = {
        name: form.name.trim(),
        source_type: nextSourceType,
        port: nextPort,
        host: normalizedHost,
        database: nextDatabase,
        username: form.username.trim(),
        password: form.password,
      }
      const resp = editingId ? await apiUpdateDatabase(token, editingId, payload) : await apiCreateDatabase(token, payload)
      const id = editingId || resp.id
      setCreating(false)
      setEditingId(null)
      setForm({ name: '', source_type: 'mysql', host_mode: 'local', host: getDefaultHostForMode('local'), port: DB_PORTS.mysql, database: '', username: '', password: '', jdbc: buildJdbc('mysql', getDefaultHostForMode('local'), DB_PORTS.mysql, '', getDefaultJdbcParams('mysql')) })
      await load()
      try {
        const test = await apiTestDatabaseConnection(token, id)
        if (test.ok) {
          const sync = await apiSyncDatabaseSchema(token, id)
          alert(sync.metadata_warning || '保存成功，连接测试通过并已同步 Schema，可直接绑定 Project 使用')
        } else {
          alert(`保存成功，但连接失败：${test.error || 'unknown'}`)
        }
      } catch (e: any) {
        alert(`保存成功，但连接测试或 Schema 同步失败: ${e?.message || 'unknown'}`)
      }
      await load() // Refresh status
    } catch (e: any) {
      alert(e?.message || '保存数据库失败')
    } finally {
      setSaving(false)
    }
  }

  const runQuery = async (clarifyContext?: string) => {
    if (!selected) return
    const payload: any = { question }
    if (querySessionId) payload.session_id = querySessionId
    if (clarifyContext) payload.clarify_context = clarifyContext
    if (sessionContext) payload.session_context = sessionContext

    const out = await apiDatabaseQuery(token, selected.id, payload)

    if (out.session_id) setQuerySessionId(out.session_id)
    if (out.session_context) setSessionContext(out.session_context)

    setQueryHistory(prev => [...prev, {
      question: clarifyContext ? `(补充) ${clarifyContext}` : question,
      answer: out.answer,
      isClarification: !!out.needs_clarification,
    }])

    setQueryOutput({
      answer: out.answer,
      summary: out.summary,
      sql: out.sql,
      rows: out.rows,
      insights: out.insights,
      statistical_report: out.statistical_report,
      visualization_config: out.visualization_config,
      verification_report: out.verification_report,
      confidence: out.confidence,
      session_id: out.session_id,
      needs_clarification: out.needs_clarification,
      clarification: out.clarification,
      draft_id: out.draft_id,
      draft_status: out.draft?.status,
      candidates: out.candidates || out.draft?.candidates || [],
    })
  }

  const executeDraft = async (candidateIds: string[] = [], executeAll = false, retryFailed = false) => {
    if (!selected || !queryOutput?.draft_id) return
    const executionKey = executeAll ? 'all' : candidateIds[0]
    setExecutingCandidate(executionKey)
    try {
      const draft = await apiExecuteSQLDraft(token, selected.id, queryOutput.draft_id, {
        candidate_ids: candidateIds,
        execute_all: executeAll,
        retry_failed: retryFailed,
      })
      const candidates = draft.candidates || []
      const completed = candidates.find((item) => item.execution_status === 'completed')
      setQueryOutput((previous) => previous ? {
        ...previous,
        answer: draft.status === 'completed' ? 'SQL 执行完成。' : 'SQL 执行结束，部分候选执行失败。',
        summary: `${candidates.filter((item) => item.execution_status === 'completed').length} 条 SQL 执行成功`,
        sql: completed?.sql || previous.sql,
        rows: completed?.rows || [],
        draft_status: draft.status,
        candidates,
      } : previous)
    } catch (error: any) {
      alert(error?.message || '执行 SQL 草案失败')
    } finally {
      setExecutingCandidate(null)
    }
  }

  const refreshDraft = async () => {
    if (!selected || !queryOutput?.draft_id) return
    try {
      const draft = await apiGetSQLDraft(token, selected.id, queryOutput.draft_id)
      const completed = draft.candidates?.find((item) => item.execution_status === 'completed')
      setQueryOutput((previous) => previous ? {
        ...previous,
        sql: completed?.sql || previous.sql,
        rows: completed?.rows || previous.rows,
        draft_status: draft.status,
        candidates: draft.candidates || [],
      } : previous)
    } catch (error: any) {
      alert(error?.message || '刷新 SQL 草案失败')
    }
  }

  const testConn = async () => {
    if (!selected) return
    const out = await apiTestDatabaseConnection(token, selected.id)
    alert(out.ok ? '连接成功' : `连接失败: ${out.error || 'unknown'}`)
    await load()
  }

  const syncSchema = async () => {
    if (!selected || schemaSyncing) return
    setSchemaSyncing(true)
    setSchemaError('')
    try {
      const sync = await apiSyncDatabaseSchema(token, selected.id)
      setSchemaSearch('')
      setSchemaAppliedSearch('')
      setSchemaDatabase('')
      await loadSchemaPage(selected.id)
      setActiveTab('tables')
      await load()
      alert(sync.metadata_warning || `Schema 已同步，库数: ${sync.database_count || 0}，表数: ${sync.tables_truncated ? '至少 ' : ''}${sync.table_count || 0}`)
    } catch (error) {
      setSchemaError(error instanceof Error ? error.message : '同步数据库 Schema 失败')
    } finally {
      setSchemaSyncing(false)
    }
  }

  const runAnalysis = async () => {
    if (!selected) return
    const out = await apiAnalyzeDatabase(token, selected.id)
    setAnalysis(out)
  }

  const removeDb = async (id: string) => {
    await apiDeleteDatabase(token, id)
    if (selected?.id === id) setSelected(null)
    await load()
  }

  const handleAutoExtractSemantic = async () => {
    if (!selected) return
    try {
      const result = await apiAutoExtractSemantic(token, selected.id)
      setSemanticConfig({
        dimensions: result?.dimensions || {},
        metrics: result?.metrics || {},
        time_macros: result?.time_macros || [],
      })
      alert(`自动提取完成：${Object.keys(result?.dimensions || {}).length} 个维度，${Object.keys(result?.metrics || {}).length} 个度量`)
    } catch (e: any) {
      alert(`自动提取失败: ${e?.message || 'unknown'}`)
    }
  }

  const handleSaveSemanticConfig = async () => {
    if (!selected) return
    try {
      await apiUpdateSemanticConfig(token, selected.id, semanticConfig)
      alert('语义配置已保存')
    } catch (e: any) {
      alert(`保存失败: ${e?.message || 'unknown'}`)
    }
  }

  const addDimension = () => {
    if (!editingDimension.name.trim() || !editingDimension.column.trim()) return
    const next = { ...semanticConfig.dimensions }
    next[editingDimension.name.trim()] = {
      column: editingDimension.column.trim(),
      table: editingDimension.table.trim() || schema?.tables?.[0]?.name || '',
    }
    setSemanticConfig({ ...semanticConfig, dimensions: next })
    setEditingDimension({ name: '', column: '', table: '' })
  }

  const removeDimension = (key: string) => {
    const next = { ...semanticConfig.dimensions }
    delete next[key]
    setSemanticConfig({ ...semanticConfig, dimensions: next })
  }

  const addMetric = () => {
    if (!editingMetric.name.trim() || !editingMetric.expression.trim()) return
    const next = { ...semanticConfig.metrics }
    next[editingMetric.name.trim()] = editingMetric.expression.trim()
    setSemanticConfig({ ...semanticConfig, metrics: next })
    setEditingMetric({ name: '', expression: '' })
  }

  const removeMetric = (key: string) => {
    const next = { ...semanticConfig.metrics }
    delete next[key]
    setSemanticConfig({ ...semanticConfig, metrics: next })
  }

  const addTimeMacro = () => {
    if (!editingTimeMacro.keyword.trim() || !editingTimeMacro.column.trim()) return
    const next = [...semanticConfig.time_macros, { ...editingTimeMacro }]
    setSemanticConfig({ ...semanticConfig, time_macros: next })
    setEditingTimeMacro({ keyword: '', column: '', days: 7 })
  }

  const removeTimeMacro = (index: number) => {
    const next = [...semanticConfig.time_macros]
    next.splice(index, 1)
    setSemanticConfig({ ...semanticConfig, time_macros: next })
  }

  const columns = useMemo(() => {
    if (!queryOutput?.rows?.length) return []
    return Object.keys(queryOutput.rows[0] || {})
  }, [queryOutput])

  return (
    <div className="flex flex-col h-screen bg-[var(--bg)] text-[var(--text)]">
      <div className="flex items-center gap-3 px-6 h-14 border-b border-[var(--border)]">
        <button onClick={onBack} className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
        <h1 className="text-sm font-semibold inline-flex items-center gap-2"><Database size={16} /> 数据库</h1>
      </div>

      <div className="grid grid-cols-12 gap-4 p-4 flex-1 overflow-hidden">
        <div className="col-span-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 overflow-y-auto">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold">数据库列表</h2>
            <button className="px-2 py-1 rounded border text-xs inline-flex items-center gap-1" onClick={beginCreate}><Plus size={12} /> 添加</button>
          </div>

          {creating ? (
            <div className="space-y-2 mb-3 rounded border border-[var(--border)] p-2">
              <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
                <span>{editingId ? '编辑数据库' : '新建数据库'}</span>
                <button className="inline-flex items-center gap-1 rounded border px-2 py-1" onClick={() => { setCreating(false); setEditingId(null) }}>取消</button>
              </div>
              <input className="w-full rounded border border-[var(--border)] px-2 py-1 text-xs bg-transparent" placeholder="别名" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              <div className="text-[11px] text-[var(--text-secondary)]">
                示例 MySQL：`127.0.0.1` / `root` / `123456` / `test_db`
              </div>
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 py-2 text-[11px] text-[var(--text-secondary)] space-y-1">
                <div>仅支持连接本机/宿主机或外部链接数据库，不提供 Docker 内数据库创建入口。</div>
              </div>
              <DatabaseTypeSelect
                value={form.source_type}
                onChange={(source_type) => setForm({ ...form, source_type, port: DB_PORTS[source_type] })}
              />
              <div className="grid grid-cols-2 gap-2">
                {DATABASE_HOST_MODE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setForm((f) => {
                      const host = getDefaultHostForMode(opt.value)
                      return {
                        ...f,
                        host_mode: opt.value,
                        host,
                        jdbc: buildJdbc(f.source_type, host || f.host, f.port, f.database, getDefaultJdbcParams(f.source_type)),
                      }
                    })}
                    className={`rounded-xl border px-3 py-2 text-left text-xs ${form.host_mode === opt.value ? 'border-[var(--accent)] bg-[var(--accent-dim)]' : 'border-[var(--border)] bg-[var(--surface-raised)]'}`}
                  >
                    <div className="font-semibold">{opt.label}</div>
                    <div className="mt-0.5 text-[11px] text-[var(--text-secondary)]">{opt.hint}</div>
                  </button>
                ))}
              </div>
              <input
                className="w-full rounded border border-[var(--border)] px-2 py-1 text-xs bg-transparent"
                placeholder={form.host_mode === 'local' ? 'localhost / 127.0.0.1 / host.docker.internal / 宿主机IP' : '外部主机名 / IP'}
                value={form.host}
                onChange={(e) => setForm((f) => {
                  const rawHost = e.target.value
                  const parsedHostInput = parseJdbcLikeHostInput(rawHost, {
                    source_type: f.source_type,
                    port: f.port,
                    database: f.database.trim(),
                  })
                  if (parsedHostInput) {
                    return {
                      ...f,
                      source_type: parsedHostInput.source_type,
                      host_mode: parsedHostInput.host_mode,
                      host: parsedHostInput.host,
                      port: parsedHostInput.port,
                      database: parsedHostInput.database,
                      jdbc: parsedHostInput.jdbc,
                    }
                  }
                  return {
                    ...f,
                    host: rawHost,
                    jdbc: buildJdbc(f.source_type, rawHost || getDefaultHostForMode(f.host_mode), f.port, f.database, getDefaultJdbcParams(f.source_type)),
                  }
                })}
              />
              <input className="w-full rounded border border-[var(--border)] px-2 py-1 text-xs bg-transparent" placeholder="port" type="number" value={form.port} onChange={(e) => setForm((f) => ({ ...f, port: Number(e.target.value), jdbc: buildJdbc(f.source_type, f.host || getDefaultHostForMode(f.host_mode), Number(e.target.value), f.database, getDefaultJdbcParams(f.source_type)) }))} />
              <input className="w-full rounded border border-[var(--border)] px-2 py-1 text-xs bg-transparent" placeholder={form.source_type === 'clickhouse' ? '数据库名（可留空，连接后覆盖 ods / dwd）' : '数据库名'} value={form.database} onChange={(e) => setForm((f) => ({ ...f, database: e.target.value, jdbc: buildJdbc(f.source_type, f.host || getDefaultHostForMode(f.host_mode), f.port, e.target.value, getDefaultJdbcParams(f.source_type)) }))} />
              <input className="w-full rounded border border-[var(--border)] px-2 py-1 text-xs bg-transparent" placeholder="username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
              <input className="w-full rounded border border-[var(--border)] px-2 py-1 text-xs bg-transparent" placeholder="password" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
              <label className="block text-[11px] text-[var(--text-secondary)]">JDBC 地址</label>
              <textarea
                className="w-full min-h-[72px] rounded border border-[var(--border)] px-2 py-1 text-xs bg-transparent font-mono"
                value={form.jdbc}
                onChange={(e) => setForm((f) => {
                  const rawJdbc = e.target.value
                  const parsedJdbc = parseJdbc(rawJdbc)
                  if (!parsedJdbc) return { ...f, jdbc: rawJdbc }
                  const nextSourceType = parsedJdbc.source_type
                  const nextHost = parsedJdbc.host.trim()
                  const nextPort = parsedJdbc.port || DB_PORTS[nextSourceType]
                  const nextDatabase = parsedJdbc.database.trim() || f.database
                  return {
                    ...f,
                    source_type: nextSourceType,
                    host_mode: isLocalHost(nextHost) ? 'local' : 'external',
                    host: nextHost,
                    port: nextPort,
                    database: nextDatabase,
                    jdbc: buildJdbc(nextSourceType, nextHost, nextPort, nextDatabase, parsedJdbc.params || getDefaultJdbcParams(nextSourceType)),
                  }
                })}
                placeholder="jdbc:mysql://localhost:3306/test_db?allowPublicKeyRetrieval=true"
              />
              <div className="text-[10px] text-[var(--text-secondary)]">
                你可以直接修改 JDBC 里的 host / port / database / 参数；粘贴完整 JDBC 后会自动同步到表单字段。
              </div>
              <button disabled={saving} className="w-full rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-xs py-1 disabled:opacity-50" onClick={() => void saveAndTest()}>{saving ? '保存中...' : '保存并测试连接'}</button>
            </div>
          ) : null}

          <div className="space-y-2">
            {items.map((x) => (
              <div key={x.id} className={`rounded border p-2 text-xs cursor-pointer ${selected?.id === x.id ? 'border-[var(--accent)]' : 'border-[var(--border)]'}`} onClick={() => {
                setSelected(x)
                localStorage.setItem('opentrace:selected_data_source', JSON.stringify({ id: x.id, name: x.name }))
              }}>
                <div className="flex items-center justify-between">
                  <div className="font-medium">{x.name}</div>
                  <div className="flex items-center gap-1">
                    <button type="button" onClick={(e) => { e.stopPropagation(); beginEdit(x) }} className="text-sky-500"><Pencil size={12} /></button>
                    <button type="button" onClick={(e) => { e.stopPropagation(); void removeDb(x.id) }} className="text-red-500"><Trash2 size={12} /></button>
                  </div>
                </div>
                <div className="text-[var(--text-secondary)]">{x.type} · {x.host}:{x.port}/{x.database || (x.type === 'clickhouse' ? '全部可访问库' : '未指定')}</div>
                <div className="flex items-center gap-1 text-[var(--text-secondary)]">
                  <Circle size={10} className={x.status === 'active' ? 'fill-emerald-500 text-emerald-500' : x.status === 'error' ? 'fill-rose-500 text-rose-500' : 'fill-slate-400 text-slate-400'} />
                  <span>状态：{x.status}</span>
                </div>
                <div className="text-[var(--text-secondary)]">
                  库数：{x.database_count ?? (x.database ? 1 : 0)} · 表数：{x.tables_truncated ? '至少 ' : ''}{x.table_count ?? 0} · 更新：{x.updated_at || '—'} · 上次同步：{x.last_schema_sync_at || x.synced_at || '—'}
                </div>
                {x.metadata_warning ? <div className="mt-1 text-amber-500">{x.metadata_warning}</div> : null}
              </div>
            ))}
          </div>
        </div>

        <div className="col-span-8 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 overflow-y-auto">
          {!selected ? <p className="text-sm text-[var(--text-secondary)]">请选择一个数据库</p> : (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold">{selected.name}</h2>
                <div className="flex gap-2">
                  <button className="px-2 py-1 rounded border text-xs inline-flex items-center gap-1" onClick={() => void testConn()}><PlayCircle size={12} /> 测试连接</button>
                  <button disabled={schemaSyncing} className="px-2 py-1 rounded border text-xs inline-flex items-center gap-1 disabled:opacity-50" onClick={() => void syncSchema()}><RefreshCw size={12} className={schemaSyncing ? 'animate-spin' : ''} /> {schemaSyncing ? '同步中' : '同步Schema'}</button>
                </div>
              </div>

              <div className="flex flex-wrap gap-2 border-b border-[var(--border)] pb-2">
                <TabButton active={activeTab === 'overview'} onClick={() => setActiveTab('overview')} icon={<Gauge size={14} />} label="总览" />
                <TabButton active={activeTab === 'tables'} onClick={() => setActiveTab('tables')} icon={<Table2 size={14} />} label="Tables" />
                <TabButton active={activeTab === 'query'} onClick={() => setActiveTab('query')} icon={<Search size={14} />} label="Query" />
                <TabButton active={activeTab === 'sql_assets'} onClick={() => setActiveTab('sql_assets')} icon={<FileCode2 size={14} />} label="SQL 资产" />
                <TabButton active={activeTab === 'analysis'} onClick={() => setActiveTab('analysis')} icon={<BarChart3 size={14} />} label="Analysis" />
                <TabButton active={activeTab === 'metrics'} onClick={() => setActiveTab('metrics')} icon={<BarChart3 size={14} />} label="指标定义" />
                <TabButton active={activeTab === 'relationships'} onClick={() => setActiveTab('relationships')} icon={<Table2 size={14} />} label="表关系" />
                <TabButton active={activeTab === 'skills'} onClick={() => setActiveTab('skills')} icon={<Zap size={14} />} label="分析技能" />
                <TabButton active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} icon={<Settings2 size={14} />} label="Settings" />
              </div>

              {activeTab === 'overview' ? (
                <div className="space-y-4">
                  <div className="flex items-center justify-between rounded-xl border border-[var(--border)] p-4"><div><div className="text-xs text-[var(--text-secondary)]">数据工作台健康度</div><div className="mt-1 text-3xl font-semibold">{workbench?.health_score ?? 0}<span className="text-sm text-[var(--text-secondary)]">/100</span></div></div><button disabled={validating} onClick={() => void validateWorkbench()} className="rounded-lg bg-[var(--accent)] px-3 py-2 text-xs text-[var(--accent-foreground)] disabled:opacity-50"><ShieldCheck size={13} className="mr-1 inline" />{validating ? '验证中…' : '执行全链路验证'}</button></div>
                  <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[
                    ['连接', workbench?.checks?.connection, workbench?.source?.status || 'unknown'],
                    ['表结构', workbench?.checks?.schema, `${workbench?.schema?.table_count ?? 0} 张表`],
                    ['依赖关系', workbench?.checks?.relationships, `${workbench?.relationships?.verified ?? 0}/${workbench?.relationships?.total ?? 0} 已验证`],
                    ['指标资产', workbench?.checks?.metrics, `${workbench?.metrics?.published ?? 0}/${workbench?.metrics?.total ?? 0} 已发布`],
                  ].map(([label, ok, detail]) => <div key={String(label)} className="rounded-xl border border-[var(--border)] p-3"><div className={`text-xs ${ok ? 'text-emerald-500' : 'text-amber-500'}`}>{ok ? '✓ 正常' : '○ 待完善'}</div><div className="mt-2 text-sm font-medium">{label}</div><div className="mt-1 text-[11px] text-[var(--text-secondary)]">{detail}</div></div>)}</div>
                  <div className="grid gap-3 md:grid-cols-2"><div className="rounded-xl border border-[var(--border)] p-4"><div className="text-xs font-medium">AI 问数质量</div><div className="mt-3 text-2xl font-semibold">{workbench?.queries?.success_rate == null ? '—' : `${Math.round(workbench.queries.success_rate * 100)}%`}</div><div className="text-[11px] text-[var(--text-secondary)]">累计 {workbench?.queries?.total ?? 0} 次查询</div></div><div className="rounded-xl border border-[var(--border)] p-4"><div className="text-xs font-medium">推荐下一步</div><p className="mt-3 text-xs leading-5 text-[var(--text-secondary)]">{!workbench?.checks?.schema ? '先同步 Schema，生成表结构资产。' : !workbench?.checks?.relationships ? '补充并验证表依赖，减少错误 JOIN。' : !workbench?.checks?.metrics ? '发布业务指标口径，提高问数一致性。' : '资产已就绪，可直接从 Query 或主问答发起分析。'}</p></div></div>
                </div>
              ) : null}

              {activeTab === 'tables' ? (
                <div className="space-y-3">
                  <div className="flex flex-col gap-2 rounded-xl border border-[var(--border)] p-3 lg:flex-row lg:items-center">
                    <label className="relative min-w-0 flex-1">
                      <Search size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
                      <input value={schemaSearch} onChange={(event) => setSchemaSearch(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && selected) { setSchemaAppliedSearch(schemaSearch); void loadSchemaPage(selected.id, { search: schemaSearch, database: schemaDatabase }) } }} placeholder="搜索表名、注释或所属库" aria-label="搜索数据库表" className="h-9 w-full rounded-lg border border-[var(--border)] bg-transparent pl-9 pr-3 text-xs outline-none focus:border-[var(--accent)]" />
                    </label>
                    {(schema?.databases || []).length > 1 ? <select value={schemaDatabase} onChange={(event) => { const database = event.target.value; setSchemaDatabase(database); setSchemaAppliedSearch(schemaSearch); if (selected) void loadSchemaPage(selected.id, { search: schemaSearch, database }) }} aria-label="按数据库筛选" className="h-9 rounded-lg border border-[var(--border)] bg-transparent px-3 text-xs"><option value="">全部数据库</option>{(schema?.databases || []).map((database) => <option key={database} value={database}>{database}</option>)}</select> : null}
                    <button disabled={schemaLoading || !selected} onClick={() => { setSchemaAppliedSearch(schemaSearch); if (selected) void loadSchemaPage(selected.id, { search: schemaSearch, database: schemaDatabase }) }} className="h-9 rounded-lg bg-[var(--accent)] px-4 text-xs font-medium text-[var(--accent-foreground)] disabled:opacity-50">搜索</button>
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-[var(--text-secondary)]">
                    <span>已展示 {(schema?.tables || []).length} / {schemaPagination?.total ?? schema?.table_count ?? 0} 张匹配表{schema?.table_count != null && schemaPagination?.total !== schema.table_count ? ` · 全库 ${schema.tables_truncated ? '至少 ' : ''}${schema.table_count} 张` : ''}</span>
                    <span>每次加载 {SCHEMA_TABLE_PAGE_SIZE} 张，列详情随表返回</span>
                  </div>
                  {schema?.metadata_warning ? <div role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs leading-5 text-amber-500">{schema.metadata_warning}</div> : null}
                  {schemaError ? <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-500">{schemaError}</div> : null}
                  {schemaLoading && (schema?.tables || []).length === 0 ? <div className="rounded-lg border border-dashed border-[var(--border)] p-8 text-center text-xs text-[var(--text-secondary)]">正在读取表目录…</div> : null}
                  {!schemaLoading && !schemaError && (schema?.tables || []).length === 0 ? <div className="rounded-lg border border-dashed border-[var(--border)] p-8 text-center text-xs text-[var(--text-secondary)]">{schemaAppliedSearch || schemaDatabase ? '没有匹配的表，请调整搜索或数据库筛选。' : '暂无 Schema，请先同步。'}</div> : null}
                  {(schema?.tables || []).map((t) => (
                    <details key={t.qualified_name || `${t.database || ''}.${t.name}`} className="rounded border border-[var(--border)] p-2">
                      <summary className="cursor-pointer text-sm font-medium"><span>{t.name}</span>{t.database && t.database !== schema?.schema ? <span className="ml-2 rounded bg-[var(--surface-raised)] px-1.5 py-0.5 text-[10px] font-normal text-[var(--text-secondary)]">{t.database}</span> : null}</summary>
                      {t.comment ? <div className="mt-1 text-xs text-[var(--text-secondary)]">{t.comment}</div> : null}
                      {(t.columns || []).length > 0 ? <div className="mt-2 grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
                        {(t.columns || []).map((c) => (
                          <div key={`${t.qualified_name || t.name}_${c.name}`} className="rounded bg-[var(--surface-raised)] px-2 py-1">
                            {c.name} <span className="text-[var(--text-secondary)]">({c.type})</span>
                            {c.comment ? <div className="text-[10px] text-[var(--text-secondary)]">{c.comment}</div> : null}
                          </div>
                        ))}
                      </div> : <div className="mt-2 text-[11px] text-[var(--text-secondary)]">暂无列详情{schema?.columns_truncated ? '，列元数据同步已达到安全预算。' : '。'}</div>}
                    </details>
                  ))}
                  {schemaPagination?.has_more ? <button disabled={schemaLoading || !selected} onClick={() => { if (selected && schemaPagination.next_offset != null) void loadSchemaPage(selected.id, { search: schemaAppliedSearch, database: schemaDatabase, offset: schemaPagination.next_offset, append: true }) }} className="flex w-full items-center justify-center gap-2 rounded-lg border border-[var(--border)] py-2.5 text-xs hover:border-[var(--accent)] disabled:opacity-50"><RefreshCw size={12} className={schemaLoading ? 'animate-spin' : ''} />{schemaLoading ? '加载中…' : `继续加载（剩余 ${Math.max(0, schemaPagination.total - (schema?.tables || []).length)} 张）`}</button> : null}
                </div>
              ) : null}

              {activeTab === 'sql_assets' ? (
                <div className="space-y-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold">SQL 资产</h3>
                      <div className="mt-1 text-xs text-[var(--text-secondary)]">
                        {sqlAssetSources.length} 个源文件 · {sqlAssetTotal} 条资产
                      </div>
                    </div>
                    <label className="inline-flex cursor-pointer items-center gap-1 rounded border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--surface-raised)]">
                      <Upload size={13} />
                      {uploadingSQL ? '解析中' : '上传 SQL'}
                      <input
                        className="hidden"
                        type="file"
                        accept=".sql,.txt,text/plain,application/sql"
                        disabled={uploadingSQL}
                        onChange={(event) => {
                          const file = event.target.files?.[0]
                          void uploadSQLAsset(file)
                          event.currentTarget.value = ''
                        }}
                      />
                    </label>
                  </div>

                  <form
                    className="flex flex-wrap items-center gap-2"
                    onSubmit={(event) => {
                      event.preventDefault()
                      void reloadSQLAssets({ search: sqlAssetSearch, offset: 0 })
                    }}
                  >
                    <div className="relative min-w-52 flex-1">
                      <Search className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" size={13} />
                      <input
                        value={sqlAssetSearch}
                        onChange={(event) => setSqlAssetSearch(event.target.value)}
                        className="h-8 w-full rounded border border-[var(--border)] bg-transparent pl-7 pr-2 text-xs"
                        placeholder="搜索标题、描述或 SQL"
                      />
                    </div>
                    <select
                      value={sqlAssetStatus}
                      onChange={(event) => {
                        const status = event.target.value as SQLAssetItem['status'] | ''
                        setSqlAssetStatus(status)
                        void reloadSQLAssets({ status, offset: 0 })
                      }}
                      className="h-8 rounded border border-[var(--border)] bg-[var(--surface)] px-2 text-xs"
                    >
                      <option value="">全部状态</option>
                      <option value="draft">草稿</option>
                      <option value="published">已发布</option>
                      <option value="deprecated">已废弃</option>
                      <option value="rejected">已驳回</option>
                    </select>
                    <button
                      className="flex h-8 w-8 items-center justify-center rounded border border-[var(--border)] hover:bg-[var(--surface-raised)]"
                      title="搜索 SQL 资产"
                      type="submit"
                    >
                      <Search size={13} />
                    </button>
                  </form>

                  {sqlAssetSources.length > 0 ? (
                    <div className="space-y-2">
                      <div className="text-xs font-medium">源文件</div>
                      {sqlAssetSources.map((source) => (
                        <div key={source.id} className="flex items-center justify-between rounded border border-[var(--border)] px-3 py-2">
                          <div className="min-w-0">
                            <div className="truncate text-xs font-medium">{source.filename}</div>
                            <div className="mt-0.5 text-[11px] text-[var(--text-secondary)]">
                              v{source.version} · {source.dialect} · {source.statement_count} 条语句
                            </div>
                          </div>
                          <button
                            className="flex h-7 w-7 items-center justify-center rounded hover:bg-red-500/10 hover:text-red-500"
                            title="删除源文件"
                            onClick={() => void removeSQLAssetSource(source.id)}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  <div className="space-y-2">
                    <div className="text-xs font-medium">解析资产</div>
                    {sqlAssets.length === 0 ? (
                      <div className="border-y border-[var(--border)] py-8 text-center text-xs text-[var(--text-secondary)]">暂无 SQL 资产</div>
                    ) : sqlAssets.map((asset) => {
                      const validationPassed = asset.validation_report?.status === 'pass'
                      return (
                        <details key={asset.id} className="rounded border border-[var(--border)] p-3">
                          <summary className="cursor-pointer list-none">
                            <div className="flex items-center justify-between gap-3">
                              <div className="min-w-0">
                                <div className="truncate text-xs font-medium">{asset.title}</div>
                                <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-secondary)]">
                                  <span>{asset.asset_type}</span>
                                  <span>{asset.statement_type}</span>
                                  <span>{asset.tables.join(', ') || '无表引用'}</span>
                                </div>
                              </div>
                              <div className="flex shrink-0 items-center gap-2">
                                <span className={`inline-flex items-center gap-1 text-[11px] ${validationPassed ? 'text-emerald-500' : 'text-amber-500'}`}>
                                  {validationPassed ? <CheckCircle2 size={12} /> : <Circle size={12} />}
                                  {validationPassed ? '校验通过' : '仅供参考'}
                                </span>
                                <span className="rounded bg-[var(--surface-raised)] px-2 py-0.5 text-[11px]">{SQL_ASSET_STATUS_LABELS[asset.status]}</span>
                              </div>
                            </div>
                          </summary>
                          <div className="mt-3 space-y-3 border-t border-[var(--border)] pt-3">
                            {editingSQLAsset?.id === asset.id ? (
                              <div className="grid gap-2">
                                <input
                                  value={editingSQLAsset.title}
                                  onChange={(event) => setEditingSQLAsset({ ...editingSQLAsset, title: event.target.value })}
                                  className="rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs"
                                  maxLength={255}
                                  placeholder="资产标题"
                                />
                                <textarea
                                  value={editingSQLAsset.description}
                                  onChange={(event) => setEditingSQLAsset({ ...editingSQLAsset, description: event.target.value })}
                                  className="min-h-16 resize-y rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs"
                                  maxLength={4000}
                                  placeholder="业务口径与适用范围"
                                />
                                <input
                                  value={editingSQLAsset.tags}
                                  onChange={(event) => setEditingSQLAsset({ ...editingSQLAsset, tags: event.target.value })}
                                  className="rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs"
                                  placeholder="标签，使用逗号分隔"
                                />
                              </div>
                            ) : asset.description || asset.tags.length ? (
                              <div className="space-y-1 text-xs text-[var(--text-secondary)]">
                                {asset.description ? <div>{asset.description}</div> : null}
                                {asset.tags.length ? <div>{asset.tags.join(' · ')}</div> : null}
                              </div>
                            ) : null}
                            <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded border border-[var(--border)] bg-black/20 p-3 text-xs">{asset.sql}</pre>
                            {(asset.validation_report?.errors || []).map((error, index) => (
                              <div key={`${asset.id}_error_${index}`} className="text-xs text-red-400">{error}</div>
                            ))}
                            {(asset.validation_report?.warnings || []).map((warning, index) => (
                              <div key={`${asset.id}_warning_${index}`} className="text-xs text-amber-400">{warning}</div>
                            ))}
                            <div className="flex justify-end gap-2">
                              {editingSQLAsset?.id === asset.id ? (
                                <>
                                  <button className="rounded border border-[var(--border)] px-3 py-1.5 text-xs" onClick={() => setEditingSQLAsset(null)}>取消</button>
                                  <button className="rounded bg-[var(--accent)] px-3 py-1.5 text-xs text-[var(--accent-foreground)]" onClick={() => void saveSQLAssetMetadata(asset)}>保存</button>
                                </>
                              ) : (
                                <button
                                  className="flex h-7 w-7 items-center justify-center rounded border border-[var(--border)]"
                                  title="编辑资产元数据"
                                  onClick={() => setEditingSQLAsset({ id: asset.id, title: asset.title, description: asset.description, tags: asset.tags.join(', ') })}
                                >
                                  <Pencil size={13} />
                                </button>
                              )}
                              {asset.status !== 'published' && asset.executable && validationPassed ? (
                                <button className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs text-[var(--accent-foreground)]" onClick={() => void changeSQLAssetStatus(asset, 'published')}>
                                  <CheckCircle2 size={13} /> 发布
                                </button>
                              ) : null}
                              {asset.status === 'published' ? (
                                <button className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-3 py-1.5 text-xs" onClick={() => void changeSQLAssetStatus(asset, 'deprecated')}>
                                  <Archive size={13} /> 废弃
                                </button>
                              ) : null}
                            </div>
                          </div>
                        </details>
                      )
                    })}
                    {sqlAssetTotal > SQL_ASSET_PAGE_SIZE ? (
                      <div className="flex items-center justify-between border-t border-[var(--border)] pt-2 text-xs text-[var(--text-secondary)]">
                        <span>{sqlAssetOffset + 1}-{Math.min(sqlAssetOffset + sqlAssets.length, sqlAssetTotal)} / {sqlAssetTotal}</span>
                        <div className="flex gap-1">
                          <button
                            className="rounded border border-[var(--border)] px-2 py-1 disabled:opacity-40"
                            disabled={sqlAssetOffset === 0}
                            onClick={() => void reloadSQLAssets({ offset: Math.max(0, sqlAssetOffset - SQL_ASSET_PAGE_SIZE) })}
                          >
                            上一页
                          </button>
                          <button
                            className="rounded border border-[var(--border)] px-2 py-1 disabled:opacity-40"
                            disabled={sqlAssetOffset + sqlAssets.length >= sqlAssetTotal}
                            onClick={() => void reloadSQLAssets({ offset: sqlAssetOffset + SQL_ASSET_PAGE_SIZE })}
                          >
                            下一页
                          </button>
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}

              {activeTab === 'query' ? (
                <div className="rounded border border-[var(--border)] p-3 space-y-2">
                  {/* Conversation history */}
                  {queryHistory.length > 0 ? (
                    <div className="space-y-2 mb-3">
                      {queryHistory.map((h, idx) => (
                        <div key={idx} className={`rounded border p-2 text-xs ${h.isClarification ? 'border-orange-500/50 bg-orange-500/5' : 'border-[var(--border)] bg-[var(--surface-raised)]'}`}>
                          <div className="font-medium mb-1" style={{ color: 'var(--accent)' }}>
                            {h.isClarification ? '需要补充信息' : '查询'}
                          </div>
                          <div className="text-[var(--text-secondary)]">Q: {h.question}</div>
                          <div className="mt-1">{h.answer}</div>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  <input value={question} onChange={(e) => setQuestion(e.target.value)} className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-sm" />
                  <button className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs text-[var(--accent-foreground)]" onClick={() => void runQuery()}>
                    <FileCode2 size={13} /> 生成 SQL 草案
                  </button>
                  {queryOutput ? (
                    <>
                      {/* Clarification card — shown when query is too vague */}
                      {queryOutput.needs_clarification && queryOutput.clarification ? (
                        <div className="rounded border border-orange-500/50 p-3 bg-orange-500/5 space-y-2">
                          <div className="text-xs font-medium text-orange-400">需要补充信息</div>
                          <MarkdownMessage content={queryOutput.clarification.question_text || queryOutput.answer} />
                          {queryOutput.clarification.suggested_options?.length > 0 ? (
                            <div className="space-y-1">
                              <div className="text-xs text-[var(--text-secondary)]">你可以尝试以下方向：</div>
                              <div className="flex flex-wrap gap-1">
                                {queryOutput.clarification.suggested_options.map((opt: string, i: number) => (
                                  <button
                                    key={i}
                                    className="px-2 py-1 rounded text-xs border border-[var(--border)] hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)] transition-colors cursor-pointer"
                                    onClick={() => {
                                      setQuestion(opt)
                                      setTimeout(() => runQuery(opt), 50)
                                    }}
                                  >
                                    {opt}
                                  </button>
                                ))}
                              </div>
                            </div>
                          ) : null}
                          {queryOutput.clarification.missing_entities?.length > 0 ? (
                            <div className="flex items-center gap-1 flex-wrap">
                              <span className="text-xs text-[var(--text-secondary)]">缺失信息：</span>
                              {queryOutput.clarification.missing_entities.map((e: string, i: number) => (
                                <span key={i} className="px-1.5 py-0.5 rounded text-[10px] bg-[var(--surface-raised)] border border-[var(--border)]">{e}</span>
                              ))}
                            </div>
                          ) : null}
                          <div className="text-xs text-[var(--text-secondary)]">
                            你也可以在输入框中修改问题后重新提交
                          </div>
                        </div>
                      ) : null}

                      {/* 1. 草案或执行状态 */}
                      {queryOutput.answer ? (
                        <div className="rounded border border-[var(--border)] p-3 bg-[var(--surface-raised)]">
                          <div className="text-xs font-medium mb-2" style={{ color: 'var(--accent)' }}>状态</div>
                          <MarkdownMessage content={queryOutput.answer} />
                        </div>
                      ) : (
                        <div className="text-xs text-[var(--text-secondary)]">{queryOutput.summary}</div>
                      )}

                      {/* 2. 持久化 SQL 候选 */}
                      {queryOutput.candidates?.length ? (
                        <div className="space-y-2">
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-xs font-medium">SQL 候选</div>
                            <div className="flex items-center gap-1">
                              {queryOutput.draft_status === 'executing' ? (
                                <button
                                  className="flex h-7 w-7 items-center justify-center rounded border border-[var(--border)]"
                                  title="刷新执行状态"
                                  onClick={() => void refreshDraft()}
                                >
                                  <RefreshCw size={12} />
                                </button>
                              ) : null}
                              {queryOutput.candidates.length > 1 ? (
                                <button
                                  className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2 py-1 text-xs disabled:opacity-50"
                                  disabled={executingCandidate !== null}
                                  onClick={() => void executeDraft([], true, !!queryOutput.candidates?.some((item) => item.execution_status === 'failed'))}
                                >
                                  <PlayCircle size={12} /> {executingCandidate === 'all' ? '执行中' : queryOutput.candidates.some((item) => item.execution_status === 'failed') ? '重试失败项' : '执行全部'}
                                </button>
                              ) : null}
                            </div>
                          </div>
                          {queryOutput.candidates.map((candidate) => (
                            <div key={candidate.id} className="rounded border border-[var(--border)] p-3">
                              <div className="flex items-center justify-between gap-2">
                                <div>
                                  <div className="text-xs font-medium">{candidate.title}</div>
                                  <div className="mt-0.5 text-[11px] text-[var(--text-secondary)]">{candidate.description}</div>
                                </div>
                                <div className="flex items-center gap-2">
                                  <span className="text-[11px] text-[var(--text-secondary)]">{SQL_EXECUTION_STATUS_LABELS[candidate.execution_status]}</span>
                                  <button
                                    className="flex h-7 w-7 items-center justify-center rounded bg-[var(--accent)] text-[var(--accent-foreground)] disabled:opacity-50"
                                    title={candidate.execution_status === 'failed' ? `重试候选 ${candidate.position}` : `执行候选 ${candidate.position}`}
                                    disabled={executingCandidate !== null || candidate.execution_status === 'completed'}
                                    onClick={() => void executeDraft([candidate.id], false, candidate.execution_status === 'failed')}
                                  >
                                    <PlayCircle size={13} />
                                  </button>
                                </div>
                              </div>
                              <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded border border-[var(--border)] bg-black/20 p-2 text-xs">{candidate.sql}</pre>
                              {candidate.error_message ? <div className="mt-2 text-xs text-red-400">{candidate.error_message}</div> : null}
                              {candidate.execution_status === 'completed' ? (
                                <div className="mt-2 text-xs text-emerald-500">
                                  返回 {candidate.row_count} 行{candidate.result_truncated ? `，保留前 ${candidate.returned_row_count} 行` : ''}
                                </div>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      ) : queryOutput.sql ? (
                        <details open>
                          <summary className="cursor-pointer text-xs font-medium" style={{ color: 'var(--accent)' }}>SQL</summary>
                          <pre className="text-xs whitespace-pre-wrap rounded border border-[var(--border)] p-2 bg-black/20 mt-1">{queryOutput.sql}</pre>
                        </details>
                      ) : null}

                      {/* 3. 结果表格 */}
                      {queryOutput.rows.length > 0 ? <div className="overflow-x-auto rounded border border-[var(--border)]">
                        <table className="min-w-full text-xs">
                          <thead className="bg-[var(--surface-raised)]">
                            <tr>{columns.map((c) => <th key={c} className="px-2 py-1 text-left">{c}</th>)}</tr>
                          </thead>
                          <tbody>
                            {queryOutput.rows.slice(0, 20).map((r, idx) => (
                              <tr key={idx} className="border-t border-[var(--border)]">
                                {columns.map((c) => <td key={`${idx}_${c}`} className="px-2 py-1">{String((r as any)[c] ?? '')}</td>)}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div> : null}
                      {queryOutput.rows.length > 20 ? (
                        <div className="text-xs text-[var(--text-secondary)]">仅显示前 20 行，共 {queryOutput.rows.length} 行</div>
                      ) : null}

                      {/* 4. 洞察区 */}
                      {queryOutput.insights ? (
                        <div className="rounded border border-[var(--border)] p-3 space-y-2">
                          <div className="text-xs font-medium" style={{ color: 'var(--accent)' }}>数据洞察</div>
                          {queryOutput.insights.observations?.length > 0 ? (
                            <div className="space-y-1">
                              <div className="text-xs text-[var(--text-secondary)]">关键发现</div>
                              {queryOutput.insights.observations.map((o: string, i: number) => (
                                <div key={i} className="text-xs">• {o}</div>
                              ))}
                            </div>
                          ) : null}
                          {queryOutput.insights.recommendations?.length > 0 ? (
                            <div className="space-y-1">
                              <div className="text-xs text-[var(--text-secondary)]">建议</div>
                              {queryOutput.insights.recommendations.map((r: string, i: number) => (
                                <div key={i} className="text-xs">→ {r}</div>
                              ))}
                            </div>
                          ) : null}
                          {queryOutput.insights.patterns?.length > 0 ? (
                            <div className="space-y-1">
                              <div className="text-xs text-[var(--text-secondary)]">模式</div>
                              {queryOutput.insights.patterns.map((p: string, i: number) => (
                                <div key={i} className="text-xs">• {p}</div>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      ) : null}

                      {/* 5. 统计分析区 */}
                      {queryOutput.statistical_report ? (
                        <div className="rounded border border-[var(--border)] p-3 space-y-2">
                          <div className="text-xs font-medium" style={{ color: 'var(--accent)' }}>统计分析</div>
                          {queryOutput.statistical_report.trends && Object.keys(queryOutput.statistical_report.trends).length > 0 ? (
                            <div className="space-y-1">
                              <div className="text-xs text-[var(--text-secondary)]">趋势</div>
                              {Object.entries(queryOutput.statistical_report.trends as Record<string, any>).map(([col, t]) => (
                                <div key={col} className="text-xs">
                                  • {col}: {t.direction} ({t.strength_label}), 变化: {t.change_pct}%
                                </div>
                              ))}
                            </div>
                          ) : null}
                          {queryOutput.statistical_report.outliers ? (
                            (() => {
                              const totalOutliers = Object.values(queryOutput.statistical_report.outliers as Record<string, any[]>).reduce((sum: number, v: any[]) => sum + v.length, 0)
                              return totalOutliers > 0 ? (
                                <div className="text-xs">• 检测到 {totalOutliers} 个异常值</div>
                              ) : null
                            })()
                          ) : null}
                        </div>
                      ) : null}

                      {/* 6. 图表建议 */}
                      {queryOutput.visualization_config ? (
                        <div className="rounded border border-[var(--border)] p-3 space-y-1">
                          <div className="text-xs font-medium" style={{ color: 'var(--accent)' }}>图表建议</div>
                          <div className="text-xs">
                            推荐图表: {queryOutput.visualization_config.chart_type}
                            {queryOutput.visualization_config.title ? ` - ${queryOutput.visualization_config.title}` : ''}
                          </div>
                          {queryOutput.visualization_config.alternatives?.length > 0 ? (
                            <div className="text-xs text-[var(--text-secondary)]">
                              备选: {queryOutput.visualization_config.alternatives.join(', ')}
                            </div>
                          ) : null}
                          <button
                            className="px-3 py-1 rounded border text-xs mt-1"
                            onClick={() => requestPrefill(`请基于以下数据绘制图表并分析：\n${JSON.stringify(queryOutput.rows.slice(0, 20), null, 2)}`)}
                          >
                            在对话中生成图表
                          </button>
                        </div>
                      ) : (
                        <button
                          className="px-3 py-1 rounded border text-xs"
                          onClick={() => requestPrefill(`请基于以下数据绘制图表并分析：\n${JSON.stringify(queryOutput.rows.slice(0, 20), null, 2)}`)}
                        >
                          生成图表
                        </button>
                      )}

                      {/* 7. 元信息 */}
                      {queryOutput.confidence != null ? (
                        <div className="flex items-center gap-4 text-xs text-[var(--text-secondary)]">
                          <span>置信度: {(queryOutput.confidence * 100).toFixed(0)}%</span>
                          {queryOutput.verification_report ? (
                            <span>校验: {queryOutput.verification_report.status || queryOutput.verification_report}</span>
                          ) : null}
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <div className="text-xs text-[var(--text-secondary)]">查询结果会显示在这里</div>
                  )}
                </div>
              ) : null}

              {activeTab === 'analysis' ? (
                <div className="rounded border border-[var(--border)] p-3 space-y-3">
                  <button className="px-3 py-1.5 rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-xs" onClick={() => void runAnalysis()}>运行分析</button>

                  <div className="text-sm font-medium">{analysis?.summary || '点击运行分析'}</div>

                  {(analysis?.charts || []).length > 0 ? (
                    <div className="grid grid-cols-2 gap-2">
                      {(analysis?.charts || []).map((c: any, idx: number) => (
                        <div key={idx} className="rounded border border-[var(--border)] bg-[var(--surface-raised)] px-3 py-2">
                          <div className="text-[11px] text-[var(--text-secondary)]">{c?.title || `指标 ${idx + 1}`}</div>
                          <div className="mt-1 text-lg font-semibold">{String(c?.value ?? '-')}</div>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {(analysis?.insights || []).length > 0 ? (
                    <ul className="list-disc pl-5 text-xs text-[var(--text-secondary)] space-y-1">
                      {(analysis?.insights || []).map((x, idx) => <li key={idx}>{x}</li>)}
                    </ul>
                  ) : null}

                  {(analysis?.tables || []).length > 0 ? (
                    <div className="space-y-2">
                      {(analysis?.tables || []).map((t, idx) => (
                        <details key={idx} className="rounded border border-[var(--border)] p-2">
                          <summary className="cursor-pointer text-xs font-medium">{t?.title || `表 ${idx + 1}`}</summary>
                          {t?.sql ? <pre className="mt-2 text-xs whitespace-pre-wrap rounded border border-[var(--border)] p-2 bg-black/20">{t.sql}</pre> : null}
                        </details>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {activeTab === 'metrics' ? (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold">指标定义</h3>
                    <span className="text-xs text-[var(--text-secondary)]">{metricsList.length} 个</span>
                  </div>
                  {metricsList.length === 0 ? (
                    <p className="text-xs text-[var(--text-secondary)] py-4 text-center">该数据源暂无指标定义。可在"Settings → 语义层配置"中先配置度量映射，或通过管理 API 创建。</p>
                  ) : (
                    <div className="space-y-2">
                      {metricsList.map((m: any, idx: number) => (
                        <div key={m.id || idx} className="rounded border border-[var(--border)] p-3 space-y-1">
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-medium">{m.name}</span>
                            {m.status ? <span className={`px-1.5 py-0.5 rounded text-[10px] ${m.status === 'published' ? 'bg-green-500/20 text-green-400' : m.status === 'draft' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-gray-500/20 text-gray-400'}`}>{m.status}</span> : null}
                          </div>
                          {m.formula ? <div className="text-xs font-mono text-[var(--text-secondary)]">{m.formula}</div> : null}
                          {m.business_definition ? <p className="text-xs text-[var(--text-secondary)]">{m.business_definition}</p> : null}
                          {m.unit ? <span className="text-[10px] text-[var(--text-secondary)]">单位: {m.unit}</span> : null}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : null}

              {activeTab === 'relationships' ? (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold">表关系</h3>
                    <span className="text-xs text-[var(--text-secondary)]">{relationshipsList.length} 条</span>
                  </div>
                  {relationshipsList.length === 0 ? (
                    <p className="text-xs text-[var(--text-secondary)] py-4 text-center">该数据源暂无表关系定义。可通过管理 API 或运行 scripts/sync_table_relationships.py 引导脚本创建。</p>
                  ) : (
                    <div className="space-y-2">
                      {relationshipsList.map((r: any, idx: number) => (
                        <div key={r.id || idx} className="rounded border border-[var(--border)] p-2 text-xs space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-medium">{r.left_table}.{r.left_column}</span>
                            <span className="text-[var(--accent)]">&rarr;</span>
                            <span className="font-mono font-medium">{r.right_table}.{r.right_column}</span>
                            <span className="text-[var(--text-secondary)]">({r.join_type || 'LEFT'})</span>
                          </div>
                          <div className="flex gap-3">
                            {r.cardinality ? <span className="text-[var(--text-secondary)]">基数: {r.cardinality}</span> : null}
                            {r.is_verified ? <span className="text-green-400">已验证</span> : <span className="text-yellow-400">未验证</span>}
                            {r.amplification_risk ? <span className={r.amplification_risk === 'high' ? 'text-red-400' : 'text-[var(--text-secondary)]'}>放大风险: {r.amplification_risk}</span> : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : null}

              {activeTab === 'skills' ? (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold">分析技能库</h3>
                    <span className="text-xs text-[var(--text-secondary)]">{skillsList.length} 个</span>
                  </div>
                  {skillsList.length === 0 ? (
                    <p className="text-xs text-[var(--text-secondary)] py-4 text-center">暂无分析技能定义。可通过管理 API 创建或初始化预置技能。</p>
                  ) : (
                    <div className="space-y-2">
                      {skillsList.map((s: any, idx: number) => (
                        <div key={s.id || idx} className="rounded border border-[var(--border)] p-3 space-y-1">
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-medium">{s.name}</span>
                            <span className={`px-1.5 py-0.5 rounded text-[10px] ${s.status === 'active' ? 'bg-green-500/20 text-green-400' : 'bg-gray-500/20 text-gray-400'}`}>{s.status || 'active'}</span>
                          </div>
                          {s.description ? <p className="text-xs text-[var(--text-secondary)]">{s.description}</p> : null}
                          <div className="flex gap-2 text-xs">
                            {s.skill_type ? <span className="text-[var(--text-secondary)]">类型: {s.skill_type}</span> : null}
                            {s.visualization_hint ? <span className="text-[var(--text-secondary)]">图表: {s.visualization_hint}</span> : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : null}

              {activeTab === 'settings' ? (
                <div className="space-y-4">
                  <div className="rounded border border-[var(--border)] p-3 text-xs text-[var(--text-secondary)] space-y-2">
                    <h3 className="text-sm font-semibold text-[var(--text)] mb-2">连接信息</h3>
                    <div>类型：{selected.type}</div>
                    <div>主机：{selected.host}</div>
                    <div>端口：{selected.port}</div>
                    <div>数据库：{selected.database || (selected.type === 'clickhouse' ? '全部可访问库' : '未指定')}</div>
                    <div>用户名：{selected.username}</div>
                  </div>

                  <div className="rounded border border-[var(--border)] p-4 space-y-3">
                    <h3 className="inline-flex items-center gap-2 text-sm font-semibold"><Users size={14} />共享与权限</h3>
                    <p className="text-xs text-[var(--text-secondary)]">view 仅查看资产；query 可执行问数；edit 可维护 Schema、指标和关系；admin 可继续授权。</p>
                    <div className="grid gap-2 sm:grid-cols-[1fr_120px_auto]"><select value={grantUserId} onChange={(e) => setGrantUserId(e.target.value)} className="rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs"><option value="">选择用户</option>{subjects.map((user) => <option key={user.id} value={user.id}>{user.display_name || user.email} · {user.email}</option>)}</select><select value={grantLevel} onChange={(e) => setGrantLevel(e.target.value as typeof grantLevel)} className="rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs"><option value="view">view</option><option value="query">query</option><option value="edit">edit</option><option value="admin">admin</option></select><button onClick={() => void grantPermission()} className="rounded bg-[var(--accent)] px-3 py-1.5 text-xs text-[var(--accent-foreground)]">授权</button></div>
                    <div className="space-y-2">{permissions.map((permission) => <div key={permission.id} className="flex items-center rounded bg-[var(--surface-raised)] px-3 py-2 text-xs"><span className="min-w-0 flex-1 truncate">{permission.subject_email}</span><span className="mr-3 rounded-full border border-[var(--border)] px-2 py-0.5">{permission.permission}</span><button onClick={async () => { await apiRevokeResourcePermission(token, permission.id); setPermissions((items) => items.filter((item) => item.id !== permission.id)) }} className="text-red-500"><Trash2 size={12} /></button></div>)}</div>
                  </div>

                  <div className="rounded border border-[var(--border)] p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-semibold inline-flex items-center gap-1.5"><Zap size={14} /> 语义层配置</h3>
                      <button onClick={() => void handleAutoExtractSemantic()} className="px-2 py-1 rounded bg-[var(--accent-dim)] text-[var(--accent)] text-xs inline-flex items-center gap-1"><Zap size={12} /> 自动提取</button>
                    </div>
                    <p className="text-xs text-[var(--text-secondary)]">配置业务术语到数据库字段的映射，提升 Text2SQL 准确度。</p>

                    {/* Dimensions */}
                    <div className="space-y-2">
                      <h4 className="text-xs font-semibold">维度映射</h4>
                      {Object.keys(semanticConfig.dimensions).length === 0 ? (
                        <p className="text-xs text-[var(--text-secondary)]">暂无维度映射</p>
                      ) : (
                        <div className="space-y-1">
                          {Object.entries(semanticConfig.dimensions).map(([key, dim]) => (
                            <div key={key} className="flex items-center gap-2 text-xs rounded bg-[var(--surface-raised)] px-2 py-1">
                              <span className="font-medium">{key}</span>
                              <span className="text-[var(--text-secondary)]">&rarr; {dim.table}.{dim.column}</span>
                              <button onClick={() => removeDimension(key)} className="ml-auto text-red-500"><Trash2 size={11} /></button>
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="grid grid-cols-3 gap-1">
                        <input value={editingDimension.name} onChange={(e) => setEditingDimension({ ...editingDimension, name: e.target.value })} placeholder="维度名" className="rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" />
                        <input value={editingDimension.column} onChange={(e) => setEditingDimension({ ...editingDimension, column: e.target.value })} placeholder="列名" className="rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" />
                        <div className="flex gap-1">
                          <input value={editingDimension.table} onChange={(e) => setEditingDimension({ ...editingDimension, table: e.target.value })} placeholder="表名" className="flex-1 rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" />
                          <button onClick={addDimension} className="px-2 py-1 rounded border text-xs"><Plus size={12} /></button>
                        </div>
                      </div>
                    </div>

                    {/* Metrics */}
                    <div className="space-y-2">
                      <h4 className="text-xs font-semibold">度量定义</h4>
                      {Object.keys(semanticConfig.metrics).length === 0 ? (
                        <p className="text-xs text-[var(--text-secondary)]">暂无度量定义</p>
                      ) : (
                        <div className="space-y-1">
                          {Object.entries(semanticConfig.metrics).map(([key, expr]) => (
                            <div key={key} className="flex items-center gap-2 text-xs rounded bg-[var(--surface-raised)] px-2 py-1">
                              <span className="font-medium">{key}</span>
                              <span className="text-[var(--text-secondary)]">&rarr; {expr}</span>
                              <button onClick={() => removeMetric(key)} className="ml-auto text-red-500"><Trash2 size={11} /></button>
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="grid grid-cols-3 gap-1">
                        <input value={editingMetric.name} onChange={(e) => setEditingMetric({ ...editingMetric, name: e.target.value })} placeholder="度量名" className="rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" />
                        <input value={editingMetric.expression} onChange={(e) => setEditingMetric({ ...editingMetric, expression: e.target.value })} placeholder="SQL 表达式" className="rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs font-mono" />
                        <button onClick={addMetric} className="px-2 py-1 rounded border text-xs"><Plus size={12} /></button>
                      </div>
                    </div>

                    {/* Time Macros */}
                    <div className="space-y-2">
                      <h4 className="text-xs font-semibold">时间宏</h4>
                      {semanticConfig.time_macros.length === 0 ? (
                        <p className="text-xs text-[var(--text-secondary)]">暂无时间宏</p>
                      ) : (
                        <div className="space-y-1">
                          {semanticConfig.time_macros.map((tm, idx) => (
                            <div key={idx} className="flex items-center gap-2 text-xs rounded bg-[var(--surface-raised)] px-2 py-1">
                              <span className="font-medium">{tm.keyword}</span>
                              <span className="text-[var(--text-secondary)]">&rarr; {tm.column} &le; {tm.days}天</span>
                              <button onClick={() => removeTimeMacro(idx)} className="ml-auto text-red-500"><Trash2 size={11} /></button>
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="grid grid-cols-4 gap-1">
                        <input value={editingTimeMacro.keyword} onChange={(e) => setEditingTimeMacro({ ...editingTimeMacro, keyword: e.target.value })} placeholder="关键词" className="rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" />
                        <input value={editingTimeMacro.column} onChange={(e) => setEditingTimeMacro({ ...editingTimeMacro, column: e.target.value })} placeholder="时间列" className="rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" />
                        <input value={String(editingTimeMacro.days)} onChange={(e) => setEditingTimeMacro({ ...editingTimeMacro, days: Number(e.target.value) })} placeholder="天数" type="number" className="rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" />
                        <button onClick={addTimeMacro} className="px-2 py-1 rounded border text-xs"><Plus size={12} /></button>
                      </div>
                    </div>

                    <button onClick={() => void handleSaveSemanticConfig()} className="px-3 py-1.5 rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-xs">保存语义配置</button>
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function TabButton({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 rounded text-xs inline-flex items-center gap-1 ${active ? 'bg-[var(--accent)] text-[var(--accent-foreground)]' : 'border border-[var(--border)]'}`}
    >
      {icon}
      {label}
    </button>
  )
}

async function apiFetch(url: string, token: string): Promise<any> {
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
  if (!res.ok) throw new Error(`API ${res.status}`)
  return res.json()
}
