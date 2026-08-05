import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { WorkbenchOperatingPulse } from '../../api/client'
import { WorkbenchTodayPulse } from '../WorkbenchTodayPulse'

const pulse: WorkbenchOperatingPulse = {
  timezone: 'Asia/Shanghai',
  local_date: '2026-08-05',
  day_start: '2026-08-04T16:00:00+00:00',
  day_end: '2026-08-05T16:00:00+00:00',
  status: 'critical',
  headline: '有 1 项高风险工作需要立即处理',
  summary: {
    urgent_items: 2,
    calendar_events: 1,
    due_automations: 1,
    overdue_automations: 1,
    stale_goals: 1,
    focus_minutes: 90,
    meeting_minutes: 45,
  },
  focus_items: [{
    id: 'alert-1',
    type: 'alert',
    severity: 'critical',
    title: '现金流指标异常',
    description: '关键业务指标已触发规则。',
    route: '/alerts',
    priority: 'p0',
    priority_score: 130,
    priority_reason: '关键业务预警尚未确认',
    created_at: '2026-08-05T01:00:00Z',
  }],
  timeline: [{
    id: 'meeting-1',
    type: 'calendar',
    title: '经营复盘会',
    description: '会议室 A',
    status: 'upcoming',
    route: '/calendar',
    start_at: '2026-08-05T02:00:00Z',
    end_at: '2026-08-05T02:45:00Z',
    event_type: 'meeting',
  }],
}

function renderPulse() {
  return render(
    <MemoryRouter initialEntries={['/work']}>
      <Routes>
        <Route path="/work" element={<WorkbenchTodayPulse pulse={pulse} />} />
        <Route path="/alerts" element={<div>主动预警页面</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('今日工作脉搏', () => {
  it('展示可解释优先级、日程和自动化摘要', () => {
    renderPulse()

    expect(screen.getByRole('region', { name: '今日工作脉搏' })).toBeInTheDocument()
    expect(screen.getByText('有 1 项高风险工作需要立即处理')).toBeInTheDocument()
    expect(screen.getByText('现金流指标异常')).toBeInTheDocument()
    expect(screen.getByText('P0')).toBeInTheDocument()
    expect(screen.getByText('经营复盘会')).toBeInTheDocument()
    expect(screen.getByText('专注时间 1 小时 30 分')).toBeInTheDocument()
  })

  it('从优先事项直接进入对应治理页面', () => {
    renderPulse()
    fireEvent.click(screen.getByRole('button', { name: /现金流指标异常/ }))
    expect(screen.getByText('主动预警页面')).toBeInTheDocument()
  })
})
