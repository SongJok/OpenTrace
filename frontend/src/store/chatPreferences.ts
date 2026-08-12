import { create } from 'zustand'

export type ExecutionProfile = 'auto' | 'fast' | 'deep'

interface ChatPreferencesState {
  executionProfile: ExecutionProfile
  assistantProfileId: string | null
  prefillText: string | null
  resetUserState: () => void
  setExecutionProfile: (profile: ExecutionProfile) => void
  setAssistantProfileId: (id: string | null) => void
  requestPrefill: (text: string) => void
  consumePrefill: () => void
}

export const useChatPreferences = create<ChatPreferencesState>((set) => ({
  executionProfile: 'auto',
  assistantProfileId: null,
  prefillText: null,
  resetUserState: () => set({
    assistantProfileId: null,
    prefillText: null,
  }),
  setExecutionProfile: (executionProfile) => set({ executionProfile }),
  setAssistantProfileId: (assistantProfileId) => set({ assistantProfileId }),
  requestPrefill: (prefillText) => set({ prefillText }),
  consumePrefill: () => set({ prefillText: null }),
}))
