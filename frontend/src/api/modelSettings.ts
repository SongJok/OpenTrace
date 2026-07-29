export type ModelProfileSource = 'environment' | 'official' | 'relay'
export type ModelApiMode = 'auto' | 'responses' | 'chat_completions'

export interface ModelEndpointSettings {
  provider: string
  base_url: string
  model: string
  models: string[]
  api_mode: ModelApiMode
  has_api_key: boolean
  api_key_masked: string
  api_key_source: 'stored' | 'environment' | 'missing'
}

export interface UserModelSettings {
  active_profile: ModelProfileSource
  scope: { tenant_id: string; workspace_id: string }
  environment: ModelEndpointSettings
  official: ModelEndpointSettings
  relay: ModelEndpointSettings
}

export interface ModelEndpointUpdate {
  provider: string
  base_url: string
  api_key?: string
  clear_api_key?: boolean
  model: string
  models: string[]
  api_mode: ModelApiMode
}

const API_ROOT = '/api/v1'
const ENV_API = (import.meta as any)?.env?.VITE_API_URL as string | undefined
const DIRECT_ROOT = `${ENV_API?.trim() || 'http://localhost:14100'}/api/v1`

async function modelSettingsFetch(path: string, token: string, init?: RequestInit) {
  const request = {
    ...init,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...init?.headers },
  }
  try {
    return await fetch(`${API_ROOT}${path}`, request)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    return fetch(`${DIRECT_ROOT}${path}`, request)
  }
}

async function errorMessage(response: Response, fallback: string) {
  const body = await response.json().catch(() => ({})) as { message?: string; detail?: string }
  return body.message || body.detail || fallback
}

export async function apiGetModelSettings(token: string): Promise<UserModelSettings> {
  const response = await modelSettingsFetch('/users/model-settings', token)
  if (!response.ok) throw new Error(await errorMessage(response, '读取大模型配置失败'))
  return response.json()
}

export async function apiPatchModelSettings(
  token: string,
  payload: { active_profile: ModelProfileSource; official: ModelEndpointUpdate; relay: ModelEndpointUpdate },
): Promise<UserModelSettings> {
  const response = await modelSettingsFetch('/users/model-settings', token, { method: 'PATCH', body: JSON.stringify(payload) })
  if (!response.ok) throw new Error(await errorMessage(response, '保存大模型配置失败'))
  return response.json()
}
export function withSelectedModel(
  settings: UserModelSettings,
  profile: ModelProfileSource,
  model?: string,
): UserModelSettings {
  if (profile === 'environment') return { ...settings, active_profile: profile }
  const endpoint = settings[profile]
  const selected = model || endpoint.model
  if (!endpoint.models.includes(selected)) throw new Error('所选模型不在候选列表中')
  return { ...settings, active_profile: profile, [profile]: { ...endpoint, model: selected } }
}

export async function apiSelectModelSettings(
  token: string,
  profile: ModelProfileSource,
  model?: string,
): Promise<UserModelSettings> {
  const response = await modelSettingsFetch('/users/model-settings/selection', token, {
    method: 'PATCH',
    body: JSON.stringify({ profile, ...(model ? { model } : {}) }),
  })
  if (!response.ok) throw new Error(await errorMessage(response, '切换大模型失败'))
  return response.json()
}
