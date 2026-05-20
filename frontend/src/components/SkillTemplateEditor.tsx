import { useState } from 'react'
import { Save, X, Plus, Trash2, GripVertical } from 'lucide-react'

export interface SkillStep {
  id: string
  agent: string
  description: string
  params?: Record<string, any>
  depends_on: string[]
}

export interface SkillTemplateForm {
  name: string
  skill_type: string
  description: string
  required_intent_types: string[]
  required_metric_count: number
  required_dimension_count: number
  plan_template: {
    steps: SkillStep[]
    parameters?: Record<string, any>
  }
  sql_template: string
  visualization_hint: string
}

interface SkillTemplateEditorProps {
  initial?: Partial<SkillTemplateForm>
  onSave: (data: SkillTemplateForm) => void
  onCancel: () => void
  saving?: boolean
}

const SKILL_TYPES = ['comparison', 'trend', 'funnel', 'cohort', 'rfm', 'attribution', 'anomaly', 'ranking', 'composition']
const AGENT_TYPES = ['data', 'statistical', 'insight', 'visualization']
const VIZ_HINTS = ['line', 'area', 'bar', 'grouped_bar', 'stacked_bar', 'horizontal_bar', 'pie', 'donut', 'scatter', 'heatmap', 'funnel', 'metric_card', 'table']
const INTENT_TYPES = ['comparison', 'trend', 'funnel', 'cohort', 'rfm', 'attribution', 'anomaly', 'ranking', 'composition', 'distribution', 'detail_lookup', 'metadata', 'general']

const TYPE_LABELS: Record<string, string> = {
  comparison: '对比', trend: '趋势', funnel: '漏斗', cohort: '队列',
  rfm: 'RFM', attribution: '归因', anomaly: '异常', ranking: '排名',
  composition: '分布', distribution: '分布', detail_lookup: '明细', metadata: '元数据', general: '通用',
}

const defaultStep = (): SkillStep => ({
  id: `step_${Date.now()}`,
  agent: 'data',
  description: '',
  params: {},
  depends_on: [],
})

