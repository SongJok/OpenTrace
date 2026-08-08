import {
  getAuthSessionSnapshot,
  isAuthSessionCurrent,
  type AuthSessionSnapshot,
  useAuthStore,
} from '../store/auth'

const API_V1_BASE = '/api/v1'
export const RESPONSES_BASE = '/api/v2'
const ENV_API = (import.meta as any)?.env?.VITE_API_URL as string | undefined
const CONFIGURED_API = ENV_API?.trim() || ''

type ApiErr = { code?: number; message?: string; detail?: string }

if (typeof window !== 'undefined') {
  console.info('[OpenTrace] API config:', {
    VITE_API_URL: CONFIGURED_API || '(unset)',
    base: API_V1_BASE,
    backendDirect: CONFIGURED_API ? `${CONFIGURED_API}${API_V1_BASE}` : '(same-origin only)',
    fallbackUsed: Boolean(CONFIGURED_API),
  })
}

export function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
}

export async function readApiError(res: Response, fallback: string): Promise<string> {
  const err = (await res.json().catch(() => ({}))) as ApiErr
  if (res.status === 413) return '上传内容超过服务允许的大小，请压缩或拆分后重试'
  return err.message || err.detail || fallback
}

function captureRequestAuthSession(init?: RequestInit): AuthSessionSnapshot | null {
  const authorization = new Headers(init?.headers).get('Authorization') || ''
  const requestToken = authorization.startsWith('Bearer ') ? authorization.slice(7) : null
  const authSession = getAuthSessionSnapshot()
  return requestToken && authSession.token === requestToken ? authSession : null
}

function handleUnauthorized(res: Response, authSession: AuthSessionSnapshot | null): Response {
  if (res.status === 401 && authSession && isAuthSessionCurrent(authSession)) {
    useAuthStore.getState().logout()
  }
  return res
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

async function fetchWithConfiguredFallback(
  base: string,
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const authSession = captureRequestAuthSession(init)
  try {
    return handleUnauthorized(await fetch(`${base}${path}`, init), authSession)
  } catch (error) {
    if (isAbortError(error) || !CONFIGURED_API) throw error
    return handleUnauthorized(
      await fetch(`${CONFIGURED_API}${base}${path}`, init),
      authSession,
    )
  }
}

export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetchWithConfiguredFallback(API_V1_BASE, path, init)
}

export function apiFetchResponses(path: string, init?: RequestInit): Promise<Response> {
  return fetchWithConfiguredFallback(RESPONSES_BASE, path, init)
}
