import { create } from 'zustand'

export type ExecutionProfile = 'auto' | 'fast' | 'deep'
export type ChatModel = 'qwen3.7-max' | 'qwen3.6-plus' | 'qwen3-14b' | 'qwen3-8b'

interface ChatPreferencesState {
  executionProfile: ExecutionProfile
  model: ChatModel
  assistantProfileId: string | null
  projectId: string | null
  prefillText: string | null
  setExecutionProfile: (profile: ExecutionProfile) => void
  setModel: (model: ChatModel) => void
  setAssistantProfileId: (id: string | null) => void
  setProjectId: (id: string | null) => void
  requestPrefill: (text: string) => void
  consumePrefill: () => void
}

export const useChatPreferences = create<ChatPreferencesState>((set) => ({
  executionProfile: 'auto',
  model: 'qwen3.7-max',
  assistantProfileId: null,
  projectId: null,
  prefillText: null,
  setExecutionProfile: (executionProfile) => set({ executionProfile }),
  setModel: (model) => set({ model }),
  setAssistantProfileId: (assistantProfileId) => set({ assistantProfileId }),
  setProjectId: (projectId) => set({ projectId }),
  requestPrefill: (prefillText) => set({ prefillText }),
  consumePrefill: () => set({ prefillText: null }),
}))
