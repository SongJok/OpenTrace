import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { useChatStore } from './chat'
import { useChatCommands } from './chatCommands'
import { useChatPreferences } from './chatPreferences'

function resetUserScopedState() {
  useChatStore.getState().resetUserState()
  useChatPreferences.getState().resetUserState()
  useChatCommands.getState().resetUserState()
  if (typeof localStorage !== 'undefined') {
    localStorage.removeItem('opentrace:selected_data_source')
  }
}

export interface AuthSessionSnapshot {
  token: string | null
  userId: string | null
  generation: number
}

interface AuthState {
  token: string | null
  userId: string | null
  email: string | null
  displayName: string | null
  role: string | null
  sessionGeneration: number
  login: (token: string, userId: string, email: string, displayName?: string | null, role?: string | null) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      userId: null,
      email: null,
      displayName: null,
      role: null,
      sessionGeneration: 0,
      login: (token, userId, email, displayName, role) => {
        resetUserScopedState()
        set((state) => ({
          token,
          userId,
          email,
          displayName: displayName ?? email,
          role: role ?? 'user',
          sessionGeneration: state.sessionGeneration + 1,
        }))
      },
      logout: () => {
        resetUserScopedState()
        set((state) => ({
          token: null,
          userId: null,
          email: null,
          displayName: null,
          role: null,
          sessionGeneration: state.sessionGeneration + 1,
        }))
      },
    }),
    { name: 'opentrace-auth' }
  )
)

export function getAuthSessionSnapshot(): AuthSessionSnapshot {
  const { token, userId, sessionGeneration } = useAuthStore.getState()
  return { token, userId, generation: sessionGeneration }
}

export function isAuthSessionCurrent(snapshot: AuthSessionSnapshot): boolean {
  const current = useAuthStore.getState()
  return current.token === snapshot.token
    && current.userId === snapshot.userId
    && current.sessionGeneration === snapshot.generation
}
