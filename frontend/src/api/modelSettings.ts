export type ModelSource = 'free' | 'custom'
export type ModelApiMode = 'auto' | 'responses' | 'chat_completions'

export interface FreeModelSettings {
  provider: string
  base_url: string
  models: string[]
  api_mode: ModelApiMode
  has_api_key: boolean
}

export interface CustomModelSettings {
  id: string
  name: string
  provider: string
  base_url: string
  model: string
  api_mode: ModelApiMode
  has_api_key: boolean
  api_key_masked: string
  created_at: string | null
  updated_at: string | null
}

export interface UserModelSettings {
  active_selection: {
    source: ModelSource
    model: string
    custom_model_id: string | null
  }
  scope: { tenant_id: string; workspace_id: string }
  free: FreeModelSettings
  custom_models: CustomModelSettings[]
}

export interface CustomModelInput {
  name: string
  provider: string
  base_url: string
  api_key?: string
  model: string
  api_mode: ModelApiMode
}

const API_ROOT = '/api/v1'
const ENV_API = (import.meta as any)?.env?.VITE_API_URL as string | undefined
const CONFIGURED_API = ENV_API?.trim() || ''
const DIRECT_ROOT = `${CONFIGURED_API}/api/v1`

async function modelSettingsFetch(path: string, token: string, init?: RequestInit) {
  const request = {
    ...init,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...init?.headers },
  }
  try {
    return await fetch(`${API_ROOT}${path}`, request)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    if (!CONFIGURED_API) throw error
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

export async function apiCreateCustomModel(token: string, payload: CustomModelInput & { api_key: string }): Promise<CustomModelSettings> {
  const response = await modelSettingsFetch('/users/model-settings/custom-models', token, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await errorMessage(response, '添加模型失败'))
  return response.json()
}

export async function apiUpdateCustomModel(token: string, id: string, payload: CustomModelInput): Promise<CustomModelSettings> {
  const response = await modelSettingsFetch(`/users/model-settings/custom-models/${encodeURIComponent(id)}`, token, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await errorMessage(response, '更新模型失败'))
  return response.json()
}

export async function apiDeleteCustomModel(token: string, id: string): Promise<void> {
  const response = await modelSettingsFetch(`/users/model-settings/custom-models/${encodeURIComponent(id)}`, token, { method: 'DELETE' })
  if (!response.ok) throw new Error(await errorMessage(response, '删除模型失败'))
}

export function withSelectedModel(
  settings: UserModelSettings,
  source: ModelSource,
  selected: string,
): UserModelSettings {
  if (source === 'free') {
    if (!settings.free.models.includes(selected)) throw new Error('所选模型不在通用免费模型列表中')
    return { ...settings, active_selection: { source, model: selected, custom_model_id: null } }
  }
  const custom = settings.custom_models.find((item) => item.id === selected)
  if (!custom) throw new Error('自定义模型不存在')
  return { ...settings, active_selection: { source, model: custom.model, custom_model_id: custom.id } }
}

export async function apiSelectModelSettings(
  token: string,
  source: ModelSource,
  selected: string,
): Promise<UserModelSettings> {
  const response = await modelSettingsFetch('/users/model-settings/selection', token, {
    method: 'PATCH',
    body: JSON.stringify(source === 'free' ? { source, model: selected } : { source, custom_model_id: selected }),
  })
  if (!response.ok) throw new Error(await errorMessage(response, '切换大模型失败'))
  return response.json()
}
