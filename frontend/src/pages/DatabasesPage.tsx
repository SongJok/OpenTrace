import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, Database, Plus, Trash2, RefreshCw, PlayCircle, BarChart3, Table2, Settings2, Search, Pencil, Circle, Zap } from 'lucide-react'
import DatabaseTypeSelect, { DATABASE_HOST_MODE_OPTIONS, type DatabaseHostMode, type DatabaseType } from '../components/DatabaseTypeSelect'
import MarkdownMessage from '../components/MarkdownMessage'
import { useAuthStore } from '../store/auth'
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
  type DataSourceItem,
} from '../api/client'

type TabKey = 'tables' | 'query' | 'analysis' | 'settings' | 'metrics' | 'relationships' | 'skills'

export default function DatabasesPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((s) => s.token)!
  const [items, setItems] = useState<DataSourceItem[]>([])
  const [selected, setSelected] = useState<DataSourceItem | null>(null)
  const [activeTab, setActiveTab] = useState<TabKey>('query')
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
  } | null>(null)
  const [schema, setSchema] = useState<{ tables: Array<{ name: string; comment?: string; columns: Array<{ name: string; type: string; comment?: string }> }> } | null>(null)
  const [analysis, setAnalysis] = useState<{ summary: string; charts: any[]; tables: any[]; insights: string[] } | null>(null)
  const [creating, setCreating] = useState(false)
  const [saving, setSaving] = useState(false)
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

  useEffect(() => {
    void load()
  }, [])

  useEffect(() => {
    if (!selected?.id) return
    void apiGetDatabaseSchema(token, selected.id)
      .then((x) => setSchema(x?.schema || { tables: [] }))
      .catch(() => setSchema({ tables: [] }))
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
  }, [selected?.id, token])

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
    if (!form.name.trim() || !normalizedHost || !nextDatabase || !form.username.trim() || !form.password.trim()) {
      alert('请填写完整的本机 / 宿主机 / 外部数据库连接信息')
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
        alert(test.ok ? '保存成功，连接测试通过' : `保存成功，但连接失败：${test.error || 'unknown'}`)
      } catch (e: any) {
        alert(`保存成功，但连接测试失败: ${e?.message || 'unknown'}`)
      }
      await load() // Refresh status
    } catch (e: any) {
      alert(e?.message || '保存数据库失败')
    } finally {
      setSaving(false)
    }
  }

  const runQuery = async () => {
    if (!selected) return
    const out = await apiDatabaseQuery(token, selected.id, { question })
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
    })
  }

  const testConn = async () => {
    if (!selected) return
    const out = await apiTestDatabaseConnection(token, selected.id)
    alert(out.ok ? '连接成功' : `连接失败: ${out.error || 'unknown'}`)
    await load()
  }

  const syncSchema = async () => {
    if (!selected) return
    await apiSyncDatabaseSchema(token, selected.id)
    const out = await apiGetDatabaseSchema(token, selected.id)
    setSchema(out.schema)
    setActiveTab('tables')
    await load()
    alert(`Schema 已同步，表数: ${out.schema.tables?.length || 0}`)
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
                    className={`rounded-xl border px-3 py-2 text-left text-xs ${form.host_mode === opt.value ? 'border-[var(--accent)] bg-[var(--accent)]/10' : 'border-[var(--border)] bg-[var(--surface-raised)]'}`}
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
              <input className="w-full rounded border border-[var(--border)] px-2 py-1 text-xs bg-transparent" placeholder="数据库名" value={form.database} onChange={(e) => setForm((f) => ({ ...f, database: e.target.value, jdbc: buildJdbc(f.source_type, f.host || getDefaultHostForMode(f.host_mode), f.port, e.target.value, getDefaultJdbcParams(f.source_type)) }))} />
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
                <div className="text-[var(--text-secondary)]">{x.type} · {x.host}:{x.port}/{x.database}</div>
                <div className="flex items-center gap-1 text-[var(--text-secondary)]">
                  <Circle size={10} className={x.status === 'active' ? 'fill-emerald-500 text-emerald-500' : x.status === 'error' ? 'fill-rose-500 text-rose-500' : 'fill-slate-400 text-slate-400'} />
                  <span>状态：{x.status}</span>
                </div>
                <div className="text-[var(--text-secondary)]">表数：{x.table_count ?? 0} · 上次同步：{x.last_schema_sync_at || x.synced_at || '—'}</div>
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
                  <button className="px-2 py-1 rounded border text-xs inline-flex items-center gap-1" onClick={() => void syncSchema()}><RefreshCw size={12} /> 同步Schema</button>
                </div>
              </div>

              <div className="flex gap-2 border-b border-[var(--border)] pb-2">
                <TabButton active={activeTab === 'tables'} onClick={() => setActiveTab('tables')} icon={<Table2 size={14} />} label="Tables" />
                <TabButton active={activeTab === 'query'} onClick={() => setActiveTab('query')} icon={<Search size={14} />} label="Query" />
                <TabButton active={activeTab === 'analysis'} onClick={() => setActiveTab('analysis')} icon={<BarChart3 size={14} />} label="Analysis" />
                <TabButton active={activeTab === 'metrics'} onClick={() => setActiveTab('metrics')} icon={<BarChart3 size={14} />} label="指标定义" />
                <TabButton active={activeTab === 'relationships'} onClick={() => setActiveTab('relationships')} icon={<Table2 size={14} />} label="表关系" />
                <TabButton active={activeTab === 'skills'} onClick={() => setActiveTab('skills')} icon={<Zap size={14} />} label="分析技能" />
                <TabButton active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} icon={<Settings2 size={14} />} label="Settings" />
              </div>

              {activeTab === 'tables' ? (
                <div className="space-y-2">
                  {(schema?.tables || []).length === 0 ? <div className="text-xs text-[var(--text-secondary)]">暂无 schema，请先同步</div> : null}
                  {(schema?.tables || []).map((t) => (
                    <details key={t.name} className="rounded border border-[var(--border)] p-2">
                      <summary className="cursor-pointer text-sm font-medium">{t.name}</summary>
                      {t.comment ? <div className="mt-1 text-xs text-[var(--text-secondary)]">{t.comment}</div> : null}
                      <div className="mt-2 grid grid-cols-2 gap-1 text-xs">
                        {(t.columns || []).map((c) => (
                          <div key={`${t.name}_${c.name}`} className="rounded bg-[var(--surface-raised)] px-2 py-1">
                            {c.name} <span className="text-[var(--text-secondary)]">({c.type})</span>
                            {c.comment ? <div className="text-[10px] text-[var(--text-secondary)]">{c.comment}</div> : null}
                          </div>
                        ))}
                      </div>
                    </details>
                  ))}
                </div>
              ) : null}

              {activeTab === 'query' ? (
                <div className="rounded border border-[var(--border)] p-3 space-y-2">
                  <input value={question} onChange={(e) => setQuestion(e.target.value)} className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-sm" />
                  <button className="px-3 py-1.5 rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-xs" onClick={() => void runQuery()}>运行 Text2SQL</button>
                  {queryOutput ? (
                    <>
                      {/* 1. Answer - 自然语言分析回答 */}
                      {queryOutput.answer ? (
                        <div className="rounded border border-[var(--border)] p-3 bg-[var(--surface-raised)]">
                          <div className="text-xs font-medium mb-2" style={{ color: 'var(--accent)' }}>分析结果</div>
                          <MarkdownMessage content={queryOutput.answer} />
                        </div>
                      ) : (
                        <div className="text-xs text-[var(--text-secondary)]">{queryOutput.summary}</div>
                      )}

                      {/* 2. SQL - 默认展开 */}
                      {queryOutput.sql ? (
                        <details open>
                          <summary className="cursor-pointer text-xs font-medium" style={{ color: 'var(--accent)' }}>已执行 SQL</summary>
                          <pre className="text-xs whitespace-pre-wrap rounded border border-[var(--border)] p-2 bg-black/20 mt-1">{queryOutput.sql}</pre>
                        </details>
                      ) : null}

                      {/* 3. 结果表格 */}
                      <div className="overflow-x-auto rounded border border-[var(--border)]">
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
                      </div>
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
                            onClick={() => window.dispatchEvent(new CustomEvent('opentrace:prefill', { detail: `请基于以下数据绘制图表并分析：\n${JSON.stringify(queryOutput.rows.slice(0, 20), null, 2)}` }))}
                          >
                            在对话中生成图表
                          </button>
                        </div>
                      ) : (
                        <button
                          className="px-3 py-1 rounded border text-xs"
                          onClick={() => window.dispatchEvent(new CustomEvent('opentrace:prefill', { detail: `请基于以下数据绘制图表并分析：\n${JSON.stringify(queryOutput.rows.slice(0, 20), null, 2)}` }))}
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
                    <div>数据库：{selected.database}</div>
                    <div>用户名：{selected.username}</div>
                  </div>

                  <div className="rounded border border-[var(--border)] p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-semibold inline-flex items-center gap-1.5"><Zap size={14} /> 语义层配置</h3>
                      <button onClick={() => void handleAutoExtractSemantic()} className="px-2 py-1 rounded bg-[var(--accent)]/10 text-[var(--accent)] text-xs inline-flex items-center gap-1"><Zap size={12} /> 自动提取</button>
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
