import { create } from 'zustand'

export interface RegenerateRequest {
  responseId: string
  input?: string
}

interface ChatCommandsState {
  regenerate: RegenerateRequest | null
  resetUserState: () => void
  requestRegenerate: (request: RegenerateRequest) => void
  consumeRegenerate: () => void
}

export const useChatCommands = create<ChatCommandsState>((set) => ({
  regenerate: null,
  resetUserState: () => set({ regenerate: null }),
  requestRegenerate: (regenerate) => set({ regenerate }),
  consumeRegenerate: () => set({ regenerate: null }),
}))
