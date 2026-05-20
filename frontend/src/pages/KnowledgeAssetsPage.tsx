import { useEffect, useState } from 'react'
import { Database, GitBranch, BarChart3, Plus, Trash2, Save, RefreshCw, CheckCircle, XCircle } from 'lucide-react'
import { useAuthStore } from '../store/auth'

// ── Types ──────────────────────────────────────────────────────────

interface MetricItem {
  id: string; name: string; formula: string; agg_function?: string
  business_definition?: string; unit?: string; category?: string
  status: string; version: number; data_source_id: string
  aliases: string[]; underlying_columns: string[]; tags: string[]
}

interface RelationshipItem {
  id: string; left_table: string; left_column: string
  right_table: string; right_column: string; join_type: string
  cardinality?: string; is_verified: boolean; usage_count: number
  success_rate: number; amplification_risk?: string
}

interface SkillItem {
  id: string; name: string; skill_type: string; description?: string
  status: string; version: number; visualization_hint?: string
}

interface RelationshipGraph {
  nodes: { name: string; edge_count: number }[]
  edges: { id: string; source: string; target: string; join_type: string; is_verified: boolean }[]
}

// ── API helpers ─────────────────────────────────────────────────────

function token() { return useAuthStore.getState().token || '' }
function h() { return { Authorization: `Bearer ${token()}`, 'Content-Type': 'application/json' } }

async function apiFetch(path: string, opts: RequestInit = {}) {
  return fetch(`/api/v1${path}`, opts)
}

async function listMetrics(dsId = ''): Promise<MetricItem[]> {
  const res = await apiFetch(`/metrics?data_source_id=${dsId}&limit=100`, { headers: h() })
  if (!res.ok) return []
  const data = await res.json()
  return data.items || []
}

async function createMetric(payload: any): Promise<MetricItem | null> {
  const res = await apiFetch('/metrics', { method: 'POST', headers: h(), body: JSON.stringify(payload) })
  if (!res.ok) return null
  const data = await res.json()
  return data.metric
}

async function updateMetric(id: string, payload: any): Promise<MetricItem | null> {
  const res = await apiFetch(`/metrics/${id}`, { method: 'PUT', headers: h(), body: JSON.stringify(payload) })
  if (!res.ok) return null
  const data = await res.json()
  return data.metric
}

async function deleteMetric(id: string): Promise<boolean> {
  const res = await apiFetch(`/metrics/${id}`, { method: 'DELETE', headers: h() })
  return res.ok
}

async function listRelationships(dsId = ''): Promise<RelationshipItem[]> {
  const res = await apiFetch(`/table-relationships?data_source_id=${dsId}&limit=200`, { headers: h() })
  if (!res.ok) return []
  const data = await res.json()
  return data.items || []
}

async function getRelationshipGraph(dsId: string): Promise<RelationshipGraph | null> {
  const res = await apiFetch(`/table-relationships/graph?data_source_id=${dsId}`, { headers: h() })
  if (!res.ok) return null
  return res.json()
}

async function verifyRelationship(id: string): Promise<boolean> {
  const res = await apiFetch(`/table-relationships/${id}/verify`, { method: 'POST', headers: h() })
  return res.ok
}

async function listSkills(): Promise<SkillItem[]> {
  const res = await apiFetch('/analytical-skills?limit=100', { headers: h() })
  if (!res.ok) return []
  const data = await res.json()
  return data.items || []
}

async function seedSkills(): Promise<any> {
  const res = await apiFetch('/analytical-skills/seed', { method: 'POST', headers: h() })
  return res.json()
}

// ── Page Component ──────────────────────────────────────────────────

type Tab = 'metrics' | 'relationships' | 'skills'

