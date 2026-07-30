import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../../store/auth'
import { useChatCommands } from '../../store/chatCommands'
import { useChatPreferences } from '../../store/chatPreferences'
import { useChatStore } from '../../store/chat'
import ChatInput from '../ChatInput'

type StreamCallbacks = {
  onResponseCreated?: (payload: unknown) => void
  onDelta?: (text: string) => void
  onApprovalRequired?: (approvals: unknown[]) => void
  onFinalAnswer?: (answer: { content: string }) => void
}

const streamControl = vi.hoisted(() => ({
  callbacks: null as StreamCallbacks | null,
  resolve: null as (() => void) | null,
}))

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    apiChatStream: vi.fn((_token: string, _conversationId: string, _query: string, callbacks: StreamCallbacks) => {
      streamControl.callbacks = callbacks
      return new Promise<void>((resolve) => { streamControl.resolve = resolve })
    }),
  }
})

describe('ChatInput 认证会话隔离', () => {
  beforeEach(() => {
    localStorage.removeItem('opentrace-auth')
    localStorage.removeItem('opentrace:selected_data_source')
    streamControl.callbacks = null
    streamControl.resolve = null
    useAuthStore.setState({
      token: null,
      userId: null,
      email: null,
      displayName: null,
      role: null,
      sessionGeneration: 0,
    })
    useChatStore.getState().resetUserState()
    useChatPreferences.getState().resetUserState()
    useChatCommands.getState().resetUserState()
  })

  it('账号切换后忽略旧 SSE 的增量、审批和最终答案', async () => {
    useAuthStore.getState().login('old-token', 'user-old', 'old@example.com')
    useChatStore.setState({
      conversations: [{ id: 'old-conversation', title: '旧会话', turn_count: 0, created_at: '', last_active: '' }],
      activeId: 'old-conversation',
      messages: { 'old-conversation': [] },
    })

    render(<ChatInput />)
    fireEvent.change(screen.getByLabelText('消息'), { target: { value: '旧账号请求' } })
    fireEvent.click(screen.getByRole('button', { name: '确定发送' }))
    await waitFor(() => expect(streamControl.callbacks).not.toBeNull())

    useAuthStore.getState().login('new-token', 'user-new', 'new@example.com')
    streamControl.callbacks?.onResponseCreated?.({ response_id: 'old-response' })
    streamControl.callbacks?.onDelta?.('旧账号增量')
    streamControl.callbacks?.onApprovalRequired?.([{ id: 'old-approval' }])
    streamControl.callbacks?.onFinalAnswer?.({ content: '旧账号最终答案' })
    streamControl.resolve?.()

    await waitFor(() => expect(screen.getByLabelText('消息')).toHaveValue(''))
    expect(useChatStore.getState().streaming).toBe(false)
    expect(useChatStore.getState().activeId).toBeNull()
    expect(useChatStore.getState().activeResponseId).toBeNull()
    expect(useChatStore.getState().messages).toEqual({})
  })
})
