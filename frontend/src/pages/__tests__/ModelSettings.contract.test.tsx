import { describe, expect, it } from 'vitest'

import * as client from '../../api/modelSettings'

describe('大模型动态配置 contract', () => {
  it('exposes scoped model settings API helpers', () => {
    expect(client.apiGetModelSettings).toBeTypeOf('function')
    expect(client.apiPatchModelSettings).toBeTypeOf('function')
    expect(client.apiSelectModelSettings).toBeTypeOf('function')
  })

  it('loads the settings page with the model configuration section', async () => {
    const page = await import('../SettingsPage')
    expect(page.default).toBeTypeOf('function')
  })
  it('activates exactly the model that the user clicked', () => {
    const settings: client.UserModelSettings = {
      active_profile: 'environment',
      scope: { tenant_id: 'default', workspace_id: 'default' },
      environment: { provider: 'env', base_url: 'https://env.example/v1', model: 'qwen', models: ['qwen'], api_mode: 'auto', has_api_key: true, api_key_masked: '***', api_key_source: 'environment' },
      official: { provider: 'official', base_url: 'https://official.example/v1', model: 'official-a', models: ['official-a'], api_mode: 'responses', has_api_key: true, api_key_masked: '***', api_key_source: 'stored' },
      relay: { provider: 'relay', base_url: 'https://relay.example/v1', model: 'gpt-5.6-sol', models: ['gpt-5.6-sol', 'kimi-k3-kimi'], api_mode: 'chat_completions', has_api_key: true, api_key_masked: '***', api_key_source: 'environment' },
    }

    const selected = client.withSelectedModel(settings, 'relay', 'kimi-k3-kimi')
    expect(selected.active_profile).toBe('relay')
    expect(selected.relay.model).toBe('kimi-k3-kimi')
    expect(settings.active_profile).toBe('environment')
    expect(settings.relay.model).toBe('gpt-5.6-sol')
  })

})
