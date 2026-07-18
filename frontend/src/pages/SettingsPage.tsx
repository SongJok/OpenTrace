import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { ChevronLeft, Check, LogOut, Moon, Monitor, Palette, Sun } from 'lucide-react'
import clsx from 'clsx'
import { useThemeStore, type AccentMode, type ThemeMode } from '../store/theme'
import { useAuthStore } from '../store/auth'
import { apiGetCustomInstructions, apiGetUiSettings, apiPatchUiSettings, apiSetCustomInstructions } from '../api/client'
import { CardShell } from '../components/CardShell'

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
          </SectionCard>

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
                  <div className="mt-2 text-lg font-semibold text-[var(--text)]">OpenTrace</div>
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

          <SectionCard eyebrow="Personalization" title="自定义指令" meta="明确告诉 OpenTrace 应该了解什么，以及如何回答；临时聊天也会遵守这些指令。">
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
                  placeholder="例如：我是产品经理，常用中文沟通，正在做 OpenTrace。"
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
                { label: 'API Endpoint', value: ((import.meta as any).env?.VITE_API_URL || 'http://localhost:14100') },
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
