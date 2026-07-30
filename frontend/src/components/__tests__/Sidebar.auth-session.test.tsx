import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../../store/auth'
import { useChatStore } from '../../store/chat'
import Sidebar from '../Sidebar'

const api = vi.hoisted(() => ({
  listConversations: vi.fn(),
  listNotifications: vi.fn(),
  getMessages: vi.fn(),
  resumeResponse: vi.fn(),
}))

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    apiListConversations: api.listConversations,
    apiListNotifications: api.listNotifications,
    apiGetMessages: api.getMessages,
    apiResumeResponseWithRetry: api.resumeResponse,
  }
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}

describe('Sidebar 认证会话隔离', () => {
  beforeEach(() => {
    localStorage.removeItem('opentrace-auth')
    localStorage.removeItem('opentrace:selected_data_source')
    api.listConversations.mockReset()
    api.listNotifications.mockReset()
    api.getMessages.mockReset()
    api.resumeResponse.mockReset()
    api.getMessages.mockResolvedValue([])
    api.resumeResponse.mockResolvedValue(undefined)
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

  it('旧账号的会话列表晚到时不会写入新账号 store', async () => {
    const oldConversations = deferred<any[]>()
    api.listConversations.mockImplementation((token: string) => (
      token === 'old-token' ? oldConversations.promise : Promise.resolve([])
    ))
    api.listNotifications.mockResolvedValue({ items: [], unread_count: 0 })
    useAuthStore.getState().login('old-token', 'user-old', 'old@example.com')

    render(<MemoryRouter><Sidebar /></MemoryRouter>)
    await waitFor(() => expect(api.listConversations).toHaveBeenCalledWith(
      'old-token',
      expect.objectContaining({ archived: false }),
    ))

    useAuthStore.getState().login('new-token', 'user-new', 'new@example.com')
    oldConversations.resolve([{ id: 'old-conversation', title: '旧账号会话', turn_count: 1, created_at: '', last_active: '' }])

    await waitFor(() => expect(api.listConversations).toHaveBeenCalledWith(
      'new-token',
      expect.objectContaining({ archived: false }),
    ))
    expect(useChatStore.getState().conversations).toEqual([])
    expect(useChatStore.getState().activeId).toBeNull()
  })

  it('快速从会话 A 切到 B 时忽略 A 的迟到消息和恢复流', async () => {
    const messagesA = deferred<any[]>()
    let callbacksA: Record<string, (...args: any[]) => void> | null = null
    api.listConversations.mockResolvedValue([
      { id: 'conversation-a', title: '会话 A', turn_count: 1, created_at: '', last_active: '' },
      { id: 'conversation-b', title: '会话 B', turn_count: 1, created_at: '', last_active: '' },
    ])
    api.listNotifications.mockResolvedValue({ items: [], unread_count: 0 })
    api.getMessages.mockImplementation((_token: string, conversationId: string) => (
      conversationId === 'conversation-a'
        ? messagesA.promise
        : Promise.resolve([{ id: 'message-b', role: 'assistant', status: 'completed', content: 'B 的内容' }])
    ))
    api.resumeResponse.mockImplementation((_token: string, responseId: string, _cursor: number, callbacks: any) => {
      if (responseId === 'response-a') callbacksA = callbacks
      return Promise.resolve()
    })
    useAuthStore.getState().login('token', 'user', 'dev@example.com')

    render(<MemoryRouter><Sidebar /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('会话 A')).toBeInTheDocument())
    fireEvent.click(screen.getByText('会话 B'))
    await waitFor(() => expect(useChatStore.getState().activeId).toBe('conversation-b'))

    messagesA.resolve([{
      id: 'message-a',
      role: 'assistant',
      status: 'in_progress',
      response_id: 'response-a',
      content: '',
    }])
    await Promise.resolve()
    callbacksA?.onDelta?.('A 的迟到增量')
    callbacksA?.onFinalAnswer?.({ content: 'A 的迟到答案' })

    expect(useChatStore.getState().activeId).toBe('conversation-b')
    expect(useChatStore.getState().activeResponseId).toBeNull()
    expect(useChatStore.getState().streaming).toBe(false)
    expect(useChatStore.getState().messages['conversation-b']?.[0]?.finalText).toBe('B 的内容')
    expect(useChatStore.getState().messages['conversation-a']).toBeUndefined()
    expect(api.resumeResponse).not.toHaveBeenCalled()
  })
})
