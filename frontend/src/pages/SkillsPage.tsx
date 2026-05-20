import { useEffect, useState } from 'react'
import { ChevronLeft, Wrench, Plus, Trash2, Play, Save, Code, FileText, TestTube } from 'lucide-react'
import { t } from '../i18n'
import { useAuthStore } from '../store/auth'
import {
  apiListSkills,
  apiCreateSkill,
  apiGetSkill,
  apiTestSkill,
  apiUninstallSkill,
  type SkillItem,
} from '../api/client'

type ViewMode = 'list' | 'create' | 'detail' | 'test'

export default function SkillsPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((s) => s.token)!
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [view, setView] = useState<ViewMode>('list')
  const [selectedSkill, setSelectedSkill] = useState<SkillItem | null>(null)
  const [output, setOutput] = useState('')
  const [loading, setLoading] = useState(false)

  // Create form
  const [name, setName] = useState('')
  const [version, setVersion] = useState('0.1.0')
  const [entrypoint, setEntrypoint] = useState('main.py')
  const [code, setCode] = useState('')
  const [description, setDescription] = useState('')
  const [skillType, setSkillType] = useState('generic')
  const [testCasesJson, setTestCasesJson] = useState('')
  const [dataSourceId, setDataSourceId] = useState('')

  // Test form
  const [testInputJson, setTestInputJson] = useState('{}')

  const load = async () => {
    try {
      const ss = await apiListSkills(token)
      setSkills(Array.isArray(ss) ? ss : [])
    } catch (e) {
      console.error('load skills failed', e)
      setSkills([])
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const resetCreateForm = () => {
    setName('')
    setVersion('0.1.0')
    setEntrypoint('main.py')
    setCode('')
    setDescription('')
    setSkillType('generic')
    setTestCasesJson('')
    setDataSourceId('')
  }

  const handleCreate = async () => {
    if (!name.trim()) return
    setLoading(true)
    setOutput('')
    try {
      const testCases = testCasesJson.trim() ? JSON.parse(testCasesJson) : []
      await apiCreateSkill(token, {
        name: name.trim(),
        version: version.trim() || '0.1.0',
        entrypoint: entrypoint.trim() || 'main.py',
        code: code,
        description: description.trim(),
        skill_type: skillType,
        test_cases: testCases,
        data_source_id: dataSourceId.trim(),
      })
      setOutput('Skill created successfully!')
      resetCreateForm()
      await load()
      setView('list')
    } catch (e: any) {
      setOutput(`Create failed: ${e?.message || e}`)
    } finally {
      setLoading(false)
    }
  }

  const handleSelectSkill = async (skill: SkillItem) => {
    setLoading(true)
    try {
      const detail = await apiGetSkill(token, skill.skill_id || skill.id)
      setSelectedSkill(detail)
      setView('detail')
      setOutput('')
    } catch (e: any) {
      setOutput(`Failed to load skill: ${e?.message || e}`)
    } finally {
      setLoading(false)
    }
  }

  const handleUninstall = async (id: string) => {
    try {
      await apiUninstallSkill(token, id)
      await load()
      if (selectedSkill && (selectedSkill.skill_id === id || selectedSkill.id === id)) {
        setSelectedSkill(null)
        setView('list')
      }
    } catch (e: any) {
      setOutput(`Uninstall failed: ${e?.message || e}`)
    }
  }

  const handleTest = async () => {
    if (!selectedSkill) return
    setLoading(true)
    setOutput('')
    try {
      const input = JSON.parse(testInputJson)
      const result = await apiTestSkill(token, selectedSkill.skill_id || selectedSkill.id, input)
      setOutput(JSON.stringify(result.result, null, 2))
    } catch (e: any) {
      setOutput(`Test failed: ${e?.message || e}`)
    } finally {
      setLoading(false)
    }
  }

  const defaultCodeTemplate = `def execute(input: dict) -> dict:
    """Skill entry point — receives a dict, returns a dict."""
    return {
        "status": "ok",
        "message": f"Received: {input}",
    }
`

  return (
    <div className="flex flex-col h-screen bg-[var(--bg)] text-[var(--text)]">
      <div className="flex items-center gap-3 px-6 h-14 border-b border-[var(--border)]">
        <button onClick={onBack} className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
        <h1 className="text-sm font-semibold inline-flex items-center gap-2"><Wrench size={15} /> {t('nav.skills') || 'Skills'}</h1>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {view === 'list' && (
          <div className="max-w-4xl mx-auto space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold">Installed Skills</h2>
              <button
                onClick={() => { resetCreateForm(); setCode(defaultCodeTemplate); setView('create') }}
                className="px-3 py-1.5 rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-xs inline-flex items-center gap-1.5"
              >
                <Plus size={13} /> Create Skill
              </button>
            </div>

            {skills.length === 0 ? (
              <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-8 text-center">
                <p className="text-sm text-[var(--text-secondary)]">No skills installed. Create one to get started.</p>
              </div>
            ) : (
              <div className="grid gap-3">
                {skills.map((s) => (
                  <div key={s.skill_id || s.id} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 flex items-center justify-between">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{s.name || s.id}</p>
                      <p className="text-xs text-[var(--text-secondary)]">
                        v{s.version} · {s.skill_type || 'generic'} · {s.entrypoint || 'main.py'}
                      </p>
                      {s.description && <p className="text-xs text-[var(--text-secondary)] mt-1 truncate">{s.description}</p>}
                    </div>
                    <div className="flex items-center gap-2">
                      <button onClick={() => void handleSelectSkill(s)} className="px-2 py-1 rounded border text-xs inline-flex items-center gap-1 hover:bg-[var(--surface-raised)]">
                        <FileText size={12} /> Detail
                      </button>
                      <button onClick={() => void handleUninstall(s.skill_id || s.id)} className="px-2 py-1 rounded border border-red-300 text-red-500 text-xs inline-flex items-center gap-1 hover:bg-red-50">
                        <Trash2 size={12} /> Remove
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {view === 'create' && (
          <div className="max-w-4xl mx-auto space-y-4">
            <div className="flex items-center gap-3">
              <button onClick={() => setView('list')} className="text-xs text-[var(--text-secondary)] hover:text-[var(--text)]">&larr; Back</button>
              <h2 className="text-base font-semibold">Create Skill</h2>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-4">
                <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-3">
                  <h3 className="text-sm font-semibold">Metadata</h3>
                  <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Skill name" className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm" />
                  <div className="grid grid-cols-2 gap-2">
                    <input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="version" className="rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm" />
                    <input value={entrypoint} onChange={(e) => setEntrypoint(e.target.value)} placeholder="entrypoint" className="rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm" />
                  </div>
                  <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Description" className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm" />
                  <select value={skillType} onChange={(e) => setSkillType(e.target.value)} className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm">
                    <option value="generic">Generic</option>
                    <option value="data_query">Data Query</option>
                    <option value="text_analysis">Text Analysis</option>
                    <option value="code_gen">Code Generation</option>
                  </select>
                  <input value={dataSourceId} onChange={(e) => setDataSourceId(e.target.value)} placeholder="Data source ID (optional)" className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm" />
                </div>

                <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-2">
                  <h3 className="text-sm font-semibold inline-flex items-center gap-1.5"><TestTube size={13} /> Test Cases (JSON array)</h3>
                  <textarea
                    value={testCasesJson}
                    onChange={(e) => setTestCasesJson(e.target.value)}
                    placeholder={`[{"input": {"query": "hello"}, "expected": {"status": "ok"}}]`}
                    rows={4}
                    className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs font-mono"
                  />
                </div>
              </div>

              <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-2">
                <h3 className="text-sm font-semibold inline-flex items-center gap-1.5"><Code size={13} /> Code</h3>
                <textarea
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  rows={18}
                  className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs font-mono"
                />
              </div>
            </div>

            {output && (
              <pre className="text-xs whitespace-pre-wrap rounded border border-[var(--border)] p-3 bg-black/20">{output}</pre>
            )}

            <button onClick={() => void handleCreate()} disabled={loading || !name.trim()} className="px-4 py-2 rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-sm inline-flex items-center gap-1.5 disabled:opacity-50">
              <Save size={14} /> {loading ? 'Creating...' : 'Create'}
            </button>
          </div>
        )}

        {view === 'detail' && selectedSkill && (
          <div className="max-w-4xl mx-auto space-y-4">
            <div className="flex items-center gap-3">
              <button onClick={() => { setView('list'); setSelectedSkill(null) }} className="text-xs text-[var(--text-secondary)] hover:text-[var(--text)]">&larr; Back</button>
              <h2 className="text-base font-semibold">{selectedSkill.name}</h2>
              <span className="text-xs text-[var(--text-secondary)]">v{selectedSkill.version}</span>
            </div>

            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-2">
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div><span className="text-[var(--text-secondary)]">Type:</span> {selectedSkill.skill_type || 'generic'}</div>
                <div><span className="text-[var(--text-secondary)]">Entrypoint:</span> {selectedSkill.entrypoint}</div>
                {selectedSkill.data_source_id && <div><span className="text-[var(--text-secondary)]">Data Source:</span> {selectedSkill.data_source_id}</div>}
              </div>
              {selectedSkill.description && <p className="text-sm text-[var(--text-secondary)]">{selectedSkill.description}</p>}
            </div>

            {selectedSkill.code && (
              <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-2">
                <h3 className="text-sm font-semibold inline-flex items-center gap-1.5"><Code size={13} /> Code</h3>
                <pre className="text-xs font-mono whitespace-pre-wrap rounded border border-[var(--border)] p-3 bg-black/20 max-h-64 overflow-y-auto">{selectedSkill.code}</pre>
              </div>
            )}

            {selectedSkill.test_cases && selectedSkill.test_cases.length > 0 && (
              <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-2">
                <h3 className="text-sm font-semibold inline-flex items-center gap-1.5"><TestTube size={13} /> Test Cases</h3>
                <pre className="text-xs font-mono whitespace-pre-wrap rounded border border-[var(--border)] p-3 bg-black/20 max-h-48 overflow-y-auto">{JSON.stringify(selectedSkill.test_cases, null, 2)}</pre>
              </div>
            )}

            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-3">
              <h3 className="text-sm font-semibold inline-flex items-center gap-1.5"><Play size={13} /> Test Skill</h3>
              <textarea
                value={testInputJson}
                onChange={(e) => setTestInputJson(e.target.value)}
                rows={3}
                className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs font-mono"
                placeholder='{"query": "your test input"}'
              />
              <button onClick={() => void handleTest()} disabled={loading} className="px-3 py-1.5 rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-xs inline-flex items-center gap-1.5 disabled:opacity-50">
                <Play size={12} /> {loading ? 'Running...' : 'Run Test'}
              </button>
            </div>

            {output && (
              <pre className="text-xs whitespace-pre-wrap rounded border border-[var(--border)] p-3 bg-black/20 max-h-64 overflow-y-auto">{output}</pre>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
