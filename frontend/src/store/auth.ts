import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
  token: string | null
  userId: string | null
  email: string | null
  displayName: string | null
  login: (token: string, userId: string, email: string, displayName?: string | null) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      userId: null,
      email: null,
      displayName: null,
      login: (token, userId, email, displayName) =>
        set({ token, userId, email, displayName: displayName ?? email }),
      logout: () => set({ token: null, userId: null, email: null, displayName: null }),
    }),
    { name: 'opentrace-auth' }
  )
)
