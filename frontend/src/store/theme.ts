import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ThemeMode = 'light' | 'dark' | 'system'
export type AccentMode = 'white' | 'black' | 'warm'

interface ThemeState {
  mode: ThemeMode
  accent: AccentMode
  setMode: (m: ThemeMode) => void
  setAccent: (a: AccentMode) => void
  effective: () => 'light' | 'dark'
}

export const TRACE_VISIBILITY_KEYS = {
  reasoning: 'opentrace:ui.reasoning.defaultExpanded',
  dag: 'opentrace:ui.dag.defaultExpanded',
  executionGraph: 'opentrace:ui.executionGraph.defaultExpanded',
  decisionTrace: 'opentrace:ui.decisionTrace.defaultExpanded',
  flowCards: 'opentrace:ui.flowCards.defaultExpanded',
} as const

export function getTraceVisibility(key: keyof typeof TRACE_VISIBILITY_KEYS) {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage.getItem(TRACE_VISIBILITY_KEYS[key]) === '1'
  } catch {
    return false
  }
}

export function setTraceVisibility(key: keyof typeof TRACE_VISIBILITY_KEYS, value: boolean) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(TRACE_VISIBILITY_KEYS[key], value ? '1' : '0')
  } catch {
    // localStorage not available
  }
}

const SHOW_AVATARS_KEY = 'opentrace:ui.showAvatars'

export function getShowAvatars(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage.getItem(SHOW_AVATARS_KEY) === '1'
  } catch {
    return false
  }
}

export function setShowAvatars(value: boolean) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(SHOW_AVATARS_KEY, value ? '1' : '0')
  } catch {
    // localStorage not available
  }
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      mode: 'light',
      accent: 'white',
      setMode: (mode) => {
        set({ mode })
        applyTheme(mode, get().accent)
      },
      setAccent: (accent) => {
        set({ accent })
        applyTheme(get().mode, accent)
      },
      effective: () => {
        const m = get().mode
        if (m === 'system') {
          return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
        }
        return m
      },
    }),
    {
      name: 'opentrace-theme',
      onRehydrateStorage: () => (state) => {
        if (state) applyTheme(state.mode, state.accent)
      },
    }
  )
)

export function applyTheme(mode: ThemeMode, accent: AccentMode = 'white') {
  const resolvedMode =
    mode === 'system'
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light'
      : mode

  document.documentElement.setAttribute('data-theme', resolvedMode)
  document.documentElement.setAttribute('data-accent', accent)

  const root = document.documentElement
  root.style.removeProperty('--bg')
  root.style.removeProperty('--bg-secondary')
  root.style.removeProperty('--surface')
  root.style.removeProperty('--surface-raised')

  if (resolvedMode === 'dark') {
    root.style.setProperty('--time-card-bg', '#1a1a1a')
    root.style.setProperty('--time-card-panel', '#1a1a1a')
    root.style.setProperty('--time-card-text', '#f5f5f5')
    root.style.setProperty('--time-card-muted', 'rgba(245,245,245,0.68)')
    root.style.setProperty('--time-card-faint', 'rgba(245,245,245,0.42)')
    root.style.setProperty('--time-card-border', 'rgba(255,255,255,0.08)')
    root.style.setProperty('--time-card-shadow', '0 22px 60px rgba(0,0,0,0.38)')
    root.style.setProperty('--time-card-accent', '#ff7b7b')
  } else {
    root.style.setProperty('--time-card-bg', '#f7f8fa')
    root.style.setProperty('--time-card-panel', '#f7f8fa')
    root.style.setProperty('--time-card-text', '#111111')
    root.style.setProperty('--time-card-muted', 'rgba(17,17,17,0.72)')
    root.style.setProperty('--time-card-faint', 'rgba(17,17,17,0.48)')
    root.style.setProperty('--time-card-border', 'rgba(17,17,17,0.08)')
    root.style.setProperty('--time-card-shadow', '0 18px 48px rgba(0,0,0,0.10)')
    root.style.setProperty('--time-card-accent', '#ff6b6b')
  }
}
