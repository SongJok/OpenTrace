import { useEffect, useState } from 'react'
import { ChevronLeft, FileCode, Plus, Trash2, Pencil, Eye, Copy, FileText, Download, Wand2 } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import {
  apiListRules,
  apiGetRule,
  apiCreateRule,
  apiUpdateRule,
  apiDeleteRule,
  apiGenerateRule,
  type RuleItem,
  type RuleFormData,
} from '../api/client'

export default function RulesPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((s) => s.token)!
  const [rules, setRules] = useState<RuleItem[]>([])
  const [selected, setSelected] = useState<RuleItem | null>(null)
  const [showEditor, setShowEditor] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [showYamlPreview, setShowYamlPreview] = useState(false)
  const [yamlContent, setYamlContent] = useState('')

  // Form state
  const [form, setForm] = useState<RuleFormData>({
    id: '', name: '', trigger: '', description: '', version: '1.0',
    data_sources: [{ label: '', type: 'query', description: '', sql: '' }],
    conditions: [{ id: '', data_ref: '', expr: '' }],
    outputs: [{ label: '', when: [], template: '' }],
  })

  const load = async () => {
    try {
      const list = await apiListRules(token)
      setRules(list)
      if (selected) {
        const refreshed = list.find((x) => x.id === selected.id)
        if (refreshed) setSelected(refreshed)
      }
    } catch { setRules([]) }
  }

  useEffect(() => { void load() }, [])

  const beginCreate = () => {
    setEditingId(null)
    setForm({
      id: '', name: '', trigger: '', description: '', version: '1.0',
      data_sources: [{ label: '', type: 'query', description: '', sql: '' }],
      conditions: [{ id: '', data_ref: '', expr: '' }],
      outputs: [{ label: '', when: [], template: '' }],
    })
    setShowEditor(true)
  }

  const beginEdit = async (rule: RuleItem) => {
    setEditingId(rule.id)
    try {
      const full = await apiGetRule(token, rule.filename)
      setForm({
        id: full.id || rule.id,
        name: full.name || '',
        trigger: full.trigger || '',
        description: full.description || '',
        version: full.version || '1.0',
        data_sources: (full.data_sources || []).length > 0
          ? full.data_sources
          : [{ label: '', type: 'query', description: '', sql: '' }],
        conditions: (full.conditions || []).length > 0
          ? full.conditions
          : [{ id: '', data_ref: '', expr: '' }],
        outputs: (full.outputs || []).length > 0
          ? full.outputs
          : [{ label: '', when: [], template: '' }],
      })
      setShowEditor(true)
    } catch {
      // Fallback: just use summary data
      setForm({
        id: rule.id, name: rule.name, trigger: rule.trigger, description: rule.description, version: rule.version,
        data_sources: [{ label: '', type: 'query', description: '', sql: '' }],
        conditions: [{ id: '', data_ref: '', expr: '' }],
        outputs: [{ label: '', when: [], template: '' }],
      })
      setShowEditor(true)
    }
  }

  const viewRule = async (rule: RuleItem) => {
    try {
      const full = await apiGetRule(token, rule.filename)
      setYamlContent(full.yaml_raw || JSON.stringify(full, null, 2))
      setShowYamlPreview(true)
    } catch {
      alert('无法加载规则详情')
    }
  }

  const saveRule = async () => {
    if (!form.id.trim()) { alert('规则 ID 不能为空'); return }
    if (!form.name.trim()) { alert('规则名称不能为空'); return }
    if (!form.trigger.trim()) { alert('触发词不能为空'); return }
    setSaving(true)
    try {
      const payload = { ...form }
      if (editingId) {
        await apiUpdateRule(token, editingId + '.yml', payload)
      } else {
        await apiCreateRule(token, payload)
      }
      setShowEditor(false)
      setEditingId(null)
      await load()
    } catch (e: any) {
      alert(e?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const removeRule = async (rule: RuleItem) => {
    if (!confirm(`确认删除规则「${rule.name}」?`)) return
    try {
      await apiDeleteRule(token, rule.filename)
      if (selected?.id === rule.id) setSelected(null)
      await load()
    } catch (e: any) {
      alert(e?.message || '删除失败')
    }
  }

  // YAML Generator
  const [showGenerator, setShowGenerator] = useState(false)
  const [genForm, setGenForm] = useState({
    id: '', name: '', trigger: '', description: '',
    dataSourcesCount: 1, conditionsCount: 1, outputsCount: 1,
  })
  const [genResult, setGenResult] = useState('')

  const handleGenerate = async () => {
    if (!genForm.id.trim() || !genForm.trigger.trim()) {
      alert('请填写规则 ID 和触发词')
      return
    }
    try {
      const result = await apiGenerateRule(token, genForm)
      setGenResult(result.yaml_content)
    } catch (e: any) {
      alert(e?.message || '生成失败')
    }
  }

  const applyGenerated = () => {
    if (genResult) {
      setYamlContent(genResult)
      setShowGenerator(false)
      setShowYamlPreview(true)
    }
  }

  const [saving, setSaving] = useState(false)

  return (
    <div className="flex flex-col h-screen bg-[var(--bg)] text-[var(--text)]">
      <div className="flex items-center gap-3 px-6 h-14 border-b border-[var(--border)] flex-shrink-0">
        <button onClick={onBack} className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
        <h1 className="text-sm font-semibold inline-flex items-center gap-2"><FileCode size={16} /> 规则管理</h1>
      </div>

      <div className="grid grid-cols-12 gap-4 p-4 flex-1 overflow-hidden">
        {/* Left: rule list */}
        <div className="col-span-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 overflow-y-auto">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold">规则列表</h2>
            <div className="flex gap-1">
              <button className="px-2 py-1 rounded border text-xs inline-flex items-center gap-1" onClick={() => setShowGenerator(true)}>
                <Wand2 size={12} /> 生成
              </button>
              <button className="px-2 py-1 rounded border text-xs inline-flex items-center gap-1" onClick={beginCreate}>
                <Plus size={12} /> 新建
              </button>
            </div>
          </div>

          {rules.length === 0 ? (
            <div className="text-xs text-[var(--text-secondary)] text-center py-8">暂无规则</div>
          ) : (
            <div className="space-y-2">
              {rules.map((r) => (
                <div key={r.id} className={`rounded border p-3 text-xs cursor-pointer transition-colors ${selected?.id === r.id ? 'border-[var(--accent)] bg-[var(--accent-dim)]' : 'border-[var(--border)] hover:border-[var(--accent-border)]'}`} onClick={() => { setSelected(r); void viewRule(r) }}>
                  <div className="flex items-center justify-between">
                    <div className="font-medium text-sm">{r.name}</div>
                    <div className="flex items-center gap-1">
                      <button onClick={(e) => { e.stopPropagation(); void viewRule(r) }} className="text-slate-400 hover:text-[var(--accent)]"><Eye size={13} /></button>
                      <button onClick={(e) => { e.stopPropagation(); void beginEdit(r) }} className="text-slate-400 hover:text-sky-500"><Pencil size={13} /></button>
                      <button onClick={(e) => { e.stopPropagation(); void removeRule(r) }} className="text-slate-400 hover:text-red-500"><Trash2 size={13} /></button>
                    </div>
                  </div>
                  <div className="text-[var(--text-secondary)] mt-1">{r.trigger}</div>
                  <div className="text-[var(--text-secondary)] mt-0.5">{r.description || '无描述'}</div>
                  <div className="flex gap-3 mt-2 text-[10px] text-[var(--text-secondary)]">
                    <span>数据源: {r.data_sources_count}</span>
                    <span>条件: {r.conditions_count}</span>
                    <span>输出: {r.outputs_count}</span>
                    <span>v{r.version}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right: YAML preview or form editor */}
        <div className="col-span-8 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 overflow-y-auto">
          {showYamlPreview ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold inline-flex items-center gap-2"><FileText size={14} /> YAML 预览</h2>
                <div className="flex gap-2">
                  <button className="px-2 py-1 rounded border text-xs inline-flex items-center gap-1" onClick={() => { navigator.clipboard.writeText(yamlContent); alert('已复制') }}>
                    <Copy size={12} /> 复制
                  </button>
                  <button className="px-2 py-1 rounded border text-xs inline-flex items-center gap-1" onClick={() => {
                    const blob = new Blob([yamlContent], { type: 'text/yaml' })
                    const url = URL.createObjectURL(blob)
                    const a = document.createElement('a')
                    a.href = url
                    a.download = selected?.filename || 'rule.yml'
                    a.click()
                    URL.revokeObjectURL(url)
                  }}>
                    <Download size={12} /> 下载
                  </button>
                  <button className="px-2 py-1 rounded border text-xs" onClick={() => setShowYamlPreview(false)}>关闭</button>
                </div>
              </div>
              <pre className="text-xs whitespace-pre-wrap rounded border border-[var(--border)] p-4 bg-black/20 font-mono max-h-[60vh] overflow-y-auto">{yamlContent}</pre>
            </div>
          ) : showEditor ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold">{editingId ? '编辑规则' : '新建规则'}</h2>
                <button className="px-2 py-1 rounded border text-xs" onClick={() => { setShowEditor(false); setEditingId(null) }}>取消</button>
              </div>

              {/* Basic info */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-[var(--text-secondary)]">规则 ID</label>
                  <input className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })} placeholder="如 sister_group_reward" disabled={!!editingId} />
                </div>
                <div>
                  <label className="text-xs text-[var(--text-secondary)]">规则名称</label>
                  <input className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如 姐妹团奖励规则" />
                </div>
                <div>
                  <label className="text-xs text-[var(--text-secondary)]">触发词</label>
                  <input className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" value={form.trigger} onChange={(e) => setForm({ ...form, trigger: e.target.value })} placeholder="如 姐妹团" />
                </div>
                <div>
                  <label className="text-xs text-[var(--text-secondary)]">版本</label>
                  <input className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} />
                </div>
              </div>
              <div>
                <label className="text-xs text-[var(--text-secondary)]">描述</label>
                <input className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="规则用途描述" />
              </div>

              {/* Data sources */}
              <div className="space-y-2">
                <h3 className="text-xs font-semibold">数据源</h3>
                {form.data_sources.map((ds, i) => (
                  <div key={i} className="rounded border border-[var(--border)] p-2 space-y-2">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-[var(--text-secondary)]">数据源 #{i + 1}</span>
                      {form.data_sources.length > 1 && (
                        <button onClick={() => { const next = [...form.data_sources]; next.splice(i, 1); setForm({ ...form, data_sources: next }) }} className="text-red-500"><Trash2 size={11} /></button>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <input className="rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" placeholder="label" value={ds.label} onChange={(e) => { const next = [...form.data_sources]; next[i] = { ...next[i], label: e.target.value }; setForm({ ...form, data_sources: next }) }} />
                      <select className="rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" value={ds.type} onChange={(e) => { const next = [...form.data_sources]; next[i] = { ...next[i], type: e.target.value }; setForm({ ...form, data_sources: next }) }}>
                        <option value="query">query (数据库查询)</option>
                        <option value="static">static (静态数据)</option>
                      </select>
                    </div>
                    <input className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" placeholder="描述" value={ds.description || ''} onChange={(e) => { const next = [...form.data_sources]; next[i] = { ...next[i], description: e.target.value }; setForm({ ...form, data_sources: next }) }} />
                    {ds.type === 'query' ? (
                      <textarea className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs font-mono" rows={2} placeholder="SQL 语句" value={ds.sql || ''} onChange={(e) => { const next = [...form.data_sources]; next[i] = { ...next[i], sql: e.target.value }; setForm({ ...form, data_sources: next }) }} />
                    ) : null}
                  </div>
                ))}
                <button className="px-2 py-1 rounded border text-xs inline-flex items-center gap-1" onClick={() => setForm({ ...form, data_sources: [...form.data_sources, { label: '', type: 'query', description: '', sql: '' }] })}>
                  <Plus size={11} /> 添加数据源
                </button>
              </div>

              {/* Conditions */}
              <div className="space-y-2">
                <h3 className="text-xs font-semibold">条件</h3>
                {form.conditions.map((cond, i) => (
                  <div key={i} className="rounded border border-[var(--border)] p-2 space-y-2">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-[var(--text-secondary)]">条件 #{i + 1}</span>
                      {form.conditions.length > 1 && (
                        <button onClick={() => { const next = [...form.conditions]; next.splice(i, 1); setForm({ ...form, conditions: next }) }} className="text-red-500"><Trash2 size={11} /></button>
                      )}
                    </div>
                    <div className="grid grid-cols-3 gap-2">
                      <input className="rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" placeholder="条件 ID" value={cond.id} onChange={(e) => { const next = [...form.conditions]; next[i] = { ...next[i], id: e.target.value }; setForm({ ...form, conditions: next }) }} />
                      <input className="rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" placeholder="数据引用 label" value={cond.data_ref} onChange={(e) => { const next = [...form.conditions]; next[i] = { ...next[i], data_ref: e.target.value }; setForm({ ...form, conditions: next }) }} />
                      <input className="rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" placeholder="表达式" value={cond.expr} onChange={(e) => { const next = [...form.conditions]; next[i] = { ...next[i], expr: e.target.value }; setForm({ ...form, conditions: next }) }} />
                    </div>
                  </div>
                ))}
                <button className="px-2 py-1 rounded border text-xs inline-flex items-center gap-1" onClick={() => setForm({ ...form, conditions: [...form.conditions, { id: '', data_ref: '', expr: '' }] })}>
                  <Plus size={11} /> 添加条件
                </button>
              </div>

              {/* Outputs */}
              <div className="space-y-2">
                <h3 className="text-xs font-semibold">输出</h3>
                {form.outputs.map((out, i) => (
                  <div key={i} className="rounded border border-[var(--border)] p-2 space-y-2">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-[var(--text-secondary)]">输出 #{i + 1}</span>
                      {form.outputs.length > 1 && (
                        <button onClick={() => { const next = [...form.outputs]; next.splice(i, 1); setForm({ ...form, outputs: next }) }} className="text-red-500"><Trash2 size={11} /></button>
                      )}
                    </div>
                    <div className="grid grid-cols-3 gap-2">
                      <input className="rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" placeholder="标签" value={out.label} onChange={(e) => { const next = [...form.outputs]; next[i] = { ...next[i], label: e.target.value }; setForm({ ...form, outputs: next }) }} />
                      <input className="rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs col-span-2" placeholder="when 条件 ID 列表（逗号分隔）" value={out.when.join(', ')} onChange={(e) => { const next = [...form.outputs]; next[i] = { ...next[i], when: e.target.value.split(',').map(s => s.trim()).filter(Boolean) }; setForm({ ...form, outputs: next }) }} />
                    </div>
                    <textarea className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" rows={2} placeholder="输出模板（支持 {{data_ref.field}} 和 {{flag:condition_id}}）" value={out.template} onChange={(e) => { const next = [...form.outputs]; next[i] = { ...next[i], template: e.target.value }; setForm({ ...form, outputs: next }) }} />
                  </div>
                ))}
                <button className="px-2 py-1 rounded border text-xs inline-flex items-center gap-1" onClick={() => setForm({ ...form, outputs: [...form.outputs, { label: '', when: [], template: '' }] })}>
                  <Plus size={11} /> 添加输出
                </button>
              </div>

              <button disabled={saving} className="w-full rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-xs py-1.5 disabled:opacity-50" onClick={() => void saveRule()}>
                {saving ? '保存中...' : (editingId ? '保存修改' : '创建规则')}
              </button>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <FileCode size={48} className="text-[var(--text-secondary)] mb-4" />
              <p className="text-sm text-[var(--text-secondary)]">选择左侧规则查看 YAML 预览</p>
              <p className="text-xs text-[var(--text-secondary)] mt-1">或点击「新建」/「生成」创建规则</p>
            </div>
          )}
        </div>
      </div>

      {/* YAML Generator Modal */}
      {showGenerator && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setShowGenerator(false)}>
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 w-full max-w-lg max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-sm font-semibold mb-4 inline-flex items-center gap-2"><Wand2 size={16} /> YAML 规则生成器</h2>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-[var(--text-secondary)]">规则 ID</label>
                  <input className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" value={genForm.id} onChange={(e) => setGenForm({ ...genForm, id: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })} placeholder="如 product_sales" />
                </div>
                <div>
                  <label className="text-xs text-[var(--text-secondary)]">规则名称</label>
                  <input className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" value={genForm.name} onChange={(e) => setGenForm({ ...genForm, name: e.target.value })} placeholder="如 产品销售规则" />
                </div>
                <div>
                  <label className="text-xs text-[var(--text-secondary)]">触发词</label>
                  <input className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" value={genForm.trigger} onChange={(e) => setGenForm({ ...genForm, trigger: e.target.value })} placeholder="如 销售" />
                </div>
                <div>
                  <label className="text-xs text-[var(--text-secondary)]">描述</label>
                  <input className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-xs" value={genForm.description} onChange={(e) => setGenForm({ ...genForm, description: e.target.value })} placeholder="规则描述" />
                </div>
              </div>
              <div className="flex gap-4 text-xs">
                <label className="inline-flex items-center gap-1">数据源: <input type="number" className="w-12 rounded border border-[var(--border)] bg-transparent px-1 py-0.5 text-center" value={genForm.dataSourcesCount} onChange={(e) => setGenForm({ ...genForm, dataSourcesCount: Math.max(0, Number(e.target.value)) })} /></label>
                <label className="inline-flex items-center gap-1">条件: <input type="number" className="w-12 rounded border border-[var(--border)] bg-transparent px-1 py-0.5 text-center" value={genForm.conditionsCount} onChange={(e) => setGenForm({ ...genForm, conditionsCount: Math.max(0, Number(e.target.value)) })} /></label>
                <label className="inline-flex items-center gap-1">输出: <input type="number" className="w-12 rounded border border-[var(--border)] bg-transparent px-1 py-0.5 text-center" value={genForm.outputsCount} onChange={(e) => setGenForm({ ...genForm, outputsCount: Math.max(0, Number(e.target.value)) })} /></label>
              </div>
              <button className="w-full rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-xs py-1.5" onClick={() => void handleGenerate()}>
                生成 YAML
              </button>
              {genResult && (
                <div className="space-y-2">
                  <pre className="text-xs whitespace-pre-wrap rounded border border-[var(--border)] p-3 bg-black/20 font-mono max-h-48 overflow-y-auto">{genResult}</pre>
                  <div className="flex gap-2">
                    <button className="flex-1 rounded border text-xs py-1 inline-flex items-center justify-center gap-1" onClick={() => { navigator.clipboard.writeText(genResult); alert('已复制') }}><Copy size={12} /> 复制</button>
                    <button className="flex-1 rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-xs py-1" onClick={applyGenerated}>应用到编辑器</button>
                  </div>
                </div>
              )}
            </div>
            <button className="mt-4 w-full rounded border text-xs py-1.5" onClick={() => setShowGenerator(false)}>关闭</button>
          </div>
        </div>
      )}
    </div>
  )
}
