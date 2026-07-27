import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiGetEnterpriseWorkbench } from '../../api/client'

describe('enterprise AI workbench contracts', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('uses one actionable entry for enterprise work', async () => {
    const source = (await import('../WorkPage')).default.toString()
    expect(source).toContain('企业 AI 工作台')
    expect(source).toContain('apiGetEnterpriseWorkbench')
    expect(source).toContain('OverviewPanel')
    expect(source).toContain('apiListProjects')
    expect(source).toContain('apiListGoals')
  })

  it('reads the durable v2 workbench projection', async () => {
    const payload = {
      generated_at: '2026-07-27T00:00:00Z',
      scope: { tenant_id: 'tenant-a', workspace_id: 'workspace-a', user_id: 'user-a' },
      readiness: {
        score: 88,
        status: 'ready',
        dimensions: { context: 100, knowledge: 90, data: 100, automation: 75, governance: 90 },
        blockers: [],
      },
      summary: {
        projects: 2,
        active_goals: 1,
        running_responses: 1,
        pending_approvals: 0,
        unread_notifications: 0,
        scheduled_tasks: 1,
        active_alerts: 1,
        unacknowledged_alerts: 0,
        accessible_data_sources: 2,
        knowledge_spaces: 3,
        published_knowledge: 20,
      },
      knowledge_health: { score: 100, status: 'healthy', scope: { space_count: 1 }, metrics: {} },
      attention_items: [],
      recent_activity: [],
    }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiGetEnterpriseWorkbench('token', 8)

    expect(result.readiness.score).toBe(88)
    expect(result.scope).toMatchObject({ tenant_id: 'tenant-a', workspace_id: 'workspace-a' })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v2/workbench/overview?recent_limit=8',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer token' }) }),
    )
  })

  it('makes the enterprise workbench the authenticated product home', async () => {
    const appSource = (await import('../../App')).default.toString()
    const sidebarSource = (await import('../../components/Sidebar')).default.toString()
    expect(appSource).toContain('to: "/work"')
    expect(sidebarSource).toContain('企业 AI 工作台')
  })
})
