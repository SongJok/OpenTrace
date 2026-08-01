import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { BrainCircuit, ChevronLeft, Check, Eye, EyeOff, KeyRound, LogOut, Moon, Monitor, Palette, Pencil, Plus, Sun, Trash2, X } from 'lucide-react'
import clsx from 'clsx'
import { useThemeStore, type AccentMode, type ThemeMode } from '../store/theme'
import { useAuthStore } from '../store/auth'
import { apiChangePassword, apiGetCustomInstructions, apiGetUiSettings, apiPatchUiSettings, apiSetCustomInstructions } from '../api/client'
import { CardShell } from '../components/CardShell'
import { apiCreateCustomModel, apiDeleteCustomModel, apiGetModelSettings, apiSelectModelSettings, apiUpdateCustomModel, withSelectedModel, type CustomModelInput, type CustomModelSettings, type ModelSource, type UserModelSettings } from '../api/modelSettings'
import { useCompanyStore } from '../store/company'

const THEME_OPTIONS: { value: ThemeMode; label: string; description: string; icon: ReactNode }[] = [
  { value: 'light', label: 'Light', description: '更适合白底阅读', icon: <Sun size={16} /> },
  { value: 'dark', label: 'Dark', description: '默认暗色体验', icon: <Moon size={16} /> },
  { value: 'system', label: 'System', description: '跟随系统设置', icon: <Monitor size={16} /> },
]

const ACCENT_OPTIONS: { value: AccentMode; label: string; description: string; preview: string }[] = [
  { value: 'white', label: 'White', description: '更克制、偏中性', preview: 'from-white/60 via-white/25 to-white/10' },
  { value: 'black', label: 'Black', description: '深色高对比', preview: 'from-black/80 via-black/55 to-white/5' },
  { value: 'warm', label: 'Warm', description: '偏暖的品牌色', preview: 'from-amber-400/80 via-orange-400/60 to-rose-400/30' },
]

function SectionCard({ eyebrow, title, meta, children }: { eyebrow: string; title: string; meta?: string; children: ReactNode }) {
  return (
    <section className="overflow-hidden rounded-[28px] border border-[var(--border)] bg-[var(--surface)] shadow-[0_18px_50px_rgba(0,0,0,0.18)] backdrop-blur-xl">
      <div className="h-1 bg-gradient-to-r from-[var(--accent)] via-[var(--accent)] to-transparent" />
      <div className="p-5">
        <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--text-secondary)]">{eyebrow}</div>
        <div className="mt-1 text-lg font-semibold tracking-[-0.02em] text-[var(--text)]">{title}</div>
        {meta ? <div className="mt-1 text-sm text-[var(--text-secondary)]">{meta}</div> : null}
        <div className="mt-4">{children}</div>
      </div>
    </section>
  )
}

