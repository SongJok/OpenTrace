import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiGetEnterpriseWorkbench, type EnterpriseWorkbenchScenario } from '../../api/client'
import { scenarioLaunchIntent } from '../WorkPage'

describe('enterprise AI workbench contracts', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('uses one actionable entry for enterprise work', async () => {
    const workPage = await import('../WorkPage')
    const source = workPage.default.toString()
    const overviewSource = workPage.OverviewPanel.toString()
    expect(source).toContain('企业 AI 工作台')
    expect(source).toContain('apiGetEnterpriseWorkbench')
    expect(source).toContain('OverviewPanel')
    expect(source).toContain('WorkbenchActionCenter')
    expect(source).toContain('apiListProjects')
    expect(source).toContain('apiListGoals')
    expect(overviewSource).toContain('WorkbenchTodayPulse')
    expect(overviewSource).toContain('企业日常工作场景')
    expect(overviewSource).toContain('scenarioLaunchIntent')
  })

  it('prefills ready chat scenarios but routes setup gaps without unsafe execution', () => {
    const base = {
      id: 'decision_brief',
      category: '管理协作',
      title: '决策简报',
      description: '说明',
      status: 'ready',
      recommended: true,
      launch_mode: 'chat',
      action_route: '/chat',
      action_label: '开始工作',
      starter_prompt: '请生成可追溯决策简报：',
      capabilities: ['document_retrieval', 'data_query'],
      tools: [],
      memory_scope: 'project',
      risk: 'read',
      approval_policy: 'none',
      approval_required: false,
      evidence_requirements: ['知识引用'],
      deliverables: ['决策摘要'],
      blockers: [],
    } satisfies EnterpriseWorkbenchScenario

    expect(scenarioLaunchIntent(base)).toEqual({
      route: '/chat',
      prefillText: '请生成可追溯决策简报：',
    })
    expect(scenarioLaunchIntent({
      ...base,
      status: 'setup_required',
      action_route: '/databases',
      blockers: [{ code: 'data', title: '连接数据', description: '说明', route: '/databases' }],
    })).toEqual({ route: '/databases', prefillText: null })
    expect(scenarioLaunchIntent({
      ...base,
      status: 'active',
      action_route: '/reports',
      action_label: '查看运行',
    })).toEqual({ route: '/reports', prefillText: null })
  })

  it('offers all six assistant personality styles when creating a role', async () => {
    const { ASSISTANT_PERSONALITY_OPTIONS } = await import('../WorkPage')
    expect(ASSISTANT_PERSONALITY_OPTIONS).toEqual([
      { value: 'none', label: '中性' },
      { value: 'friendly', label: '友好' },
      { value: 'pragmatic', label: '务实' },
      { value: 'cute', label: '可爱' },
      { value: 'romantic', label: '浪漫' },
      { value: 'funny', label: '搞笑' },
    ])
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
      '/api/v2/workbench/overview?recent_limit=8&timezone=Asia%2FShanghai',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer token' }) }),
    )
  })

  it('supports a bounded action-center projection for enterprise queues', async () => {
    const payload = {
      generated_at: '2026-07-29T00:00:00Z',
      scope: { tenant_id: 'tenant-a', workspace_id: 'workspace-a', user_id: 'user-a' },
      readiness: { score: 90, status: 'ready', dimensions: { context: 100, knowledge: 90, data: 100, automation: 80, governance: 90 }, blockers: [] },
      summary: { projects: 1, active_goals: 1, running_responses: 0, pending_approvals: 1, unread_notifications: 2, scheduled_tasks: 1, active_alerts: 1, unacknowledged_alerts: 1, accessible_data_sources: 1, knowledge_spaces: 1, published_knowledge: 3 },
      knowledge_health: { score: 100, status: 'healthy', scope: { space_count: 1 }, metrics: {} },
      attention_items: [{ id: 'approval-1', type: 'approval', severity: 'warning', title: '待审批', description: '需要处理', route: '/chat', created_at: '2026-07-29T00:00:00Z' }],
      recent_activity: [],
    }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await apiGetEnterpriseWorkbench('token', 12, 50)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v2/workbench/overview?recent_limit=12&timezone=Asia%2FShanghai&attention_limit=50',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer token' }) }),
    )
  })

  it('provides a searchable action center with notification acknowledgement', async () => {
    const source = (await import('../../components/WorkbenchActionCenter')).WorkbenchActionCenter.toString()
    expect(source).toContain('统一行动中心')
    expect(source).toContain('搜索标题或内容')
    expect(source).toContain('apiReadNotification')
    expect(source).toContain('apiReadAllNotifications')
    expect(source).toContain('查看并已读')
  })

  it('makes the enterprise workbench the authenticated product home', async () => {
    const appSource = (await import('../../App')).default.toString()
    const sidebarSource = (await import('../../components/Sidebar')).default.toString()
    expect(appSource).toContain('to: "/work"')
    expect(sidebarSource).toContain('企业 AI 工作台')
  })
})
