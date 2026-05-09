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

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      mode: 'dark',
      accent: 'warm',
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

export function applyTheme(mode: ThemeMode, accent: AccentMode = 'warm') {
  const resolvedMode =
    accent === 'white'
      ? 'light'
      : accent === 'black'
        ? 'dark'
        : mode === 'system'
          ? window.matchMedia('(prefers-color-scheme: dark)').matches
            ? 'dark'
            : 'light'
          : mode

  document.documentElement.setAttribute('data-theme', resolvedMode)
  document.documentElement.setAttribute('data-accent', accent)

  const root = document.documentElement
  if (accent === 'black') {
    root.style.setProperty('--bg', '#0f0f0f')
    root.style.setProperty('--bg-secondary', '#141414')
    root.style.setProperty('--surface', '#1a1a1a')
    root.style.setProperty('--surface-raised', '#232323')
    root.style.setProperty('--time-card-bg', '#151515')
    root.style.setProperty('--time-card-panel', '#0f0f0f')
    root.style.setProperty('--time-card-text', '#f5f5f5')
    root.style.setProperty('--time-card-muted', 'rgba(245,245,245,0.68)')
    root.style.setProperty('--time-card-faint', 'rgba(245,245,245,0.42)')
    root.style.setProperty('--time-card-border', 'rgba(255,255,255,0.08)')
    root.style.setProperty('--time-card-shadow', '0 22px 60px rgba(0,0,0,0.38)')
    root.style.setProperty('--time-card-accent', '#ff7b7b')
  } else if (accent === 'white') {
    root.style.setProperty('--bg', '#ffffff')
    root.style.setProperty('--bg-secondary', '#f7f7f7')
    root.style.setProperty('--surface', '#fafafa')
    root.style.setProperty('--surface-raised', '#efefef')
    root.style.setProperty('--time-card-bg', '#ffffff')
    root.style.setProperty('--time-card-panel', '#f5f5f5')
    root.style.setProperty('--time-card-text', '#111111')
    root.style.setProperty('--time-card-muted', 'rgba(17,17,17,0.72)')
    root.style.setProperty('--time-card-faint', 'rgba(17,17,17,0.48)')
    root.style.setProperty('--time-card-border', 'rgba(17,17,17,0.08)')
    root.style.setProperty('--time-card-shadow', '0 18px 48px rgba(0,0,0,0.10)')
    root.style.setProperty('--time-card-accent', '#ff6b6b')
  } else {
    root.style.removeProperty('--bg')
    root.style.removeProperty('--bg-secondary')
    root.style.removeProperty('--surface')
    root.style.removeProperty('--surface-raised')
    root.style.removeProperty('--time-card-bg')
    root.style.removeProperty('--time-card-panel')
    root.style.removeProperty('--time-card-text')
    root.style.removeProperty('--time-card-muted')
    root.style.removeProperty('--time-card-faint')
    root.style.removeProperty('--time-card-border')
    root.style.removeProperty('--time-card-shadow')
    root.style.removeProperty('--time-card-accent')
  }
}