function CustomModelDialog({
  open,
  model,
  saving,
  onClose,
  onSave,
}: {
  open: boolean
  model: CustomModelSettings | null
  saving: boolean
  onClose: () => void
  onSave: (payload: CustomModelInput, apiKey: string) => void
}) {
  const [name, setName] = useState('')
  const [provider, setProvider] = useState('自定义 / Custom')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [modelName, setModelName] = useState('')
  const [apiMode, setApiMode] = useState<CustomModelInput['api_mode']>('chat_completions')
  const [showApiKey, setShowApiKey] = useState(false)

  useEffect(() => {
    if (!open) return
    setName(model?.name || '')
    setProvider(model?.provider || '自定义 / Custom')
    setBaseUrl(model?.base_url || '')
    setApiKey('')
    setModelName(model?.model || '')
    setApiMode(model?.api_mode || 'chat_completions')
    setShowApiKey(false)
  }, [open, model])

  if (!open) return null
  const inputClass = 'mt-1.5 w-full rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2.5 text-sm text-[var(--text)] outline-none transition-colors focus:border-[var(--accent)]'
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-label={model ? '编辑模型' : '添加模型'}>
      <form
        className="max-h-[calc(100vh-2rem)] w-full max-w-2xl overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-2xl"
        onSubmit={(event) => {
          event.preventDefault()
          onSave({ name: name.trim(), provider: provider.trim(), base_url: baseUrl.trim(), model: modelName.trim(), api_mode: apiMode }, apiKey.trim())
        }}
      >
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
          <div className="flex min-w-0 items-center gap-3">
            <h3 className="text-lg font-semibold text-[var(--text)]">{model ? '编辑模型' : '添加模型'}</h3>
            <span className="truncate rounded-full border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--text-secondary)]">OpenAI 兼容协议</span>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭" className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] hover:text-[var(--text)]"><X size={18} /></button>
        </div>
        <div className="space-y-4 p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="text-xs text-[var(--text-secondary)]">显示名称<input required value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：我的开发模型" className={inputClass} /></label>
            <label className="text-xs text-[var(--text-secondary)]">提供商<input value={provider} onChange={(event) => setProvider(event.target.value)} className={inputClass} /></label>
          </div>
          <label className="block text-xs text-[var(--text-secondary)]">接口地址<input required type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://provider.example.com/v1" className={inputClass} /></label>
          <label className="block text-xs text-[var(--text-secondary)]">
            API Key {model ? '（留空表示保持现有密钥）' : ''}
            <div className="relative">
              <input required={!model} type={showApiKey ? 'text' : 'password'} autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={model?.api_key_masked || '输入 API Key'} className={`${inputClass} pr-11`} />
              <button type="button" onClick={() => setShowApiKey((current) => !current)} aria-label={showApiKey ? '隐藏 API Key' : '显示 API Key'} className="absolute right-1.5 top-3 grid h-8 w-8 place-items-center rounded-lg text-[var(--text-secondary)] hover:text-[var(--text)]">{showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}</button>
            </div>
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="text-xs text-[var(--text-secondary)]">模型名称<input required value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="例如：gpt-4.1-mini" className={inputClass} /></label>
            <label className="text-xs text-[var(--text-secondary)]">API 模式<select value={apiMode} onChange={(event) => setApiMode(event.target.value as CustomModelInput['api_mode'])} className={inputClass}><option value="chat_completions">Chat Completions</option><option value="responses">Responses API</option><option value="auto">自动判断</option></select></label>
          </div>
          <p className="text-xs leading-5 text-[var(--text-secondary)]">自定义模型需要支持 OpenAI 兼容请求。工具调用等能力由模型服务实际支持情况决定。</p>
        </div>
        <div className="flex justify-end gap-3 border-t border-[var(--border)] px-5 py-4">
          <button type="button" onClick={onClose} disabled={saving} className="rounded-xl border border-[var(--border)] px-4 py-2 text-sm text-[var(--text)] disabled:opacity-50">取消</button>
          <button type="submit" disabled={saving || !name.trim() || !baseUrl.trim() || !modelName.trim() || (!model && !apiKey.trim())} className="rounded-xl bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-foreground)] disabled:opacity-50">{saving ? '保存中…' : '保存'}</button>
        </div>
      </form>
    </div>
  )
}

const TRACE_UI_KEYS = {
  reasoning: 'opentrace:ui.reasoning.defaultExpanded',
  dag: 'opentrace:ui.dag.defaultExpanded',
  executionGraph: 'opentrace:ui.executionGraph.defaultExpanded',
  decisionTrace: 'opentrace:ui.decisionTrace.defaultExpanded',
  flowCards: 'opentrace:ui.flowCards.defaultExpanded',
} as const

function readLegacyBool(key: string) {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(key) === '1'
}

function readTraceSetting(key: keyof typeof TRACE_UI_KEYS, legacyKeys: string[]) {
  if (typeof window === 'undefined') return false
  const current = window.localStorage.getItem(TRACE_UI_KEYS[key])
  if (current !== null) return current === '1'
  for (const legacyKey of legacyKeys) {
    const legacy = window.localStorage.getItem(legacyKey)
    if (legacy !== null) {
      window.localStorage.setItem(TRACE_UI_KEYS[key], legacy)
      return legacy === '1'
    }
  }
  return false
}

function SwitchRow({
  label,
  checked,
  onToggle,
}: {
  label: string
  checked: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-full items-center justify-between rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-3 transition-colors hover:border-[var(--accent)] hover:bg-[var(--surface)]"
    >
      <span className="text-sm text-[var(--text)]">{label}</span>
      <span
        className={clsx(
          'relative inline-flex h-6 w-11 items-center rounded-full border transition-colors',
          checked ? 'border-[var(--accent)] bg-[var(--accent-dim)]' : 'border-[var(--border)] bg-[var(--surface)]'
        )}
      >
        <span
          className={clsx(
            'inline-block h-5 w-5 rounded-full bg-[var(--text)] transition-transform',
            checked ? 'translate-x-5 bg-[var(--accent)]' : 'translate-x-0'
          )}
        />
      </span>
    </button>
  )
}

