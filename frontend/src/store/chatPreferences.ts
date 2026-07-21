import { create } from 'zustand'

export type ExecutionProfile = 'auto' | 'fast' | 'deep'

interface ChatPreferencesState {
  executionProfile: ExecutionProfile
  assistantProfileId: string | null
  projectId: string | null
  dataSourceId: string | null
  prefillText: string | null
  setExecutionProfile: (profile: ExecutionProfile) => void
  setAssistantProfileId: (id: string | null) => void
  setProjectId: (id: string | null) => void
  setDataSourceId: (id: string | null) => void
  requestPrefill: (text: string) => void
  consumePrefill: () => void
}

export const useChatPreferences = create<ChatPreferencesState>((set) => ({
  executionProfile: 'auto',
  assistantProfileId: null,
  projectId: null,
  dataSourceId: null,
  prefillText: null,
  setExecutionProfile: (executionProfile) => set({ executionProfile }),
  setAssistantProfileId: (assistantProfileId) => set({ assistantProfileId }),
  setProjectId: (projectId) => set({ projectId }),
  setDataSourceId: (dataSourceId) => set({ dataSourceId }),
  requestPrefill: (prefillText) => set({ prefillText }),
  consumePrefill: () => set({ prefillText: null }),
}))
