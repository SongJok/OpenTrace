import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  apiImportProductionAssetGraph,
  apiListConfigValidationRuns,
  apiListEnterpriseConnectors,
  apiListPendingProductionApprovals,
  apiListProductionAssetSyncRuns,
  apiListProductionAssets,
  apiSyncProductionAssetGraph,
} from '../../api/productionIntelligence'

describe('Production intelligence workbench contract', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('keeps assets, connectors, policy and config validation in one admin workbench', async () => {
    const source = (await import('../ProductionIntelligencePage')).default.toString()

    expect(source).toContain('生产智能控制台')
    expect(source).toContain('生产资产')
    expect(source).toContain('企业连接器')
    expect(source).toContain('配置智能')
    expect(source).toContain('默认拒绝')
    expect(source).toContain('dry-run')
    expect(source).toContain('新连接器默认停用')
    expect(source).toContain('原子批量导入资产图')
    expect(source).toContain('持久化资产源同步')
    expect(source).toContain('稳定的同步幂等键')
    expect(source).toContain('高风险生产变更复核')
    expect(source).toContain('两个不同账号批准')
  })

  it('uses only scoped v2 production control-plane endpoints', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify({ items: [] }), { status: 200 }),
    ))
    vi.stubGlobal('fetch', fetchMock)

    await apiListProductionAssets('token')
    await apiListEnterpriseConnectors('token')
    await apiListPendingProductionApprovals('token')
    await apiListConfigValidationRuns('token', 'asset-1')
    await apiImportProductionAssetGraph('token', { assets: [], relations: [] })
    await apiListProductionAssetSyncRuns('token')
    await apiSyncProductionAssetGraph('token', { source_key: 'cmdb:primary' }, 'sync-1')

    expect(fetchMock.mock.calls.map((call) => String(call[0]))).toEqual([
      '/api/v2/production/assets?limit=500',
      '/api/v2/production/connectors',
      '/api/v2/response-approvals/pending',
      '/api/v2/production/config-assets/asset-1/validation-runs',
      '/api/v2/production/asset-graph/import',
      '/api/v2/production/asset-sync-runs',
      '/api/v2/production/asset-graph/sync',
    ])
    expect(fetchMock.mock.calls[4]?.[1]).toMatchObject({ method: 'POST' })
    expect(fetchMock.mock.calls[6]?.[1]).toMatchObject({
      method: 'POST',
      headers: expect.objectContaining({ 'Idempotency-Key': 'sync-1' }),
    })
  })

  it('is lazy loaded and visible only through the administrator navigation', async () => {
    const [app, sidebar] = await Promise.all([
      import('../../App').then((module) => module.default.toString()),
      import('../../components/Sidebar').then((module) => module.default.toString()),
    ])

    expect(app).toContain('/production-intelligence')
    expect(app).toContain('ProductionIntelligenceRoute')
    expect(app).toContain('AdminProtected')
    expect(sidebar).toContain('/production-intelligence')
    expect(sidebar).toContain('生产智能控制台')
  })

  it('keeps destructive production actions behind a second confirmation', async () => {
    const source = (await import('../../components/ChatMessage')).default.toString()

    expect(source).toContain('approval?.side_effect')
    expect(source).toContain('destructive')
    expect(source).toContain('生产变更或破坏性操作')
    expect(source).toContain('不会自动重试')
  })
})
