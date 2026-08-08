import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import type { WorkbenchPortfolio as WorkbenchPortfolioData } from '../../api/client'
import { useChatPreferences } from '../../store/chatPreferences'
import { WorkbenchPortfolio } from '../WorkbenchPortfolio'

const portfolio: WorkbenchPortfolioData = {
  window_days: 7,
  window_start: '2026-08-01T00:00:00Z',
  summary: {
    projects: 3,
    critical_projects: 1,
    attention_projects: 0,
    active_projects: 0,
    active_work: 1,
    pending_approvals: 0,
    unacknowledged_alerts: 0,
    delivered_turns_7d: 4,
    unassigned_work: 0,
  },
  items: [
    {
      project_id: 'project-1',
      name: '经营分析',
      description: '经营月报和指标复盘',
      status: 'critical',
      status_reason: '近 7 天有 1 次 AI 工作未完成',
      instructions_ready: true,
      data_source_count: 1,
      active_work: 1,
      active_responses: 0,
      active_goals: 1,
      pending_approvals: 0,
      failed_responses_7d: 1,
      unacknowledged_alerts: 0,
      active_automations: 1,
      delivered_turns_7d: 3,
      last_activity_at: '2026-08-08T01:00:00Z',
      next_action: {
        type: 'response',
        label: '检查并重试',
        title: '经营月报',
        description: '执行未完整结束，请查看事件后安全重试。',
        route: '/chat?conversation=conversation-1',
      },
    },
    {
      project_id: 'project-2',
      name: '客户运营',
      description: '客户成功流程',
      status: 'foundation',
      status_reason: '需要先补充业务背景、术语和输出约束',
      instructions_ready: false,
      data_source_count: 0,
      active_work: 0,
      active_responses: 0,
      active_goals: 0,
      pending_approvals: 0,
      failed_responses_7d: 0,
      unacknowledged_alerts: 0,
      active_automations: 0,
      delivered_turns_7d: 0,
      last_activity_at: '2026-08-07T01:00:00Z',
      next_action: {
        type: 'setup',
        label: '完善上下文',
        title: '补充 Project 业务指令',
        description: '写明业务背景、术语、输出规范和决策约束。',
        route: '/work?tab=projects',
      },
    },
    {
      project_id: 'project-3',
      name: '产品规划',
      description: '需求分析与方案设计',
      status: 'ready',
      status_reason: '业务指令已就绪，可以开始新的 AI 工作',
      instructions_ready: true,
      data_source_count: 0,
      active_work: 0,
      active_responses: 0,
      active_goals: 0,
      pending_approvals: 0,
      failed_responses_7d: 0,
      unacknowledged_alerts: 0,
      active_automations: 0,
      delivered_turns_7d: 1,
      last_activity_at: '2026-08-06T01:00:00Z',
      next_action: {
        type: 'start',
        label: '开始新工作',
        title: '在当前 Project 中发起 AI 工作',
        description: '聊天页会继承该 Project 的指令、记忆和数据授权。',
        route: '/chat',
      },
    },
  ],
}

function renderPortfolio() {
  return render(
    <MemoryRouter initialEntries={['/work?tab=portfolio']}>
      <Routes>
        <Route path="/work" element={<WorkbenchPortfolio portfolio={portfolio} />} />
        <Route path="/chat" element={<div>持久对话页面</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('Project 工作组合驾驶舱', () => {
  beforeEach(() => {
    useChatPreferences.getState().resetUserState()
  })

  it('展示跨执行面的项目健康状态并支持状态筛选', () => {
    renderPortfolio()

    expect(screen.getByRole('heading', { name: 'Project 工作组合驾驶舱' })).toBeInTheDocument()
    expect(screen.getByText('经营分析')).toBeInTheDocument()
    expect(screen.getByText('客户运营')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '待完善 1' }))
    expect(screen.queryByText('经营分析')).not.toBeInTheDocument()
    expect(screen.getByText('客户运营')).toBeInTheDocument()
  })

  it('把失败工作恢复到精确会话，而不是打开泛化聊天入口', () => {
    renderPortfolio()

    fireEvent.click(screen.getByRole('button', { name: /检查并重试/ }))
    expect(screen.getByText('持久对话页面')).toBeInTheDocument()
  })

  it('从就绪 Project 开始工作时预先选择对应上下文', () => {
    renderPortfolio()

    fireEvent.click(screen.getByRole('button', { name: /开始新工作/ }))
    expect(screen.getByText('持久对话页面')).toBeInTheDocument()
    expect(useChatPreferences.getState().projectId).toBe('project-3')
  })
})
