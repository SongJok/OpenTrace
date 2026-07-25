import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  apiDecideKnowledgeReview,
  apiListKnowledgeSpaces,
  apiListKnowledgeSyncRunItems,
  apiListKnowledgeSyncRuns,
  apiRetryKnowledgeSyncRun,
  apiSearchEnterpriseKnowledge,
} from '../../api/client'

describe('enterprise knowledge base contracts', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('exposes employee search, governed spaces and review workflow', async () => {
    const pageSource = (await import('../EnterpriseKnowledgePage')).default.toString()
    expect(pageSource).toContain('企业知识库')
    expect(pageSource).toContain('知识资产')
    expect(pageSource).toContain('来源与时效')
    expect(pageSource).toContain('发布审核')
    expect(pageSource).toContain('连接器')
    expect(pageSource).toContain('成员权限')
    expect(pageSource).toContain('syncRuns')
    expect(pageSource).toContain('retrySyncRun')
    expect(pageSource).toContain('knowledge_space_id')
  })

  it('uses the enterprise knowledge API envelope', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: 'space-1', name: '制度' }] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: 'claim-1', text: '需审批' }] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ published: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const spaces = await apiListKnowledgeSpaces('token')
    const evidence = await apiSearchEnterpriseKnowledge('token', '报销制度', 'project-1')
    const decision = await apiDecideKnowledgeReview('token', 'review-1', 'approve', '通过')

    expect(spaces[0].id).toBe('space-1')
    expect(evidence[0].id).toBe('claim-1')
    expect(decision.published).toBe(true)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/knowledge/spaces')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/knowledge/search')
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toMatchObject({
      query: '报销制度',
      project_id: 'project-1',
      top_k: 8,
    })
    expect(fetchMock.mock.calls[2][0]).toBe('/api/v1/knowledge/reviews/review-1/decision')
  })
  it('lists durable sync runs, expands items and retries failed entries', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: 'run-1', connector_id: 'connector-1', status: 'failed', stats: { failed: 1 } }] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: 'item-1', external_id: 'policy-1', status: 'failed', attempts: 3 }] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ run_id: 'run-1', requeued: 1, status: 'pending' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const runs = await apiListKnowledgeSyncRuns('token', 'connector-1')
    const items = await apiListKnowledgeSyncRunItems('token', 'run-1')
    const retried = await apiRetryKnowledgeSyncRun('token', 'run-1')

    expect(runs[0].status).toBe('failed')
    expect(items[0].attempts).toBe(3)
    expect(retried).toMatchObject({ requeued: 1, status: 'pending' })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/knowledge/sync-runs?connector_id=connector-1')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/knowledge/sync-runs/run-1/items')
    expect(fetchMock.mock.calls[2][0]).toBe('/api/v1/knowledge/sync-runs/run-1/retry')
    expect(fetchMock.mock.calls[2][1]?.method).toBe('POST')
  })

})