export default function SkillTemplateEditor({
  initial, onSave, onCancel, saving,
}: SkillTemplateEditorProps) {
  const [form, setForm] = useState<SkillTemplateForm>({
    name: initial?.name || '',
    skill_type: initial?.skill_type || 'comparison',
    description: initial?.description || '',
    required_intent_types: initial?.required_intent_types || [],
    required_metric_count: initial?.required_metric_count ?? 1,
    required_dimension_count: initial?.required_dimension_count ?? 0,
    plan_template: initial?.plan_template || { steps: [] },
    sql_template: initial?.sql_template || '',
    visualization_hint: initial?.visualization_hint || 'table',
  })

  const [intentInput, setIntentInput] = useState('')
  const [paramKey, setParamKey] = useState('')
  const [paramVal, setParamVal] = useState('')
  const [paramDefVal, setParamDefVal] = useState('')

  const update = <K extends keyof SkillTemplateForm>(k: K, v: SkillTemplateForm[K]) =>
    setForm(f => ({ ...f, [k]: v }))

  const addIntent = () => {
    const i = intentInput.trim()
    if (i && !form.required_intent_types.includes(i)) {
      update('required_intent_types', [...form.required_intent_types, i])
      setIntentInput('')
    }
  }

  const addStep = () => {
    const steps = [...form.plan_template.steps, defaultStep()]
    update('plan_template', { ...form.plan_template, steps })
  }

  const updateStep = (idx: number, patch: Partial<SkillStep>) => {
    const steps = form.plan_template.steps.map((s, i) => i === idx ? { ...s, ...patch } : s)
    update('plan_template', { ...form.plan_template, steps })
  }

  const removeStep = (idx: number) => {
    const steps = form.plan_template.steps.filter((_, i) => i !== idx)
    // Clean up depends_on references
    const removedId = form.plan_template.steps[idx]?.id
    const cleanSteps = steps.map(s => ({
      ...s,
      depends_on: s.depends_on.filter(d => d !== removedId),
    }))
    update('plan_template', { ...form.plan_template, steps: cleanSteps })
  }

  const addParameter = () => {
    const k = paramKey.trim()
    const v = paramVal.trim()
    const d = paramDefVal.trim()
    if (k) {
      const params = {
        ...(form.plan_template.parameters || {}),
        [k]: { type: v || 'string', default: d || undefined },
      }
      update('plan_template', { ...form.plan_template, parameters: params })
      setParamKey('')
      setParamVal('')
      setParamDefVal('')
    }
  }

  const removeParameter = (key: string) => {
    const params = { ...(form.plan_template.parameters || {}) }
    delete params[key]
    update('plan_template', { ...form.plan_template, parameters: params })
  }

  const isValid = form.name.trim() && form.plan_template.steps.length > 0

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', display: 'flex',
      alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div style={{
        background: '#fff', borderRadius: 12, width: 720, maxHeight: '85vh',
        overflow: 'auto', boxShadow: '0 8px 40px rgba(0,0,0,0.15)',
      }}>
        {/* Header */}
        <div style={{
          padding: '16px 20px', borderBottom: '1px solid #eee',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
            {initial?.name ? `编辑技能: ${initial.name}` : '新建分析技能'}
          </h3>
          <button onClick={onCancel} style={iconBtn}><X size={16} /></button>
        </div>

        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Basic info */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={lbl}>技能名称 *</label>
              <input value={form.name} onChange={e => update('name', e.target.value)}
                placeholder="例如: 同比环比分析" style={inp} />
            </div>
            <div>
              <label style={lbl}>技能类型</label>
              <select value={form.skill_type} onChange={e => update('skill_type', e.target.value)} style={inp}>
                {SKILL_TYPES.map(t => <option key={t} value={t}>{TYPE_LABELS[t] || t} ({t})</option>)}
              </select>
            </div>
          </div>

          <div>
            <label style={lbl}>描述</label>
            <textarea value={form.description} onChange={e => update('description', e.target.value)}
              placeholder="描述该技能解决什么分析问题..."
              rows={2} style={{ ...inp, resize: 'vertical', fontFamily: 'inherit' }} />
          </div>

          {/* Triggers */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            <div>
              <label style={lbl}>最少指标数</label>
              <input type="number" min={0} value={form.required_metric_count}
                onChange={e => update('required_metric_count', parseInt(e.target.value) || 0)} style={inp} />
            </div>
            <div>
              <label style={lbl}>最少维度数</label>
              <input type="number" min={0} value={form.required_dimension_count}
                onChange={e => update('required_dimension_count', parseInt(e.target.value) || 0)} style={inp} />
            </div>
            <div>
              <label style={lbl}>图表建议</label>
              <select value={form.visualization_hint} onChange={e => update('visualization_hint', e.target.value)} style={inp}>
                {VIZ_HINTS.map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
          </div>

          {/* Intent types */}
          <div>
            <label style={lbl}>触发意图类型</label>
            <div style={{ display: 'flex', gap: 6 }}>
              <select value={intentInput} onChange={e => setIntentInput(e.target.value)} style={{ ...inp, flex: 1 }}>
                <option value="">选择意图...</option>
                {INTENT_TYPES.map(t => <option key={t} value={t}>{TYPE_LABELS[t] || t}</option>)}
              </select>
              <button onClick={addIntent} style={smBtn}>添加</button>
            </div>
            {form.required_intent_types.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
                {form.required_intent_types.map(t => (
                  <span key={t} style={chip}>
                    {TYPE_LABELS[t] || t}
                    <button onClick={() => update('required_intent_types', form.required_intent_types.filter(x => x !== t))} style={chipX}>×</button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* SQL template */}
          <div>
            <label style={lbl}>SQL 模板 (可选)</label>
            <textarea value={form.sql_template} onChange={e => update('sql_template', e.target.value)}
              placeholder="SELECT ... FROM ... WHERE ... GROUP BY ..."
              rows={4} style={{ ...inp, resize: 'vertical', fontFamily: 'monospace', fontSize: 12 }} />
          </div>

          {/* Plan template - Steps */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <label style={{ ...lbl, marginBottom: 0 }}>执行步骤 (DAG)</label>
              <button onClick={addStep} style={{ ...smBtn, display: 'flex', alignItems: 'center', gap: 4 }}>
                <Plus size={12} /> 添加步骤
              </button>
            </div>
            {form.plan_template.steps.length === 0 ? (
              <p style={{ fontSize: 12, color: '#9ca3af', padding: 12, textAlign: 'center', border: '1px dashed #e5e7eb', borderRadius: 6 }}>
                暂无步骤。点击"添加步骤"开始设计分析流程。
              </p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {form.plan_template.steps.map((step, idx) => (
                  <div key={step.id} style={{
                    padding: 10, border: '1px solid #e5e7eb', borderRadius: 6, background: '#fafbfc',
                    display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: 8, alignItems: 'center',
                  }}>
                    <GripVertical size={14} color="#d1d5db" />
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 2fr', gap: 6, alignItems: 'center' }}>
                      <input value={step.id} onChange={e => updateStep(idx, { id: e.target.value })}
                        placeholder="Step ID" style={{ ...inp, fontFamily: 'monospace', fontSize: 11, padding: '4px 6px' }} />
                      <select value={step.agent} onChange={e => updateStep(idx, { agent: e.target.value })} style={{ ...inp, fontSize: 11, padding: '4px 6px' }}>
                        {AGENT_TYPES.map(a => <option key={a} value={a}>{a}</option>)}
                      </select>
                      <input value={step.description} onChange={e => updateStep(idx, { description: e.target.value })}
                        placeholder="步骤描述..." style={{ ...inp, fontSize: 11, padding: '4px 6px' }} />
                    </div>
                    <button onClick={() => removeStep(idx)} style={{ ...iconBtn, color: '#dc2626' }}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Parameters */}
          <div>
            <label style={lbl}>模板参数 (可选)</label>
            <div style={{ display: 'flex', gap: 6 }}>
              <input value={paramKey} onChange={e => setParamKey(e.target.value)}
                placeholder="参数名 (如 time_window)" style={{ ...inp, flex: 1, fontSize: 12 }} />
              <input value={paramVal} onChange={e => setParamVal(e.target.value)}
                placeholder="类型 (如 string)" style={{ ...inp, width: 100, fontSize: 12 }} />
              <input value={paramDefVal} onChange={e => setParamDefVal(e.target.value)}
                placeholder="默认值" style={{ ...inp, width: 100, fontSize: 12 }} />
              <button onClick={addParameter} style={smBtn}>添加</button>
            </div>
            {form.plan_template.parameters && Object.keys(form.plan_template.parameters).length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
                {Object.entries(form.plan_template.parameters).map(([k, v]: [string, any]) => (
                  <span key={k} style={{ ...chip, fontFamily: 'monospace' }}>
                    ${k}: {v.type}{v.default ? ` = ${v.default}` : ''}
                    <button onClick={() => removeParameter(k)} style={chipX}>×</button>
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
