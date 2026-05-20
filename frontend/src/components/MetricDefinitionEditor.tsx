import { useState } from 'react'
import { Save, X } from 'lucide-react'

export interface MetricFormData {
  name: string
  formula: string
  business_definition: string
  agg_function: string
  unit: string
  category: string
  data_source_id: string
  aliases: string[]
  underlying_columns: string[]
  tags: string[]
}

interface MetricDefinitionEditorProps {
  initial?: Partial<MetricFormData>
  dataSourceId?: string
  onSave: (data: MetricFormData) => void
  onCancel: () => void
  saving?: boolean
}

const AGG_FUNCTIONS = ['SUM', 'COUNT', 'AVG', 'MAX', 'MIN', 'COUNT_DISTINCT']
const CATEGORIES = ['营收', '用户', '订单', '流量', '内容', '财务', '其他']

export default function MetricDefinitionEditor({
  initial, dataSourceId, onSave, onCancel, saving,
}: MetricDefinitionEditorProps) {
  const [form, setForm] = useState<MetricFormData>({
    name: initial?.name || '',
    formula: initial?.formula || '',
    business_definition: initial?.business_definition || '',
    agg_function: initial?.agg_function || '',
    unit: initial?.unit || '',
    category: initial?.category || '',
    data_source_id: initial?.data_source_id || dataSourceId || '',
    aliases: initial?.aliases || [],
    underlying_columns: initial?.underlying_columns || [],
    tags: initial?.tags || [],
  })

  const [aliasInput, setAliasInput] = useState('')
  const [colInput, setColInput] = useState('')
  const [tagInput, setTagInput] = useState('')

  const update = (k: keyof MetricFormData, v: any) => setForm(f => ({ ...f, [k]: v }))

  const addAlias = () => {
    const a = aliasInput.trim()
    if (a && !form.aliases.includes(a)) {
      update('aliases', [...form.aliases, a])
      setAliasInput('')
    }
  }

  const addColumn = () => {
    const c = colInput.trim()
    if (c && !form.underlying_columns.includes(c)) {
      update('underlying_columns', [...form.underlying_columns, c])
      setColInput('')
    }
  }

  const addTag = () => {
    const t = tagInput.trim()
    if (t && !form.tags.includes(t)) {
      update('tags', [...form.tags, t])
      setTagInput('')
    }
  }

  const isValid = form.name.trim() && form.formula.trim()

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', display: 'flex',
      alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div style={{
        background: '#fff', borderRadius: 12, width: 640, maxHeight: '80vh',
        overflow: 'auto', boxShadow: '0 8px 40px rgba(0,0,0,0.15)',
      }}>
        {/* Header */}
        <div style={{
          padding: '16px 20px', borderBottom: '1px solid #eee',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
            {initial?.name ? `编辑指标: ${initial.name}` : '新建指标定义'}
          </h3>
          <button onClick={onCancel} style={iconBtn}><X size={16} /></button>
        </div>

        {/* Body */}
        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Name + Category row */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={lbl}>指标名称 *</label>
              <input value={form.name} onChange={e => update('name', e.target.value)}
                placeholder="例如: GMV" style={inp} />
            </div>
            <div>
              <label style={lbl}>分类</label>
              <select value={form.category} onChange={e => update('category', e.target.value)} style={inp}>
                <option value="">--</option>
                {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </div>

          {/* Formula */}
          <div>
            <label style={lbl}>计算公式 *</label>
            <input value={form.formula} onChange={e => update('formula', e.target.value)}
              placeholder="例如: SUM(orders.paid_amount) FILTER (WHERE orders.status = 'paid')"
              style={{ ...inp, fontFamily: 'monospace', fontSize: 13 }} />
          </div>

          {/* Agg function + Unit row */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={lbl}>聚合函数</label>
              <select value={form.agg_function} onChange={e => update('agg_function', e.target.value)} style={inp}>
                <option value="">--</option>
                {AGG_FUNCTIONS.map(a => <option key={a} value={a}>{a}</option>)}
              </select>
            </div>
            <div>
              <label style={lbl}>单位</label>
              <input value={form.unit} onChange={e => update('unit', e.target.value)}
                placeholder="例如: 元、人、次" style={inp} />
            </div>
          </div>

          {/* Business definition */}
          <div>
            <label style={lbl}>业务口径说明</label>
            <textarea value={form.business_definition} onChange={e => update('business_definition', e.target.value)}
              placeholder="清晰描述该指标的业务含义，确保换一个人也能理解..."
              rows={3} style={{ ...inp, resize: 'vertical', fontFamily: 'inherit' }} />
          </div>

          {/* Data source id */}
          {!dataSourceId && (
            <div>
              <label style={lbl}>Data Source ID</label>
              <input value={form.data_source_id} onChange={e => update('data_source_id', e.target.value)}
                placeholder="UUID" style={inp} />
            </div>
          )}

          {/* Aliases */}
          <div>
            <label style={lbl}>别名</label>
            <div style={{ display: 'flex', gap: 6 }}>
              <input value={aliasInput} onChange={e => setAliasInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addAlias())}
                placeholder="输入别名后按回车添加" style={{ ...inp, flex: 1 }} />
              <button onClick={addAlias} style={smBtn}>添加</button>
            </div>
            {form.aliases.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
                {form.aliases.map(a => (
                  <span key={a} style={chip}>
                    {a}
                    <button onClick={() => update('aliases', form.aliases.filter(x => x !== a))} style={chipX}>×</button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Underlying columns */}
          <div>
            <label style={lbl}>依赖列 (table.column)</label>
            <div style={{ display: 'flex', gap: 6 }}>
              <input value={colInput} onChange={e => setColInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addColumn())}
                placeholder="例如: orders.paid_amount" style={{ ...inp, flex: 1, fontFamily: 'monospace', fontSize: 13 }} />
              <button onClick={addColumn} style={smBtn}>添加</button>
            </div>
            {form.underlying_columns.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
                {form.underlying_columns.map(c => (
                  <span key={c} style={{ ...chip, fontFamily: 'monospace' }}>
                    {c}
                    <button onClick={() => update('underlying_columns', form.underlying_columns.filter(x => x !== c))} style={chipX}>×</button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Tags */}
          <div>
            <label style={lbl}>标签</label>
            <div style={{ display: 'flex', gap: 6 }}>
              <input value={tagInput} onChange={e => setTagInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addTag())}
                placeholder="例如: 核心指标、日报" style={{ ...inp, flex: 1 }} />
              <button onClick={addTag} style={smBtn}>添加</button>
            </div>
            {form.tags.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
                {form.tags.map(t => (
                  <span key={t} style={{ ...chip, background: '#e0e7ff', color: '#3730a3' }}>
                    {t}
                    <button onClick={() => update('tags', form.tags.filter(x => x !== t))} style={chipX}>×</button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div style={{
          padding: '14px 20px', borderTop: '1px solid #eee',
          display: 'flex', justifyContent: 'flex-end', gap: 8,
        }}>
          <button onClick={onCancel} style={{ ...btn, background: '#fff', border: '1px solid #ddd' }}>
            取消
          </button>
          <button onClick={() => onSave(form)} disabled={!isValid || saving}
            style={{
              ...btn, background: isValid ? '#2563eb' : '#93c5fd',
              color: '#fff', border: 'none', display: 'flex', alignItems: 'center', gap: 4,
            }}>
            <Save size={14} /> {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

const lbl: React.CSSProperties = { fontSize: 12, color: '#6b7280', display: 'block', marginBottom: 4, fontWeight: 500 }
const inp: React.CSSProperties = { width: '100%', padding: '7px 10px', border: '1px solid #ddd', borderRadius: 6, fontSize: 13, boxSizing: 'border-box' }
const btn: React.CSSProperties = { padding: '7px 18px', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 500 }
const smBtn: React.CSSProperties = { padding: '5px 12px', border: '1px solid #ddd', borderRadius: 6, background: '#fff', cursor: 'pointer', fontSize: 12 }
const iconBtn: React.CSSProperties = { background: 'none', border: 'none', cursor: 'pointer', padding: 4, borderRadius: 4 }
const chip: React.CSSProperties = { padding: '2px 8px', background: '#f3f4f6', borderRadius: 12, fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 4 }
const chipX: React.CSSProperties = { background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, padding: 0, lineHeight: 1, color: '#9ca3af' }
