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
let useAuthStore: typeof import('../../store/auth').useAuthStore

describe('认证会话失效处理', () => {
  beforeAll(async () => {
    vi.stubGlobal('localStorage', storage)
    const client = await import('../client')
    const auth = await import('../../store/auth')
    apiGetCurrentUser = client.apiGetCurrentUser
    apiLogin = client.apiLogin
    useAuthStore = auth.useAuthStore
  })

  beforeEach(() => {
    storage.clear()
    useAuthStore.setState({
      token: null,
      userId: null,
      email: null,
      displayName: null,
      role: null,
    })
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
})
