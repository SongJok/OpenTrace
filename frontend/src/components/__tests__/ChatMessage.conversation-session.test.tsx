import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../../store/auth'
import { useChatStore } from '../../store/chat'
import ChatMessage from '../ChatMessage'

type ResumeCallbacks = {
  onDelta?: (text: string) => void
  onFinalAnswer?: (answer: { content: string }) => void
}

const api = vi.hoisted(() => ({
  resumeCallbacks: null as ResumeCallbacks | null,
  resolveApproval: vi.fn(),
  resumeResponse: vi.fn(),
}))

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    apiResolveResponseApproval: api.resolveApproval,
    apiResumeResponseWithRetry: api.resumeResponse,
  }
})

describe('ChatMessage 会话选择隔离', () => {
  beforeEach(() => {
    localStorage.removeItem('opentrace-auth')
    api.resumeCallbacks = null
    api.resolveApproval.mockReset()
    api.resumeResponse.mockReset()
    api.resolveApproval.mockResolvedValue({ status: 'approved', starting_after: 10 })
    api.resumeResponse.mockImplementation((_token: string, _responseId: string, _cursor: number, callbacks: ResumeCallbacks) => {
      api.resumeCallbacks = callbacks
      return new Promise<void>(() => undefined)
    })
    useAuthStore.setState({
      token: null,
      userId: null,
      email: null,
      displayName: null,
      role: null,
      sessionGeneration: 0,
    })
    useChatStore.getState().resetUserState()
  })

  it('审批恢复期间切换会话后不清空新会话的流状态', async () => {
    useAuthStore.getState().login('token', 'user', 'dev@example.com')
    const approvalMessage = {
      id: 'message-a',
      role: 'assistant' as const,
      status: 'done' as const,
      streamText: '',
      finalText: '需要审批',
      response_id: 'response-a',
      approvals: [{ id: 'approval-a', tool_name: 'create_calendar_event', arguments: {} }],
    }
    useChatStore.setState({
      conversations: [
        { id: 'conversation-a', title: '会话 A', turn_count: 1, created_at: '', last_active: '' },
        { id: 'conversation-b', title: '会话 B', turn_count: 1, created_at: '', last_active: '' },
      ],
      activeId: 'conversation-a',
      messages: { 'conversation-a': [approvalMessage as any], 'conversation-b': [] },
      streaming: false,
      activeResponseId: null,
    })

    render(<ChatMessage message={approvalMessage as any} />)
    fireEvent.click(screen.getByRole('button', { name: '允许' }))
    await waitFor(() => expect(api.resumeCallbacks).not.toBeNull())

    useChatStore.setState({
      activeId: 'conversation-b',
      streaming: true,
      activeResponseId: 'response-b',
    })
    api.resumeCallbacks?.onDelta?.('A 的迟到增量')
    api.resumeCallbacks?.onFinalAnswer?.({ content: 'A 的迟到答案' })

    expect(useChatStore.getState().activeId).toBe('conversation-b')
    expect(useChatStore.getState().activeResponseId).toBe('response-b')
    expect(useChatStore.getState().streaming).toBe(true)
    expect(useChatStore.getState().messages['conversation-a']?.[0]?.finalText).toBe('需要审批')
  })

  it('审批接口失败时保留审批卡并展示错误', async () => {
    useAuthStore.getState().login('token', 'user', 'dev@example.com')
    api.resolveApproval.mockRejectedValueOnce(new Error('Response 已结束，不能再处理旧审批'))
    const approvalMessage = {
      id: 'message-a',
      role: 'assistant' as const,
      status: 'done' as const,
      streamText: '',
      finalText: '需要审批',
      response_id: 'response-a',
      approvals: [{ id: 'approval-a', tool_name: 'create_calendar_event', arguments: {} }],
    }
    useChatStore.setState({
      conversations: [
        { id: 'conversation-a', title: '会话 A', turn_count: 1, created_at: '', last_active: '' },
      ],
      activeId: 'conversation-a',
      messages: { 'conversation-a': [approvalMessage as any] },
      streaming: false,
      activeResponseId: null,
    })

    render(<ChatMessage message={approvalMessage as any} />)
    fireEvent.click(screen.getByRole('button', { name: '允许' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Response 已结束，不能再处理旧审批')
    expect(useChatStore.getState().messages['conversation-a']?.[0]?.approvals).toHaveLength(1)
    expect(useChatStore.getState().activeResponseId).toBeNull()
    expect(screen.getByRole('button', { name: '允许' })).toBeEnabled()
  })
})
