import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EnterpriseWorkbenchOverview } from '../../api/client'
import { WorkbenchActionCenter } from '../WorkbenchActionCenter'

vi.mock('../../store/auth', () => ({
  useAuthStore: (selector: (state: { token: string }) => unknown) => selector({ token: 'token' }),
  getAuthSessionSnapshot: () => ({ token: 'token', userId: 'user-a', generation: 1 }),
  isAuthSessionCurrent: () => true,
}))

const overview: EnterpriseWorkbenchOverview = {
  generated_at: '2026-07-29T00:00:00Z',
  scope: { tenant_id: 'tenant-a', workspace_id: 'workspace-a', user_id: 'user-a' },
  readiness: {
    score: 80,
    status: 'attention',
    dimensions: { context: 100, knowledge: 80, data: 100, automation: 60, governance: 60 },
    blockers: [],
  },
  summary: {
    projects: 1,
    active_goals: 1,
    running_responses: 1,
    pending_approvals: 1,
    unread_notifications: 1,
    scheduled_tasks: 1,
    active_alerts: 1,
    unacknowledged_alerts: 1,
    accessible_data_sources: 1,
    knowledge_spaces: 1,
    published_knowledge: 1,
    installed_skills: 1,
    company_skills: 1,
    available_work_scenarios: 1,
    active_work_scenarios: 1,
  },
  knowledge_health: { score: 90, status: 'healthy', scope: { space_count: 1 }, metrics: {} },
  personalization: { applied: false, templates: [], principals: [] },
  operating_pulse: {
    timezone: 'Asia/Shanghai', local_date: '2026-07-29', day_start: '2026-07-28T16:00:00Z', day_end: '2026-07-29T16:00:00Z',
    status: 'attention', headline: '有 1 项优先工作等待处理',
    summary: { urgent_items: 1, calendar_events: 0, due_automations: 0, overdue_automations: 0, stale_goals: 0, focus_minutes: 0, meeting_minutes: 0 },
    focus_items: [], timeline: [],
  },
  scenarios: [],
  attention_items: [
    {
      id: 'approval-1',
      type: 'approval',
      severity: 'warning',
      title: '待审批：写入工单',
      description: 'write 操作正在等待你的确认。',
      route: '/chat',
      created_at: '2026-07-29T01:00:00Z',
      priority: 'p1',
      priority_score: 96,
      priority_reason: '审批已等待 5 小时',
    },
  ],
  recent_activity: [],
}

function renderCenter(onRefresh = vi.fn().mockResolvedValue(undefined)) {
  return render(
    <MemoryRouter>
      <WorkbenchActionCenter overview={overview} onRefresh={onRefresh} />
    </MemoryRouter>,
  )
}

describe('企业工作台行动中心', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('统一展示审批与主动工作通知，并支持分类筛选', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      unread_count: 1,
      items: [{
        id: 'notification-1', task_id: 'task-1', kind: 'scheduled_task', level: 'success',
        title: '日报已生成', body: '日报任务执行完成。', read: false, created_at: '2026-07-29T02:00:00Z',
      }],
    }), { status: 200 })))

    renderCenter()

    expect(await screen.findByText('日报已生成')).toBeInTheDocument()
    expect(screen.getByText('待审批：写入工单')).toBeInTheDocument()
    expect(screen.getByText('P1')).toBeInTheDocument()
    expect(screen.getByText('排序依据：审批已等待 5 小时')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '审批 1' }))
    expect(screen.getByText('待审批：写入工单')).toBeInTheDocument()
    expect(screen.queryByText('日报已生成')).not.toBeInTheDocument()
  })

  it('查看未读通知前先持久化已读状态并刷新总览', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        unread_count: 1,
        items: [{
          id: 'notification-1', task_id: 'task-1', kind: 'scheduled_task', level: 'success',
          title: '日报已生成', body: '日报任务执行完成。', read: false, created_at: '2026-07-29T02:00:00Z',
        }],
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'notification-1', read: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const onRefresh = vi.fn().mockResolvedValue(undefined)

    renderCenter(onRefresh)
    fireEvent.click(await screen.findByRole('button', { name: '查看并已读' }))

    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/v2/notifications/notification-1/read',
      expect.objectContaining({ method: 'POST' }),
    ))
    expect(onRefresh).toHaveBeenCalledTimes(1)
  })
})
