import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

function memoryStorage(): Storage {
  const values = new Map<string, string>()
  return {
    get length() {
      return values.size
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => Array.from(values.keys())[index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  }
}

const storage = memoryStorage()
let apiGetCurrentUser: typeof import('../client').apiGetCurrentUser
let apiLogin: typeof import('../client').apiLogin
let getAuthSessionSnapshot: typeof import('../../store/auth').getAuthSessionSnapshot
let isAuthSessionCurrent: typeof import('../../store/auth').isAuthSessionCurrent
let useAuthStore: typeof import('../../store/auth').useAuthStore
let useChatStore: typeof import('../../store/chat').useChatStore
let useChatPreferences: typeof import('../../store/chatPreferences').useChatPreferences

describe('认证会话失效处理', () => {
  beforeAll(async () => {
    vi.stubGlobal('localStorage', storage)
    const client = await import('../client')
    const auth = await import('../../store/auth')
    const chat = await import('../../store/chat')
    const preferences = await import('../../store/chatPreferences')
    apiGetCurrentUser = client.apiGetCurrentUser
    apiLogin = client.apiLogin
    getAuthSessionSnapshot = auth.getAuthSessionSnapshot
    isAuthSessionCurrent = auth.isAuthSessionCurrent
    useAuthStore = auth.useAuthStore
    useChatStore = chat.useChatStore
    useChatPreferences = preferences.useChatPreferences
  })

  beforeEach(() => {
    storage.clear()
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

  afterEach(() => {
    vi.restoreAllMocks()
  })

  afterAll(() => {
    vi.unstubAllGlobals()
  })

  it('受保护请求返回 401 时清除本地过期登录状态', async () => {
    useAuthStore.getState().login('stale-token', 'user-1', 'dev@example.com', 'Dev User', 'admin')
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ message: '登录凭证无效或已过期' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(apiGetCurrentUser('stale-token')).rejects.toThrow('Failed to get current user')
    expect(useAuthStore.getState().token).toBeNull()
    expect(useAuthStore.getState().userId).toBeNull()
  })

  it('登录表单自身返回 401 时保留准确错误提示', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ message: '账号或密码错误' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(apiLogin('missing@example.com', 'wrong-password')).rejects.toThrow('账号或密码错误')
    expect(useAuthStore.getState().token).toBeNull()
  })

  it('切换账号时清空上一账号的对话与资源选择', () => {
    useAuthStore.getState().login('old-token', 'user-old', 'old@example.com', 'Old User', 'user')
    useChatStore.setState({
      conversations: [{ id: 'conversation-old', title: '旧会话', turn_count: 1, created_at: '', last_active: '' }],
      activeId: 'conversation-old',
      messages: { 'conversation-old': [] },
    })
    useChatPreferences.setState({
      assistantProfileId: 'profile-old',
      projectId: 'project-old',
    })
    storage.setItem('opentrace:selected_data_source', JSON.stringify({ id: 'source-old' }))

    useAuthStore.getState().login('new-token', 'user-new', 'new@example.com', 'New User', 'admin')

    expect(useChatStore.getState().conversations).toEqual([])
    expect(useChatStore.getState().activeId).toBeNull()
    expect(useChatStore.getState().messages).toEqual({})
    expect(useChatPreferences.getState().assistantProfileId).toBeNull()
    expect(useChatPreferences.getState().projectId).toBeNull()
    expect(storage.getItem('opentrace:selected_data_source')).toBeNull()
  })

  it('切换账号后旧异步请求快照不能再写入新账号状态', () => {
    useAuthStore.getState().login('old-token', 'user-old', 'old@example.com')
    const oldRequest = getAuthSessionSnapshot()

    useAuthStore.getState().login('new-token', 'user-new', 'new@example.com')

    expect(isAuthSessionCurrent(oldRequest)).toBe(false)
    expect(useAuthStore.getState().sessionGeneration).toBeGreaterThan(oldRequest.generation)
  })

  it('旧账号请求晚到的 401 不会登出当前账号', async () => {
    useAuthStore.getState().login('old-token', 'user-old', 'old@example.com')
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async () => {
        useAuthStore.getState().login('new-token', 'user-new', 'new@example.com')
        return new Response(JSON.stringify({ message: '旧凭证已失效' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )

    await expect(apiGetCurrentUser('old-token')).rejects.toThrow('Failed to get current user')
    expect(useAuthStore.getState().token).toBe('new-token')
    expect(useAuthStore.getState().userId).toBe('user-new')
  })

  it('同一 token 被新登录会话复用时旧请求晚到的 401 也不会登出新账号', async () => {
    useAuthStore.getState().login('shared-token', 'user-old', 'old@example.com')
    let resolveRequest!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise<Response>((resolve) => {
      resolveRequest = resolve
    })))

    const request = apiGetCurrentUser('shared-token')
    useAuthStore.getState().login('shared-token', 'user-new', 'new@example.com')
    resolveRequest(new Response(JSON.stringify({ message: '旧会话已过期' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    }))

    await expect(request).rejects.toThrow('Failed to get current user')
    expect(useAuthStore.getState().token).toBe('shared-token')
    expect(useAuthStore.getState().userId).toBe('user-new')
  })
})