export default function SettingsPage({ onBack }: { onBack: () => void }) {
  const brandName = useCompanyStore((state) => state.brandName)
  const { mode, setMode, accent, setAccent } = useThemeStore()
  const token = useAuthStore((s) => s.token)!
  const displayName = useAuthStore((s) => s.displayName)
  const email = useAuthStore((s) => s.email)
  const logout = useAuthStore((s) => s.logout)
  const [reasoningDefaultExpanded, setReasoningDefaultExpanded] = useState(false)
  const [dagDefaultExpanded, setDagDefaultExpanded] = useState(false)
  const [executionGraphDefaultExpanded, setExecutionGraphDefaultExpanded] = useState(false)
  const [decisionTraceDefaultExpanded, setDecisionTraceDefaultExpanded] = useState(false)
  const [flowCardsDefaultExpanded, setFlowCardsDefaultExpanded] = useState(false)
  const [customInstructionsEnabled, setCustomInstructionsEnabled] = useState(true)
  const [aboutUser, setAboutUser] = useState('')
  const [responseStyle, setResponseStyle] = useState('')
  const [savingCustomInstructions, setSavingCustomInstructions] = useState(false)
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordSaving, setPasswordSaving] = useState(false)
  const [passwordMessage, setPasswordMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [modelSettings, setModelSettings] = useState<UserModelSettings | null>(null)
  const [modelDialogOpen, setModelDialogOpen] = useState(false)
  const [editingCustomModel, setEditingCustomModel] = useState<CustomModelSettings | null>(null)
  const [modelSettingsSaving, setModelSettingsSaving] = useState(false)
  const [modelSettingsMessage, setModelSettingsMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const effectiveModeLabel = useMemo(() => (mode === 'system' ? 'System' : mode === 'light' ? 'Light' : 'Dark'), [mode])

  useEffect(() => {
    setReasoningDefaultExpanded(readTraceSetting('reasoning', ['opentrace:ui.reasoning.defaultExpanded']))
    setDagDefaultExpanded(readTraceSetting('dag', ['opentrace:ui.dag.defaultExpanded', 'opentrace:ui.graph.defaultExpanded']))
    setExecutionGraphDefaultExpanded(readTraceSetting('executionGraph', ['opentrace:ui.executionGraph.defaultExpanded', 'opentrace:ui.graph.defaultExpanded']))
    setDecisionTraceDefaultExpanded(readTraceSetting('decisionTrace', ['opentrace:ui.decisionTrace.defaultExpanded', 'opentrace:ui.graph.defaultExpanded']))
    setFlowCardsDefaultExpanded(readTraceSetting('flowCards', ['opentrace:ui.flowCards.defaultExpanded', 'opentrace:ui.graph.defaultExpanded']))

    void (async () => {
      try {
        const remote = await apiGetUiSettings(token)
        setReasoningDefaultExpanded(remote.reasoning_default_expanded)
        setDagDefaultExpanded(remote.dag_default_expanded)
        setExecutionGraphDefaultExpanded(remote.execution_graph_default_expanded)
        setDecisionTraceDefaultExpanded(remote.decision_trace_default_expanded)
        setFlowCardsDefaultExpanded(remote.flow_cards_default_expanded)
        if (remote.theme_mode) setMode(remote.theme_mode)
        if (remote.theme_accent) setAccent(remote.theme_accent)
        window.localStorage.setItem(TRACE_UI_KEYS.reasoning, remote.reasoning_default_expanded ? '1' : '0')
        window.localStorage.setItem(TRACE_UI_KEYS.dag, remote.dag_default_expanded ? '1' : '0')
        window.localStorage.setItem(TRACE_UI_KEYS.executionGraph, remote.execution_graph_default_expanded ? '1' : '0')
        window.localStorage.setItem(TRACE_UI_KEYS.decisionTrace, remote.decision_trace_default_expanded ? '1' : '0')
        window.localStorage.setItem(TRACE_UI_KEYS.flowCards, remote.flow_cards_default_expanded ? '1' : '0')
      } catch {
        // ignore remote failure, fallback to local settings
      }
    })()
  }, [token, setMode, setAccent])

  useEffect(() => {
    void (async () => {
      try {
        const instructions = await apiGetCustomInstructions(token)
        setAboutUser(instructions.about_user || '')
        setResponseStyle(instructions.response_style || '')
        setCustomInstructionsEnabled(instructions.enabled)
      } catch {
        // The rest of Settings remains usable if personalization is unavailable.
      }
    })()
  }, [token])

  useEffect(() => {
    void (async () => {
      try {
        setModelSettings(await apiGetModelSettings(token))
      } catch (error) {
        setModelSettingsMessage({ type: 'error', text: error instanceof Error ? error.message : '读取大模型配置失败' })
      }
    })()
  }, [token])

  const persistUiSettings = async (next?: Partial<{ reasoning_default_expanded: boolean; dag_default_expanded: boolean; execution_graph_default_expanded: boolean; decision_trace_default_expanded: boolean; flow_cards_default_expanded: boolean; theme_mode: ThemeMode; theme_accent: AccentMode }>) => {
    try {
      await apiPatchUiSettings(token, {
        reasoning_default_expanded: reasoningDefaultExpanded,
        dag_default_expanded: dagDefaultExpanded,
        execution_graph_default_expanded: executionGraphDefaultExpanded,
        decision_trace_default_expanded: decisionTraceDefaultExpanded,
        flow_cards_default_expanded: flowCardsDefaultExpanded,
        theme_mode: mode,
        theme_accent: accent,
        ...(next || {}),
      })
    } catch {
      // keep local optimistic state
    }
  }

  const saveCustomInstructions = async () => {
    setSavingCustomInstructions(true)
    try {
      const saved = await apiSetCustomInstructions(token, {
        about_user: aboutUser,
        response_style: responseStyle,
        enabled: customInstructionsEnabled,
      })
      setCustomInstructionsEnabled(saved.enabled)
    } finally {
      setSavingCustomInstructions(false)
    }
  }

  const saveCustomModel = async (payload: CustomModelInput, apiKey: string) => {
    if (modelSettingsSaving) return
    setModelSettingsSaving(true)
    setModelSettingsMessage(null)
    try {
      if (editingCustomModel) {
        await apiUpdateCustomModel(token, editingCustomModel.id, { ...payload, ...(apiKey ? { api_key: apiKey } : {}) })
      } else {
        await apiCreateCustomModel(token, { ...payload, api_key: apiKey })
      }
      setModelSettings(await apiGetModelSettings(token))
      setModelDialogOpen(false)
      setEditingCustomModel(null)
      setModelSettingsMessage({ type: 'success', text: editingCustomModel ? '模型配置已更新。' : '模型已添加，可立即选择使用。' })
    } catch (error) {
      setModelSettingsMessage({ type: 'error', text: error instanceof Error ? error.message : '保存模型失败' })
    } finally {
      setModelSettingsSaving(false)
    }
  }

  const deleteCustomModel = async (model: CustomModelSettings) => {
    if (modelSettingsSaving || !window.confirm(`删除模型“${model.name}”？`)) return
    setModelSettingsSaving(true)
    setModelSettingsMessage(null)
    try {
      await apiDeleteCustomModel(token, model.id)
      setModelSettings(await apiGetModelSettings(token))
      setModelSettingsMessage({ type: 'success', text: '自定义模型已删除。' })
    } catch (error) {
      setModelSettingsMessage({ type: 'error', text: error instanceof Error ? error.message : '删除模型失败' })
    } finally {
      setModelSettingsSaving(false)
    }
  }

  const activateModel = async (source: ModelSource, selected: string) => {
    if (!modelSettings || modelSettingsSaving) return
    const previous = modelSettings
    let optimistic: UserModelSettings
    try {
      optimistic = withSelectedModel(modelSettings, source, selected)
    } catch (error) {
      setModelSettingsMessage({ type: 'error', text: error instanceof Error ? error.message : '模型不可用' })
      return
    }
    setModelSettings(optimistic)
    setModelSettingsSaving(true)
    setModelSettingsMessage({ type: 'success', text: `正在切换到 ${optimistic.active_selection.model}…` })
    try {
      const saved = await apiSelectModelSettings(token, source, selected)
      setModelSettings(saved)
      setModelSettingsMessage({ type: 'success', text: `已切换到 ${saved.active_selection.model}，下一条新消息将使用该模型。` })
    } catch (error) {
      setModelSettings(previous)
      setModelSettingsMessage({ type: 'error', text: error instanceof Error ? error.message : '切换大模型失败' })
    } finally {
      setModelSettingsSaving(false)
    }
  }

  const changePassword = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setPasswordMessage(null)
    if (newPassword !== confirmPassword) {
      setPasswordMessage({ type: 'error', text: '两次输入的新密码不一致' })
      return
    }
    setPasswordSaving(true)
    try {
      const result = await apiChangePassword(token, oldPassword, newPassword)
      setOldPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setPasswordMessage({ type: 'success', text: result.message })
    } catch (error) {
      setPasswordMessage({
        type: 'error',
        text: error instanceof Error ? error.message : '修改密码失败',
      })
    } finally {
      setPasswordSaving(false)
    }
  }

  return (
    <div className="flex h-screen flex-col bg-[var(--bg)] text-[var(--text)]">
      <header className="flex h-16 items-center justify-between border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--bg)_90%,transparent)] px-6 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:border-[var(--accent)] hover:text-[var(--text)]"
          >
            <ChevronLeft size={18} />
          </button>
          <div>
            <div className="text-xs uppercase tracking-[0.22em] text-[var(--text-secondary)]">Settings</div>
            <div className="text-sm font-semibold text-[var(--text)]">统一颜色与界面行为</div>
          </div>
        </div>
        <div className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1 text-xs text-[var(--text-secondary)]">
          Effective: {effectiveModeLabel} · Accent: {accent}
        </div>
      </header>

      <main className="flex-1 overflow-y-auto bg-[var(--page-radial)] [background-image:var(--page-radial),var(--page-linear)]">
        <div className="mx-auto w-full max-w-3xl space-y-6 px-6 py-8">
          <SectionCard eyebrow="Account" title={displayName || 'Account'} meta={email || '—'}>
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-4">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--accent-dim)] text-sm font-bold text-[var(--accent)]">
                  {(displayName ?? 'U').slice(0, 2).toUpperCase()}
                </div>
                <div>
                  <p className="text-sm font-medium text-[var(--text)]">{displayName}</p>
                  <p className="text-xs text-[var(--text-secondary)]">{email}</p>
                </div>
              </div>
              <button
                onClick={logout}
                className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface-raised)] px-3 py-1.5 text-xs text-[var(--text-secondary)] transition-colors hover:border-[var(--accent)] hover:text-[var(--text)]"
              >
                <LogOut size={13} /> Sign out
              </button>
            </div>
            <form onSubmit={changePassword} className="mt-5 border-t border-[var(--border)] pt-5">
              <div className="mb-3 flex items-center gap-2">
                <KeyRound size={15} className="text-[var(--accent)]" />
                <div>
                  <p className="text-sm font-medium text-[var(--text)]">修改密码</p>
                  <p className="text-xs text-[var(--text-secondary)]">输入原密码，并设置至少 8 位的新密码</p>
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <input
                  type="password"
                  autoComplete="current-password"
                  value={oldPassword}
                  onChange={(event) => setOldPassword(event.target.value)}
                  placeholder="原密码"
                  required
                  maxLength={72}
                  className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2.5 text-sm text-[var(--text)] outline-none transition-colors focus:border-[var(--accent)]"
                />
                <input
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  placeholder="新密码（至少 8 位）"
                  required
                  minLength={8}
                  maxLength={72}
                  className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2.5 text-sm text-[var(--text)] outline-none transition-colors focus:border-[var(--accent)]"
                />
                <input
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  placeholder="再次输入新密码"
                  required
                  minLength={8}
                  maxLength={72}
                  className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2.5 text-sm text-[var(--text)] outline-none transition-colors focus:border-[var(--accent)]"
                />
              </div>
              <div className="mt-3 flex items-center justify-between gap-3">
                <p className={`text-xs ${passwordMessage?.type === 'success' ? 'text-emerald-400' : 'text-red-400'}`}>
                  {passwordMessage?.text || ''}
                </p>
                <button
                  type="submit"
                  disabled={passwordSaving || !oldPassword || newPassword.length < 8 || !confirmPassword}
                  className="rounded-full bg-[var(--accent)] px-4 py-2 text-xs font-medium text-[var(--accent-foreground)] transition-opacity disabled:opacity-50"
                >
                  {passwordSaving ? '修改中…' : '确认修改'}
                </button>
              </div>
            </form>
          </SectionCard>

          <SectionCard eyebrow="Models" title="模型选择" meta="通用免费模型对所有用户开放；你添加的模型只在当前账号和工作区可见。">
            {modelSettings ? (
              <div className="space-y-4">
                <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] pb-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-sm font-medium text-[var(--text)]"><BrainCircuit size={16} className="text-[var(--accent)]" />当前使用</div>
                    <div className="mt-1 truncate font-mono text-sm text-[var(--text)]">{modelSettings.active_selection.model}</div>
                  </div>
                  <span className="shrink-0 rounded-full bg-[var(--accent-dim)] px-2.5 py-1 text-xs text-[var(--accent)]">{modelSettings.active_selection.source === 'free' ? '通用免费' : '自定义'}</span>
                </div>

                <div>
                  <div className="mb-3 flex items-end justify-between gap-3">
                    <div><h3 className="text-sm font-semibold text-[var(--text)]">通用免费模型</h3><p className="mt-1 text-xs text-[var(--text-secondary)]">由系统统一配置，无需填写 API Key。</p></div>
                    {!modelSettings.free.has_api_key ? <span className="text-xs text-amber-400">服务端尚未配置 Key</span> : null}
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {modelSettings.free.models.map((model) => {
                      const active = modelSettings.active_selection.source === 'free' && modelSettings.active_selection.model === model
                      return (
                    <button
                      key={model}
                      type="button"
                      disabled={modelSettingsSaving || !modelSettings.free.has_api_key}
                      onClick={() => void activateModel('free', model)}
                      className={clsx(
                        'flex min-h-20 items-center justify-between gap-3 rounded-xl border p-4 text-left transition-colors disabled:opacity-50',
                        active ? 'border-[var(--accent)] bg-[var(--accent-dim)]' : 'border-[var(--border)] bg-[var(--bg-secondary)] hover:border-[var(--accent-border)]',
                      )}
                    >
                      <span className="min-w-0 truncate font-mono text-sm text-[var(--text)]">{model}</span>
                      {active ? <Check size={16} className="shrink-0 text-[var(--accent)]" /> : null}
                    </button>
                      )
                    })}
                  </div>
                </div>

                <div>
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div><h3 className="text-sm font-semibold text-[var(--text)]">我的模型</h3><p className="mt-1 text-xs text-[var(--text-secondary)]">API Key 加密保存，页面不会回显明文。</p></div>
                    <button type="button" disabled={modelSettingsSaving || modelSettings.custom_models.length >= 20} onClick={() => { setEditingCustomModel(null); setModelDialogOpen(true) }} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-3 py-2 text-sm font-medium text-[var(--accent-foreground)] disabled:opacity-50"><Plus size={16} />添加模型</button>
                  </div>
                  {modelSettings.custom_models.length ? (
                    <div className="space-y-2">
                      {modelSettings.custom_models.map((model) => {
                        const active = modelSettings.active_selection.source === 'custom' && modelSettings.active_selection.custom_model_id === model.id
                        return (
                          <div key={model.id} className={clsx('flex items-center gap-3 rounded-xl border p-3', active ? 'border-[var(--accent)] bg-[var(--accent-dim)]' : 'border-[var(--border)] bg-[var(--bg-secondary)]')}>
                            <button type="button" disabled={modelSettingsSaving} onClick={() => void activateModel('custom', model.id)} className="min-w-0 flex-1 text-left disabled:opacity-50">
                              <div className="flex items-center gap-2"><span className="truncate text-sm font-medium text-[var(--text)]">{model.name}</span>{active ? <span className="shrink-0 text-xs text-[var(--accent)]">使用中</span> : null}</div>
                              <div className="mt-1 flex min-w-0 gap-2 text-xs text-[var(--text-secondary)]"><span className="truncate font-mono">{model.model}</span><span className="shrink-0">· {model.provider}</span></div>
                            </button>
                            <button type="button" title="编辑模型" aria-label={`编辑模型 ${model.name}`} disabled={modelSettingsSaving} onClick={() => { setEditingCustomModel(model); setModelDialogOpen(true) }} className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)] disabled:opacity-50"><Pencil size={15} /></button>
                            <button type="button" title="删除模型" aria-label={`删除模型 ${model.name}`} disabled={modelSettingsSaving} onClick={() => void deleteCustomModel(model)} className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-[var(--text-secondary)] hover:bg-red-500/10 hover:text-red-400 disabled:opacity-50"><Trash2 size={15} /></button>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <button type="button" onClick={() => { setEditingCustomModel(null); setModelDialogOpen(true) }} className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-[var(--border)] px-4 py-7 text-sm text-[var(--text-secondary)] hover:border-[var(--accent-border)] hover:text-[var(--text)]"><Plus size={16} />添加第一个自定义模型</button>
                  )}
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] pt-3">
                  <p className={clsx('text-xs', modelSettingsMessage?.type === 'error' ? 'text-red-400' : 'text-emerald-400')}>{modelSettingsMessage?.text || '点击模型即可切换，并用于下一条新消息。'}</p>
                  <span className="text-xs text-[var(--text-secondary)]">{modelSettings.scope.tenant_id} / {modelSettings.scope.workspace_id}</span>
                </div>
              </div>
            ) : (
              <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4 text-sm text-[var(--text-secondary)]">{modelSettingsMessage?.text || '正在读取大模型配置…'}</div>
            )}
          </SectionCard>

          <CustomModelDialog
            open={modelDialogOpen}
            model={editingCustomModel}
            saving={modelSettingsSaving}
            onClose={() => { if (!modelSettingsSaving) { setModelDialogOpen(false); setEditingCustomModel(null) } }}
            onSave={(payload, apiKey) => void saveCustomModel(payload, apiKey)}
          />

          <SectionCard eyebrow="Appearance" title="Theme" meta="统一前端颜色：白色 / 黑色 / 暖色">
            <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
              <div className="grid gap-3 md:grid-cols-3">
                {THEME_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => void (setMode(opt.value), persistUiSettings({ theme_mode: opt.value }))}
                    className={clsx(
                      'rounded-2xl border p-4 text-left transition-all',
                      mode === opt.value
                        ? 'border-[var(--accent)] bg-[var(--accent-dim)] shadow-[0_0_0_1px_var(--accent-dim)]'
                        : 'border-[var(--border)] bg-[var(--bg-secondary)] hover:border-[var(--accent-border)] hover:bg-[var(--surface)]'
                    )}
                  >
                    <div className="flex items-center justify-between text-[var(--text)]">
                      {opt.icon}
                      {mode === opt.value ? <Check size={14} /> : null}
                    </div>
                    <div className="mt-4 text-sm font-semibold text-[var(--text)]">{opt.label}</div>
                    <div className="mt-1 text-xs text-[var(--text-secondary)]">{opt.description}</div>
                    <div className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--bg)] p-3">
                      <div className="space-y-2">
                        <div className="h-2 w-12 rounded-full bg-[var(--text)]/20" />
                        <div className="h-2 w-8 rounded-full bg-[var(--text)]/12" />
                        <div className="h-8 rounded-xl bg-gradient-to-br from-[var(--accent-dim)] to-transparent" />
                      </div>
                    </div>
                  </button>
                ))}
              </div>

              <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
                <div className="text-xs uppercase tracking-[0.2em] text-[var(--text-secondary)]">Preview</div>
                <div className="mt-3 overflow-hidden rounded-[24px] border border-[var(--border)] bg-[var(--bg)] p-4">
                  <div className="flex items-center justify-between text-[11px] uppercase tracking-[0.22em] text-[var(--text-secondary)]">
                    <span>UI Preview</span>
                    <span>{accent}</span>
                  </div>
                  <div className="mt-2 text-lg font-semibold text-[var(--text)]">{brandName}</div>
                  <div className="mt-4 grid grid-cols-3 gap-2">
                    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-3 py-3">
                      <div className="text-[11px] text-[var(--text-secondary)]">Surface</div>
                      <div className="mt-2 h-3 rounded-full bg-[var(--text)]/18" />
                      <div className="mt-2 h-2 w-2/3 rounded-full bg-[var(--text)]/10" />
                    </div>
                    <div className={clsx('rounded-2xl border border-[var(--border)] px-3 py-3', `bg-gradient-to-br ${ACCENT_OPTIONS.find((o) => o.value === accent)?.preview}`)}>
                      <div className="text-[11px] text-[var(--text-secondary)]">Accent</div>
                      <div className="mt-2 h-3 rounded-full bg-[var(--accent)]" />
                      <div className="mt-2 h-2 w-2/3 rounded-full bg-[var(--text)]/12" />
                    </div>
                    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-3 py-3">
                      <div className="text-[11px] text-[var(--text-secondary)]">Text</div>
                      <div className="mt-2 h-3 rounded-full bg-[var(--text)]/22" />
                      <div className="mt-2 h-2 w-2/3 rounded-full bg-[var(--text)]/8" />
                    </div>
                  </div>
                </div>
                <div className="mt-3 text-xs text-[var(--text-secondary)]">选择主题后会同步保存到服务器</div>
              </div>
            </div>

            <div className="mt-5">
              <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-[var(--text-secondary)]">
                <Palette size={13} /> Accent
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                {ACCENT_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => void (setAccent(opt.value), persistUiSettings({ theme_accent: opt.value }))}
                    className={clsx(
                      'rounded-2xl border p-4 text-left transition-all',
                      accent === opt.value
                        ? 'border-[var(--accent)] bg-[var(--accent-dim)] shadow-[0_0_0_1px_var(--accent-dim)]'
                        : 'border-[var(--border)] bg-[var(--bg-secondary)] hover:border-[var(--accent-border)] hover:bg-[var(--surface)]'
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <span className={clsx('h-3 w-3 rounded-full', opt.value === 'white' ? 'bg-white' : opt.value === 'black' ? 'bg-black' : 'bg-amber-500')} />
                      {accent === opt.value ? <Check size={14} /> : null}
                    </div>
                    <div className="mt-4 text-sm font-semibold text-[var(--text)]">{opt.label}</div>
                    <div className="mt-1 text-xs text-[var(--text-secondary)]">{opt.description}</div>
                    <div className={clsx('mt-4 h-10 rounded-2xl border border-[var(--border)] bg-gradient-to-br', opt.preview)} />
                  </button>
                ))}
              </div>
            </div>
          </SectionCard>

          <SectionCard eyebrow="Behavior" title="界面行为" meta="控制默认展开状态">
            <div className="space-y-2">
              <SwitchRow
                label="默认展开推理链"
                checked={reasoningDefaultExpanded}
                onToggle={async () => {
                  const next = !reasoningDefaultExpanded
                  setReasoningDefaultExpanded(next)
                  window.localStorage.setItem(TRACE_UI_KEYS.reasoning, next ? '1' : '0')
                  await persistUiSettings({ reasoning_default_expanded: next })
                }}
              />
              <SwitchRow
                label="默认展开 DAG"
                checked={dagDefaultExpanded}
                onToggle={async () => {
                  const next = !dagDefaultExpanded
                  setDagDefaultExpanded(next)
                  window.localStorage.setItem(TRACE_UI_KEYS.dag, next ? '1' : '0')
                  await persistUiSettings({ dag_default_expanded: next })
                }}
              />
              <SwitchRow
                label="默认展开执行图谱"
                checked={executionGraphDefaultExpanded}
                onToggle={async () => {
                  const next = !executionGraphDefaultExpanded
                  setExecutionGraphDefaultExpanded(next)
                  window.localStorage.setItem(TRACE_UI_KEYS.executionGraph, next ? '1' : '0')
                  await persistUiSettings({ execution_graph_default_expanded: next })
                }}
              />
              <SwitchRow
                label="默认展开决策追溯"
                checked={decisionTraceDefaultExpanded}
                onToggle={async () => {
                  const next = !decisionTraceDefaultExpanded
                  setDecisionTraceDefaultExpanded(next)
                  window.localStorage.setItem(TRACE_UI_KEYS.decisionTrace, next ? '1' : '0')
                  await persistUiSettings({ decision_trace_default_expanded: next })
                }}
              />
              <SwitchRow
                label="默认展开后续流程"
                checked={flowCardsDefaultExpanded}
                onToggle={async () => {
                  const next = !flowCardsDefaultExpanded
                  setFlowCardsDefaultExpanded(next)
                  window.localStorage.setItem(TRACE_UI_KEYS.flowCards, next ? '1' : '0')
                  await persistUiSettings({ flow_cards_default_expanded: next })
                }}
              />
            </div>
          </SectionCard>

          <SectionCard eyebrow="Personalization" title="自定义指令" meta={`明确告诉 ${brandName} 应该了解什么，以及如何回答；临时聊天也会遵守这些指令。`}>
            <div className="space-y-3">
              <SwitchRow
                label="启用自定义指令"
                checked={customInstructionsEnabled}
                onToggle={() => setCustomInstructionsEnabled((value) => !value)}
              />
              <label className="block text-sm text-[var(--text)]">
                关于你
                <textarea
                  value={aboutUser}
                  onChange={(event) => setAboutUser(event.target.value)}
                  maxLength={4000}
                  rows={3}
                  placeholder={`例如：我是产品经理，常用中文沟通，正在使用 ${brandName}。`}
                  className="mt-1.5 w-full rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"
                />
              </label>
              <label className="block text-sm text-[var(--text)]">
                回答风格
                <textarea
                  value={responseStyle}
                  onChange={(event) => setResponseStyle(event.target.value)}
                  maxLength={4000}
                  rows={3}
                  placeholder="例如：先给结论，使用中文，必要时给出可执行步骤。"
                  className="mt-1.5 w-full rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"
                />
              </label>
              <button
                type="button"
                disabled={savingCustomInstructions}
                onClick={() => void saveCustomInstructions()}
                className="rounded-xl bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-foreground)] disabled:opacity-60"
              >
                {savingCustomInstructions ? '保存中…' : '保存自定义指令'}
              </button>
            </div>
          </SectionCard>

          <SectionCard eyebrow="System" title="System Info" meta="运行环境与版本信息">
            <div className="divide-y divide-[var(--border)] overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)]">
              {[
                { label: 'API Endpoint', value: ((import.meta as any).env?.VITE_API_URL || window.location.origin) },
                { label: 'Version', value: '0.1.0' },
                { label: 'Kernel', value: 'responses-agent-loop' },
              ].map(({ label, value }) => (
                <div key={label} className="flex items-center justify-between px-4 py-3 text-sm">
                  <span className="text-[var(--text-secondary)]">{label}</span>
                  <span className="font-mono text-[var(--text)]">{value}</span>
                </div>
              ))}
            </div>
          </SectionCard>
        </div>
      </main>
    </div>
  )
}
