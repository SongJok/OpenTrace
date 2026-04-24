import { useEffect, useState } from 'react'
import { ChevronLeft, Plug, Wrench, Download, Trash2, KeyRound, RefreshCw, FolderTree } from 'lucide-react'
import { t } from '../i18n'
import { useAuthStore } from '../store/auth'
import {
  apiConnectorAuthorize,
  apiConnectorCallback,
  apiConnectorResources,
  apiConnectorSync,
  apiInstallSkill,
  apiListConnectors,
  apiListSkills,
  apiUninstallSkill,
  type ConnectorItem,
  type SkillItem,
} from '../api/client'

export default function IntegrationsPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((s) => s.token)!
  const [connectors, setConnectors] = useState<ConnectorItem[]>([])
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [gitUrl, setGitUrl] = useState('')
  const [ref, setRef] = useState('main')
  const [provider, setProvider] = useState('github')
  const [redirectUri, setRedirectUri] = useState('http://localhost/callback')
  const [authCode, setAuthCode] = useState('')
  const [connectorOutput, setConnectorOutput] = useState('')

  const load = async () => {
    try {
      const [cs, ss] = await Promise.all([apiListConnectors(token), apiListSkills(token)])
      setConnectors(Array.isArray(cs) ? cs : [])
      setSkills(Array.isArray(ss) ? ss : [])
    } catch (e) {
      console.error('load integrations failed', e)
      setConnectors([])
      setSkills([])
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const install = async () => {
    if (!gitUrl.trim()) return
    await apiInstallSkill(token, gitUrl.trim(), ref.trim() || 'main')
    setGitUrl('')
    await load()
  }

  const uninstall = async (id: string) => {
    await apiUninstallSkill(token, id)
    await load()
  }

  const authorize = async () => {
    const data = await apiConnectorAuthorize(token, provider, redirectUri)
    setConnectorOutput(JSON.stringify(data, null, 2))
  }

  const callback = async () => {
    if (!authCode.trim()) return
    const data = await apiConnectorCallback(token, provider, authCode.trim(), redirectUri)
    setConnectorOutput(JSON.stringify(data, null, 2))
  }

  const resources = async () => {
    const data = await apiConnectorResources(token, provider)
    setConnectorOutput(JSON.stringify(data, null, 2))
  }

  const sync = async () => {
    const data = await apiConnectorSync(token, provider)
    setConnectorOutput(JSON.stringify(data, null, 2))
  }

  return (
    <div className="flex flex-col h-screen bg-[var(--bg)] text-[var(--text)]">
      <div className="flex items-center gap-3 px-6 h-14 border-b border-[var(--border)]">
        <button onClick={onBack} className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
        <h1 className="text-sm font-semibold">{t('nav.integrations')}</h1>
      </div>

      <div className="grid grid-cols-12 gap-4 p-4 overflow-y-auto">
        <div className="col-span-6 space-y-4">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <h2 className="text-sm font-semibold inline-flex items-center gap-2 mb-3"><Plug size={14} /> Connectors</h2>
            {connectors.length === 0 ? <p className="text-sm text-[var(--text-secondary)]">暂无连接器</p> : (
              <div className="space-y-2">
                {connectors.map((c) => (
                  <div key={c.id} className="rounded border border-[var(--border)] p-3">
                    <p className="text-sm font-medium">{c.display_name || c.id}</p>
                    <p className="text-xs text-[var(--text-secondary)]">status={c.status}</p>
                    <p className="text-xs text-[var(--text-secondary)]">capabilities: {(c.capabilities || []).join(', ')}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-2">
            <h3 className="text-sm font-semibold">Connector 操作面板</h3>
            <input value={provider} onChange={(e) => setProvider(e.target.value)} placeholder="provider" className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-sm" />
            <input value={redirectUri} onChange={(e) => setRedirectUri(e.target.value)} placeholder="redirect_uri" className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-sm" />
            <input value={authCode} onChange={(e) => setAuthCode(e.target.value)} placeholder="code(用于 callback)" className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-sm" />
            <div className="flex flex-wrap gap-2">
              <button onClick={() => void authorize()} className="px-3 py-1.5 rounded border text-xs inline-flex items-center gap-1"><KeyRound size={12} /> authorize</button>
              <button onClick={() => void callback()} className="px-3 py-1.5 rounded border text-xs inline-flex items-center gap-1"><KeyRound size={12} /> callback</button>
              <button onClick={() => void resources()} className="px-3 py-1.5 rounded border text-xs inline-flex items-center gap-1"><FolderTree size={12} /> resources</button>
              <button onClick={() => void sync()} className="px-3 py-1.5 rounded border text-xs inline-flex items-center gap-1"><RefreshCw size={12} /> sync</button>
            </div>
            <pre className="text-xs whitespace-pre-wrap rounded border border-[var(--border)] p-2 bg-black/20 min-h-[120px]">{connectorOutput || '操作结果将在此显示'}</pre>
          </div>
        </div>

        <div className="col-span-6 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-3">
          <h2 className="text-sm font-semibold inline-flex items-center gap-2"><Wrench size={14} /> Skills</h2>
          <div className="rounded border border-[var(--border)] p-3 space-y-2">
            <p className="text-xs text-[var(--text-secondary)]">从 Git 安装技能</p>
            <input value={gitUrl} onChange={(e) => setGitUrl(e.target.value)} placeholder="git url" className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-sm" />
            <input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="ref" className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1 text-sm" />
            <button onClick={() => void install()} className="px-3 py-1.5 rounded bg-[var(--accent)] text-white text-xs inline-flex items-center gap-1"><Download size={12} /> 安装</button>
          </div>
          <div className="space-y-2">
            {skills.length === 0 ? <p className="text-sm text-[var(--text-secondary)]">暂无技能</p> : skills.map((s) => (
              <div key={s.id} className="rounded border border-[var(--border)] p-3 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">{s.name || s.id}</p>
                  <p className="text-xs text-[var(--text-secondary)]">{s.version}</p>
                </div>
                <button onClick={() => void uninstall(s.id)} className="px-2 py-1 rounded text-xs border border-red-300 text-red-500 inline-flex items-center gap-1"><Trash2 size={12} /> 卸载</button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
