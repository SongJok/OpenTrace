import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../../store/auth'
import { useChatPreferences } from '../../store/chatPreferences'
import { useChatStore } from '../../store/chat'
import ChatPage from '../ChatPage'

const api = vi.hoisted(() => ({
  assistantProfiles: vi.fn(),
  modelSettings: vi.fn(),
  selectModel: vi.fn(),
}))

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    apiListAssistantProfiles: api.assistantProfiles,
  }
})

vi.mock('../../api/modelSettings', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/modelSettings')>()
  return {
    ...actual,
    apiGetModelSettings: api.modelSettings,
    apiSelectModelSettings: api.selectModel,
  }
})

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

  it('旧账号资源请求晚到时不会恢复旧助手角色或聊天资源选择', async () => {
    const oldProfiles = deferred<any[]>()
    api.assistantProfiles.mockImplementation((token: string) => token === 'old-token' ? oldProfiles.promise : Promise.resolve([]))
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
    await waitFor(() => expect(api.assistantProfiles).toHaveBeenCalledWith('new-token'))
    expect(useChatPreferences.getState().assistantProfileId).toBeNull()
    expect(useChatPreferences.getState().projectId).toBeNull()
    expect(screen.queryByText('旧账号角色')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Project')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('企业数据源')).not.toBeInTheDocument()
  })

  it('模型选择与推理模式使用独立入口并分别保存状态', async () => {
    const initialSettings = {
      active_selection: { source: 'free' as const, model: 'free-model', custom_model_id: null },
      scope: { tenant_id: 'tenant', workspace_id: 'workspace' },
      free: { provider: 'free', base_url: '', models: ['free-model'], api_mode: 'chat_completions' as const, has_api_key: true },
      custom_models: [
        { id: 'custom-1', name: '开发模型', provider: 'Custom', base_url: 'https://example.com/v1', model: 'custom-model', api_mode: 'responses' as const, has_api_key: true, api_key_masked: 'sk-a••••z', created_at: null, updated_at: null },
        { id: 'custom-2', name: '不可用模型', provider: 'Custom', base_url: 'https://example.com/v1', model: 'missing-key-model', api_mode: 'responses' as const, has_api_key: false, api_key_masked: '', created_at: null, updated_at: null },
      ],
    }
    api.assistantProfiles.mockResolvedValue([])
    api.modelSettings.mockResolvedValue(initialSettings)
    api.selectModel.mockResolvedValue({
      ...initialSettings,
      active_selection: { source: 'custom', model: 'custom-model', custom_model_id: 'custom-1' },
    })
    useAuthStore.getState().login('token', 'user', 'user@example.com')
    useChatStore.setState({
      conversations: [{ id: 'conversation', title: '会话', turn_count: 1, created_at: '', last_active: '' }],
      activeId: 'conversation',
      messages: {
        conversation: [{ id: 'message', role: 'user', status: 'done', streamText: '', finalText: '你好' }],
      },
    })

    render(<MemoryRouter><ChatPage /></MemoryRouter>)

    const selector = await screen.findByRole('button', { name: '选择模型' })
    const profileSelector = screen.getByRole('button', { name: '选择推理模式' })

    fireEvent.click(selector)
    const menu = screen.getByRole('menu', { name: '可用模型' })
    expect(screen.queryByRole('menu', { name: '推理模式' })).not.toBeInTheDocument()
    expect(within(menu).getByText('free-model')).toBeInTheDocument()
    expect(within(menu).getByText('开发模型')).toBeInTheDocument()
    expect(within(menu).queryByText('不可用模型')).not.toBeInTheDocument()

    fireEvent.click(profileSelector)
    const profileMenu = screen.getByRole('menu', { name: '推理模式' })
    expect(screen.queryByRole('menu', { name: '可用模型' })).not.toBeInTheDocument()
    fireEvent.click(within(profileMenu).getByRole('menuitemradio', { name: '快速' }))
    expect(useChatPreferences.getState().executionProfile).toBe('fast')
    expect(selector).toHaveTextContent('free-model')
    expect(api.selectModel).not.toHaveBeenCalled()

    fireEvent.click(selector)
    const reopenedMenu = screen.getByRole('menu', { name: '可用模型' })
    fireEvent.click(within(reopenedMenu).getByRole('menuitemradio', { name: /开发模型/ }))

    await waitFor(() => expect(api.selectModel).toHaveBeenCalledWith('token', 'custom', 'custom-1'))
    await waitFor(() => expect(selector).toHaveTextContent('custom-model'))
  })
})
