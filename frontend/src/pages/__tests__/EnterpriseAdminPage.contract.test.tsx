import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  apiArchiveWorkbenchTemplate,
  apiCreateWorkbenchTemplate,
  apiGetEnterpriseOperations,
  apiListEnterpriseCognitiveEntities,
  apiListDirectoryPrincipals,
  apiListWorkbenchTemplates,
  apiPublishEnterpriseCognitiveDraft,
  apiSaveEnterpriseCognitiveDraft,
  apiSyncEnterpriseDirectory,
  apiUpdateWorkbenchTemplate,
  apiUpsertEnterpriseCognitiveEntity,
} from '../../api/client'

describe('enterprise admin center contracts', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('exposes operations, directory and ACL projection in the admin experience', async () => {
    const page = (await import('../EnterpriseAdminPage')).default.toString()
    const sidebar = (await import('../../components/Sidebar')).default.toString()
    const app = (await import('../../App')).default.toString()
    expect(page).toContain('企业运营中心')
    expect(page).toContain('apiGetEnterpriseOperations')
    expect(page).toContain('apiSyncEnterpriseDirectory')
    expect(page).toContain('apiListWorkbenchTemplates')
    expect(page).toContain('WorkbenchTemplatesPanel')
    expect(page).toContain('同步并投影 ACL')
    expect(page).toContain('成为企业级的工作台、最懂公司的 AI')
    expect(page).toContain('企业认知')
    expect(sidebar).toContain('企业运营中心')
    expect(app).toContain('/enterprise-admin')
  })

  it('creates, versions, updates and archives organization workbench templates', async () => {
    const template = {
      id: 'template-1', name: '财务经营工作台', description: '经营分析优先', audience_type: 'principals',
      principal_ids: ['principal-1'], principals: [], scenario_ids: ['business_metric_review'],
      priority: 300, status: 'active', version: 1, created_by: 'admin-1', updated_by: 'admin-1',
    }
    const payload = {
      name: template.name, description: template.description, audience_type: 'principals' as const,
      principal_ids: template.principal_ids, scenario_ids: template.scenario_ids,
      priority: template.priority, status: 'active' as const,
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [template], scenario_catalog: [{ id: 'business_metric_review', category: '数据决策', title: '经营指标复盘', description: '说明' }] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(template), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...template, version: 2 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...template, status: 'archived', version: 3 }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    expect((await apiListWorkbenchTemplates('token')).items[0].id).toBe('template-1')
    await apiCreateWorkbenchTemplate('token', payload)
    await apiUpdateWorkbenchTemplate('token', 'template-1', { ...payload, version: 1 })
    await apiArchiveWorkbenchTemplate('token', 'template-1', 2)

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/admin/enterprise/workbench/templates')
    expect(fetchMock.mock.calls[1][1]?.method).toBe('POST')
    expect(fetchMock.mock.calls[2][1]?.method).toBe('PUT')
    expect(fetchMock.mock.calls[3][0]).toContain('/template-1?version=2')
    expect(fetchMock.mock.calls[3][1]?.method).toBe('DELETE')
  })

  it('uses the scoped enterprise admin API envelope', async () => {
    const operations = {
      generated_at: '2026-07-27T00:00:00Z',
      scope: { tenant_id: 'tenant-a', workspace_id: 'workspace-a' },
      health: { score: 90, status: 'healthy', dimensions: { reliability: 95, governance: 90, knowledge: 85, adoption: 80 } },
      adoption: { active_users_30d: 10, active_goals: 2, completed_goals: 4, scheduled_tasks: 3, active_alerts: 2 },
      responses: { total_24h: 20, completed_24h: 19, failed_24h: 1, requires_action_24h: 0, success_rate: 95, pending_approvals: 0, model_calls_24h: 25, prompt_tokens_24h: 1000, completion_tokens_24h: 400, avg_latency_ms: 800, p95_latency_ms: 1200 },
      assets: { data_sources: 2, active_data_sources: 2, knowledge_spaces: 3, knowledge_sources: 20, published_knowledge: 18, due_reviews: 1, stale_knowledge: 0, pending_reviews: 1, unresolved_feedback: 0 },
      directory: { principals: 3, memberships: 10, last_sync: null },
      alerts: { unacknowledged: 0, critical: 0 },
      model_usage: [], risks: [],
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(operations), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ id: 'p1', principal_type: 'department', external_id: 'finance', display_name: '财务部' }] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'run-1', provider: 'scim', status: 'completed', stats: {} }), { status: 202 }))
    vi.stubGlobal('fetch', fetchMock)

    const overview = await apiGetEnterpriseOperations('token')
    const principals = await apiListDirectoryPrincipals('token')
    const run = await apiSyncEnterpriseDirectory('token', {
      provider: 'scim', authoritative: false,
      principals: [{ principal_type: 'department', external_id: 'finance', display_name: '财务部' }],
      memberships: [],
    })

    expect(overview.health.score).toBe(90)
    expect(principals[0].external_id).toBe('finance')
    expect(run.status).toBe('completed')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/admin/enterprise/operations/overview')
    expect(fetchMock.mock.calls[1][0]).toContain('/api/v1/admin/enterprise/directory/principals')
    expect(fetchMock.mock.calls[2][0]).toBe('/api/v1/admin/enterprise/directory/sync')
  })

  it('uses draft and publish governance for company cognition', async () => {
    const entity = { id: 'company-1', entity_type: 'company', entity_key: 'org-a', display_name: '示例科技', status: 'active' }
    const version = { id: 'version-1', entity_id: 'company-1', version: 1, status: 'draft', classification: 'internal', summary: '企业简介', mission: '企业使命', vision: '', values: [], responsibilities: [], products_services: [], operating_principles: [], terminology: {}, key_contacts: [], source_refs: ['knowledge:company'] }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ vision: '成为企业级的工作台、最懂公司的 AI', items: [entity] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(entity), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(version), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...version, status: 'published' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    expect((await apiListEnterpriseCognitiveEntities('token'))[0].id).toBe('company-1')
    await apiUpsertEnterpriseCognitiveEntity('token', { entity_type: 'company', display_name: '示例科技' })
    await apiSaveEnterpriseCognitiveDraft('token', 'company-1', {
      classification: 'internal', summary: '企业简介', mission: '企业使命', vision: '', values: [], responsibilities: [], products_services: [], operating_principles: [], terminology: {}, key_contacts: [], source_refs: ['knowledge:company'],
    })
    await apiPublishEnterpriseCognitiveDraft('token', 'company-1')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/admin/enterprise/cognition/entities')
    expect(fetchMock.mock.calls[1][1]?.method).toBe('POST')
    expect(fetchMock.mock.calls[2][1]?.method).toBe('PUT')
    expect(fetchMock.mock.calls[3][0]).toContain('/company-1/publish')
  })
})
