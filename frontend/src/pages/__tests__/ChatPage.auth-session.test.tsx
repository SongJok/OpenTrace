import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../../store/auth'
import { useChatPreferences } from '../../store/chatPreferences'
import { useChatStore } from '../../store/chat'
import ChatPage from '../ChatPage'

const api = vi.hoisted(() => ({
  assistantProfiles: vi.fn(),
  projects: vi.fn(),
  databases: vi.fn(),
  modelSettings: vi.fn(),
}))

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    apiListAssistantProfiles: api.assistantProfiles,
    apiListProjects: api.projects,
    apiListDatabases: api.databases,
  }
})

vi.mock('../../api/modelSettings', () => ({
  apiGetModelSettings: api.modelSettings,
}))

vi.mock('../../components/Sidebar', () => ({ default: () => <div /> }))
vi.mock('../../components/ChatInput', () => ({ default: () => <div /> }))
vi.mock('../../components/MessageList', () => ({ default: () => <div /> }))
vi.mock('../../components/WelcomeScreen', () => ({ default: () => <div /> }))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}

describe('ChatPage 认证会话隔离', () => {
  beforeEach(() => {
    localStorage.removeItem('opentrace-auth')
    localStorage.removeItem('opentrace:selected_data_source')
    for (const mock of Object.values(api)) mock.mockReset()
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
  })

  it('旧账号资源请求晚到时不会恢复旧助手角色、Project 或数据源', async () => {
    const oldProfiles = deferred<any[]>()
    const oldProjects = deferred<any[]>()
    const oldDatabases = deferred<any[]>()
    api.assistantProfiles.mockImplementation((token: string) => token === 'old-token' ? oldProfiles.promise : Promise.resolve([]))
    api.projects.mockImplementation((token: string) => token === 'old-token' ? oldProjects.promise : Promise.resolve([]))
    api.databases.mockImplementation((token: string) => token === 'old-token' ? oldDatabases.promise : Promise.resolve([]))
    api.modelSettings.mockResolvedValue({
      active_selection: { source: 'free', model: 'test-model', custom_model_id: null },
      scope: { tenant_id: 'tenant', workspace_id: 'workspace' },
      free: { provider: 'test', base_url: '', models: ['test-model'], api_mode: 'chat_completions', has_api_key: true },
      custom_models: [],
    })
    useAuthStore.getState().login('old-token', 'user-old', 'old@example.com')

    render(<MemoryRouter><ChatPage /></MemoryRouter>)
    await waitFor(() => expect(api.assistantProfiles).toHaveBeenCalledWith('old-token'))

    useAuthStore.getState().login('new-token', 'user-new', 'new@example.com')
    useChatStore.setState({
      conversations: [{ id: 'new-conversation', title: '新账号会话', turn_count: 1, created_at: '', last_active: '' }],
      activeId: 'new-conversation',
      messages: {
        'new-conversation': [{
          id: 'new-message',
          role: 'user',
          status: 'done',
          streamText: '',
          finalText: '新账号消息',
        }],
      },
    })
    oldProfiles.resolve([{
      id: 'old-profile', name: '旧账号角色', personality: 'none', instructions: '',
      default_model_profile: 'auto', built_in: false, is_default: true,
    }])
    oldProjects.resolve([{
      id: 'old-project', name: '旧账号项目', description: '', instructions: '',
      memory_mode: 'default', data_source_ids: ['old-source'],
    }])
    oldDatabases.resolve([{ id: 'old-source', name: '旧账号数据源', type: 'postgresql', status: 'active' }])

    await waitFor(() => expect(api.assistantProfiles).toHaveBeenCalledWith('new-token'))
    expect(useChatPreferences.getState().assistantProfileId).toBeNull()
    expect(useChatPreferences.getState().projectId).toBeNull()
    expect(useChatPreferences.getState().dataSourceId).toBeNull()
    expect(screen.queryByText('旧账号角色')).not.toBeInTheDocument()
    expect(screen.queryByText('旧账号项目')).not.toBeInTheDocument()
    expect(screen.queryByText(/旧账号数据源/)).not.toBeInTheDocument()
  })
})
