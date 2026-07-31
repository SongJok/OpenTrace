import { describe, expect, it } from 'vitest'

import * as client from '../../api/modelSettings'

const settings: client.UserModelSettings = {
  active_selection: { source: 'free', model: 'glm-5.2-free', custom_model_id: null },
  scope: { tenant_id: 'default', workspace_id: 'default' },
  free: {
    provider: '通用免费模型',
    base_url: 'https://free.example/v1',
    models: ['glm-5.2-free', 'deepseek-v4-pro-free'],
    api_mode: 'chat_completions',
    has_api_key: true,
  },
  custom_models: [{
    id: 'custom-1',
    name: '开发模型',
    provider: 'Custom',
    base_url: 'https://custom.example/v1',
    model: 'custom-model',
    api_mode: 'responses',
    has_api_key: true,
    api_key_masked: 'sk-a••••z',
    created_at: null,
    updated_at: null,
  }],
}

describe('大模型动态配置 contract', () => {
  it('exposes free selection and custom model CRUD helpers', () => {
    expect(client.apiGetModelSettings).toBeTypeOf('function')
    expect(client.apiCreateCustomModel).toBeTypeOf('function')
    expect(client.apiUpdateCustomModel).toBeTypeOf('function')
    expect(client.apiDeleteCustomModel).toBeTypeOf('function')
    expect(client.apiSelectModelSettings).toBeTypeOf('function')
  })

  it('loads the settings page with the model configuration section', async () => {
    const page = await import('../SettingsPage')
    expect(page.default).toBeTypeOf('function')
  })

  it('activates exactly the free or custom model that the user clicked', () => {
    const freeSelected = client.withSelectedModel(settings, 'free', 'deepseek-v4-pro-free')
    expect(freeSelected.active_selection).toEqual({ source: 'free', model: 'deepseek-v4-pro-free', custom_model_id: null })

    const customSelected = client.withSelectedModel(settings, 'custom', 'custom-1')
    expect(customSelected.active_selection).toEqual({ source: 'custom', model: 'custom-model', custom_model_id: 'custom-1' })
    expect(settings.active_selection.model).toBe('glm-5.2-free')
  })
})
