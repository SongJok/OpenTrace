import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  apiDecideKnowledgeReview,
  apiListKnowledgeSpaces,
  apiSearchEnterpriseKnowledge,
} from '../../api/client'

describe('enterprise knowledge base contracts', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('separates employee knowledge, unified ingestion and governance workflows', async () => {
    const employeeSource = (await import('../EnterpriseKnowledgePage')).default.toString()
    const governanceSource = (await import('../KnowledgeCenterPage')).default.toString()
    const documentsSource = (await import('../DocumentsPage')).default.toString()

    expect(employeeSource).toContain('企业知识库')
    expect(employeeSource).toContain('知识资产')
    expect(employeeSource).toContain('来源与状态')
    expect(employeeSource).toContain('投稿资料')
    expect(employeeSource).not.toContain('apiListKnowledgeReviews')
    expect(employeeSource).not.toContain('apiListEnterpriseKnowledgeConnectors')

    expect(documentsSource).toContain('我的资料')
    expect(documentsSource).toContain('投稿企业知识库')
    expect(documentsSource).toContain('knowledge_space_id')

    expect(governanceSource).toContain('知识库质量中心')
    expect(governanceSource).toContain('审核队列')
    expect(governanceSource).not.toContain('连接器与同步')
    expect(governanceSource).toContain('空间访问控制')
    expect(governanceSource).not.toContain('syncRuns')
    expect(governanceSource).not.toContain('retryRun')
  })

  it('uses the enterprise knowledge API envelope', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: 'space-1', name: '制度' }] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: 'claim-1', text: '需审批' }] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ published: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const spaces = await apiListKnowledgeSpaces('token')
    const evidence = await apiSearchEnterpriseKnowledge('token', '报销制度', 'space-1')
    const decision = await apiDecideKnowledgeReview('token', 'review-1', 'approve', '通过')

    expect(spaces[0].id).toBe('space-1')
    expect(evidence[0].id).toBe('claim-1')
    expect(decision.published).toBe(true)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/knowledge/spaces')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/knowledge/search')
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toMatchObject({
      query: '报销制度',
      space_id: 'space-1',
      top_k: 8,
    })
    expect(fetchMock.mock.calls[2][0]).toBe('/api/v1/knowledge/reviews/review-1/decision')
  })
  it('redacts compilation internals from the governance UI', async () => {
    const { formatKnowledgeJobError } = await import('../KnowledgeCenterPage')

    expect(formatKnowledgeJobError("This Session's transaction has been rolled back; SELECT private")).toContain('历史编排任务失败')
    expect(formatKnowledgeJobError('knowledge_compilation_failed:RuntimeError')).toContain('RuntimeError')
    expect(formatKnowledgeJobError('raw document content')).not.toContain('raw document content')
  })

})
