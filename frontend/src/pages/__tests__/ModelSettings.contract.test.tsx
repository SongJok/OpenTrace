import { describe, expect, it } from 'vitest'

import * as client from '../../api/modelSettings'

describe('大模型动态配置 contract', () => {
  it('exposes scoped model settings API helpers', () => {
    expect(client.apiGetModelSettings).toBeTypeOf('function')
    expect(client.apiPatchModelSettings).toBeTypeOf('function')
  })

  it('loads the settings page with the model configuration section', async () => {
    const page = await import('../SettingsPage')
    expect(page.default).toBeTypeOf('function')
  })
})
