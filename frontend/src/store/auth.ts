import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
  token: string | null
  userId: string | null
  email: string | null
  displayName: string | null
  role: string | null
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
      login: (token, userId, email, displayName, role) =>
        set({ token, userId, email, displayName: displayName ?? email, role: role ?? 'user' }),
      logout: () => {
        // Clear per-user localStorage keys to prevent cross-user data leaks
        localStorage.removeItem('opentrace:selected_data_source')
        set({ token: null, userId: null, email: null, displayName: null, role: null })
      },
    }),
    { name: 'opentrace-auth' }
  )
)