export default function KnowledgeAssetsPage({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<Tab>('metrics')
  const [metrics, setMetrics] = useState<MetricItem[]>([])
  const [relationships, setRelationships] = useState<RelationshipItem[]>([])
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [graph, setGraph] = useState<RelationshipGraph | null>(null)
  const [dsId, setDsId] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  // ── Create/Edit form state ──────────────────────────────────
  const [editing, setEditing] = useState<MetricItem | null>(null)
  const [form, setForm] = useState({ name: '', formula: '', business_definition: '', agg_function: '', unit: '', category: '', data_source_id: '' })

  const load = async () => {
    setLoading(true)
    try {
      if (tab === 'metrics') setMetrics(await listMetrics(dsId))
      if (tab === 'relationships') {
        setRelationships(await listRelationships(dsId))
        if (dsId) setGraph(await getRelationshipGraph(dsId))
      }
      if (tab === 'skills') setSkills(await listSkills())
    } catch (e) { console.error(e) }
    setLoading(false)
  }

  useEffect(() => { void load() }, [tab, dsId])

  const showMsg = (m: string) => { setMessage(m); setTimeout(() => setMessage(''), 3000) }

  // ── Metric CRUD ─────────────────────────────────────────────

  const handleCreateMetric = async () => {
    const m = await createMetric({ ...form, data_source_id: dsId || form.data_source_id, aliases: [], underlying_columns: [], tags: [] })
    if (m) { showMsg('指标创建成功'); setEditing(null); resetForm(); await load() }
    else showMsg('创建失败')
  }

  const handleUpdateMetric = async () => {
    if (!editing) return
    const m = await updateMetric(editing.id, form)
    if (m) { showMsg('指标更新成功'); setEditing(null); resetForm(); await load() }
    else showMsg('更新失败')
  }

  const handleDeleteMetric = async (id: string) => {
    if (await deleteMetric(id)) { showMsg('指标已删除'); await load() }
  }

  const handleVerifyRel = async (id: string) => {
    if (await verifyRelationship(id)) { showMsg('关系已验证'); await load() }
  }

  const handleSeedSkills = async () => {
    const r = await seedSkills()
    showMsg(`已播种 ${r.seeded} 个分析技能模板`)
    await load()
  }

  const startEdit = (m: MetricItem) => {
    setEditing(m)
    setForm({ name: m.name, formula: m.formula, business_definition: m.business_definition || '', agg_function: m.agg_function || '', unit: m.unit || '', category: m.category || '', data_source_id: m.data_source_id })
  }

  const resetForm = () => {
    setForm({ name: '', formula: '', business_definition: '', agg_function: '', unit: '', category: '', data_source_id: '' })
  }

  // ── Render ──────────────────────────────────────────────────

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: '#fff' }}>
      {/* Header */}
      <div style={{ padding: '16px 20px', borderBottom: '1px solid #eee', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <button onClick={onBack} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>← 返回</button>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>知识资产管理</h2>
        <div style={{ flex: 1 }} />

        {/* Tab bar */}
        <div style={{ display: 'flex', gap: 0, background: '#f3f4f6', borderRadius: 8, padding: 3 }}>
          {([
            ['metrics', '指标定义', <BarChart3 key="m" size={16} />],
            ['relationships', '表关系', <GitBranch key="r" size={16} />],
            ['skills', '分析技能', <Database key="s" size={16} />],
          ] as [Tab, string, JSX.Element][]).map(([t, label, icon]) => (
            <button key={t} onClick={() => setTab(t)}
              style={{
                padding: '6px 16px', border: 'none', borderRadius: 6, cursor: 'pointer',
                background: tab === t ? '#fff' : 'transparent',
                fontWeight: tab === t ? 600 : 400, fontSize: 13,
                boxShadow: tab === t ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
              }}
            >
              {icon} <span style={{ marginLeft: 4, verticalAlign: 'middle' }}>{label}</span>
            </button>
          ))}
        </div>

        {/* Data source filter */}
        <input placeholder="data_source_id (可选)" value={dsId}
          onChange={e => setDsId(e.target.value)}
          style={{ padding: '6px 10px', border: '1px solid #ddd', borderRadius: 6, fontSize: 13, width: 200 }}
        />
        <button onClick={load} disabled={loading}
          style={{ padding: '6px 12px', border: '1px solid #ddd', borderRadius: 6, background: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}
        >
          <RefreshCw size={14} /> 刷新
        </button>
      </div>

      {/* Message */}
      {message && <div style={{ padding: '8px 20px', background: '#f0fdf4', color: '#166534', fontSize: 13 }}>{message}</div>}

      {/* Content */}
      <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>
        {tab === 'metrics' && (
          <MetricsTab
            metrics={metrics} editing={editing} form={form} setForm={setForm}
            onCreate={handleCreateMetric} onUpdate={handleUpdateMetric}
            onDelete={handleDeleteMetric} onEdit={startEdit} onCancel={() => { setEditing(null); resetForm() }}
            dsId={dsId}
          />
        )}
        {tab === 'relationships' && (
          <RelationshipsTab
            relationships={relationships} graph={graph}
            onVerify={handleVerifyRel} dsId={dsId}
          />
        )}
        {tab === 'skills' && (
          <SkillsTab skills={skills} onSeed={handleSeedSkills} />
        )}
      </div>
    </div>
  )
}

// ── Metrics Tab ─────────────────────────────────────────────────────

function MetricsTab({ metrics, editing, form, setForm, onCreate, onUpdate, onDelete, onEdit, onCancel, dsId }: {
  metrics: MetricItem[]; editing: MetricItem | null
  form: any; setForm: (f: any) => void
  onCreate: () => void; onUpdate: () => void; onDelete: (id: string) => void
  onEdit: (m: MetricItem) => void; onCancel: () => void; dsId: string
}) {
  const fields = [
    ['name', '指标名称'], ['formula', '计算公式'], ['business_definition', '业务口径'],
    ['agg_function', '聚合函数'], ['unit', '单位'], ['category', '分类'],
  ]

  return (
    <div>
      {/* Create/Edit form */}
      <div style={{ marginBottom: 20, padding: 16, background: '#f9fafb', borderRadius: 8, border: '1px solid #e5e7eb' }}>
        <h3 style={{ margin: '0 0 12px 0', fontSize: 15 }}>{editing ? '编辑指标' : '新建指标'}</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
          {fields.map(([key, label]) => (
            <div key={key}>
              <label style={{ fontSize: 12, color: '#6b7280', display: 'block' }}>{label}</label>
              <input value={form[key] || ''} onChange={e => setForm({ ...form, [key]: e.target.value })}
                style={{ width: '100%', padding: '6px 8px', border: '1px solid #ddd', borderRadius: 4, fontSize: 13 }}
              />
            </div>
          ))}
          {!dsId && (
            <div>
              <label style={{ fontSize: 12, color: '#6b7280', display: 'block' }}>Data Source ID</label>
              <input value={form.data_source_id} onChange={e => setForm({ ...form, data_source_id: e.target.value })}
                style={{ width: '100%', padding: '6px 8px', border: '1px solid #ddd', borderRadius: 4, fontSize: 13 }}
              />
            </div>
          )}
        </div>
        <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
          <button onClick={editing ? onUpdate : onCreate}
            style={{ padding: '6px 16px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13, display: 'flex', alignItems: 'center', gap: 4 }}
          ><Save size={14} /> {editing ? '更新' : '创建'}</button>
          {editing && <button onClick={onCancel} style={{ padding: '6px 16px', background: '#fff', border: '1px solid #ddd', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}>取消</button>}
        </div>
      </div>

      {/* Metrics list */}
      {metrics.length === 0 ? (
        <p style={{ color: '#9ca3af', fontSize: 14 }}>暂无指标定义。创建你的第一个指标，或选择一个数据源。</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#f9fafb', textAlign: 'left' }}>
              <th style={th}>名称</th><th style={th}>公式</th><th style={th}>口径</th>
              <th style={th}>聚合</th><th style={th}>状态</th><th style={th}>版本</th><th style={th}>操作</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map(m => (
              <tr key={m.id} style={{ borderBottom: '1px solid #f3f4f6' }}>
                <td style={td}><strong>{m.name}</strong></td>
                <td style={{ ...td, fontFamily: 'monospace', fontSize: 12, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{m.formula}</td>
                <td style={{ ...td, fontSize: 12, maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis' }}>{m.business_definition || '-'}</td>
                <td style={td}>{m.agg_function || '-'}</td>
                <td style={td}>
                  <span style={{ padding: '2px 8px', borderRadius: 12, fontSize: 11, background: m.status === 'published' ? '#dcfce7' : m.status === 'draft' ? '#fef3c7' : '#fee2e2', color: m.status === 'published' ? '#166534' : m.status === 'draft' ? '#92400e' : '#991b1b' }}>
                    {m.status}
                  </span>
                </td>
                <td style={td}>v{m.version}</td>
                <td style={td}>
                  <button onClick={() => onEdit(m)} style={{ ...btnSm, marginRight: 4 }}>编辑</button>
                  <button onClick={() => onDelete(m.id)} style={{ ...btnSm, color: '#dc2626' }}><Trash2 size={12} /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ── Relationships Tab ────────────────────────────────────────────────

function RelationshipsTab({ relationships, graph, onVerify, dsId }: {
  relationships: RelationshipItem[]; graph: RelationshipGraph | null
  onVerify: (id: string) => void; dsId: string
}) {
  return (
    <div>
      {/* Graph visualization (simple text DAG) */}
      {graph && (
        <div style={{ marginBottom: 20, padding: 16, background: '#f0f9ff', borderRadius: 8, border: '1px solid #bae6fd' }}>
          <h3 style={{ margin: '0 0 8px 0', fontSize: 15 }}>关系图 (DAG)</h3>
          <p style={{ fontSize: 12, color: '#6b7280', marginBottom: 12 }}>
            {graph.nodes.length} 个表, {graph.edges.length} 条关系, {graph.edges.filter(e => e.is_verified).length} 已验证
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {graph.nodes.map(n => (
              <div key={n.name} style={{ padding: '8px 14px', background: '#fff', borderRadius: 6, border: '1px solid #e5e7eb', fontSize: 13, fontWeight: 600 }}>
                {n.name}
                <span style={{ fontSize: 10, color: '#9ca3af', marginLeft: 6 }}>({n.edge_count} 边)</span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 12 }}>
            {graph.edges.slice(0, 20).map(e => (
              <div key={e.id} style={{ fontSize: 12, padding: '4px 0', color: e.is_verified ? '#166534' : '#9ca3af' }}>
                {e.source} → {e.target} ({e.join_type})
                {e.is_verified ? ' ✓' : ''}
              </div>
            ))}
          </div>
        </div>
      )}

      {!dsId && <p style={{ color: '#9ca3af', fontSize: 14, marginBottom: 16 }}>输入 data_source_id 查看关系图。</p>}

      {/* Relationships table */}
      {relationships.length === 0 ? (
        <p style={{ color: '#9ca3af', fontSize: 14 }}>暂无表关系。</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#f9fafb', textAlign: 'left' }}>
              <th style={th}>左表</th><th style={th}>左列</th><th style={th}>右表</th><th style={th}>右列</th>
              <th style={th}>类型</th><th style={th}>基数</th><th style={th}>已验证</th>
              <th style={th}>成功率</th><th style={th}>使用次数</th><th style={th}>操作</th>
            </tr>
          </thead>
          <tbody>
            {relationships.map(r => (
              <tr key={r.id} style={{ borderBottom: '1px solid #f3f4f6' }}>
                <td style={td}><strong>{r.left_table}</strong></td>
                <td style={{ ...td, fontFamily: 'monospace', fontSize: 12 }}>{r.left_column}</td>
                <td style={td}><strong>{r.right_table}</strong></td>
                <td style={{ ...td, fontFamily: 'monospace', fontSize: 12 }}>{r.right_column}</td>
                <td style={td}>{r.join_type}</td>
                <td style={td}>{r.cardinality || '-'}</td>
                <td style={td}>{r.is_verified ? <CheckCircle size={14} color="#16a34a" /> : <XCircle size={14} color="#9ca3af" />}</td>
                <td style={td}>{(r.success_rate * 100).toFixed(0)}%</td>
                <td style={td}>{r.usage_count}</td>
                <td style={td}>
                  {!r.is_verified && (
                    <button onClick={() => onVerify(r.id)} style={{ ...btnSm, color: '#16a34a' }}>验证</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ── Skills Tab ──────────────────────────────────────────────────────

function SkillsTab({ skills, onSeed }: { skills: SkillItem[]; onSeed: () => void }) {
  const typeLabels: Record<string, string> = {
    comparison: '对比', trend: '趋势', funnel: '漏斗', cohort: '队列',
    rfm: 'RFM', attribution: '归因', anomaly: '异常', ranking: '排名', composition: '分布',
  }

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <p style={{ fontSize: 13, color: '#6b7280', margin: 0 }}>
          {skills.length} 个分析技能模板
        </p>
        <button onClick={onSeed}
          style={{ padding: '6px 16px', background: '#059669', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13, display: 'flex', alignItems: 'center', gap: 4 }}
        >
          <Plus size={14} /> 播种默认模板
        </button>
      </div>

      {skills.length === 0 ? (
        <p style={{ color: '#9ca3af', fontSize: 14 }}>暂无分析技能。点击"播种默认模板"加载内置技能。</p>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12 }}>
          {skills.map(s => (
            <div key={s.id} style={{ padding: 16, border: '1px solid #e5e7eb', borderRadius: 8, background: '#fff' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <strong style={{ fontSize: 14 }}>{s.name}</strong>
                <span style={{ padding: '2px 8px', borderRadius: 12, fontSize: 11, background: '#e0e7ff', color: '#3730a3' }}>
                  {typeLabels[s.skill_type] || s.skill_type}
                </span>
              </div>
              {s.description && <p style={{ fontSize: 12, color: '#6b7280', marginTop: 8 }}>{s.description}</p>}
              <div style={{ marginTop: 8, display: 'flex', gap: 8, fontSize: 11, color: '#9ca3af' }}>
                <span>v{s.version}</span>
                <span>{s.status}</span>
                {s.visualization_hint && <span>图表: {s.visualization_hint}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Shared styles ───────────────────────────────────────────────────

const th: React.CSSProperties = { padding: '8px 10px', fontSize: 12, fontWeight: 600, color: '#6b7280', whiteSpace: 'nowrap' }
const td: React.CSSProperties = { padding: '8px 10px', fontSize: 13 }
const btnSm: React.CSSProperties = { padding: '3px 8px', border: '1px solid #ddd', borderRadius: 4, background: '#fff', cursor: 'pointer', fontSize: 12 }
