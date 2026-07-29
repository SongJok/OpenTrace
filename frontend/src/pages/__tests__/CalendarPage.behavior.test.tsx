import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CalendarPage from '../CalendarPage'

vi.mock('../../store/auth', () => ({
  useAuthStore: (selector: (state: { token: string }) => unknown) => selector({ token: 'token' }),
}))

vi.mock('../../store/chatPreferences', () => ({
  useChatPreferences: (selector: (state: { requestPrefill: (text: string) => void }) => unknown) =>
    selector({ requestPrefill: vi.fn() }),
}))

describe('个人日历界面', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('在 2026 年 7 月月视图展示当前用户日程并可打开新建面板', async () => {
    const day = '2026-07-29'
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-07-29T08:00:00+08:00'))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: [{
        id: 'event-1', occurrence_id: 'event-1', title: '客户复盘', description: '', location: '会议室 A',
        event_type: 'meeting', start_at: `${day}T01:00:00+00:00`, end_at: `${day}T02:00:00+00:00`,
        local_start_at: `${day}T09:00:00+08:00`, local_end_at: `${day}T10:00:00+08:00`,
        timezone: 'Asia/Shanghai', view_timezone: 'Asia/Shanghai', all_day: false,
        recurrence_rule: null, reminder_minutes: [15], status: 'confirmed', source: 'assistant',
      }],
    }), { status: 200 })))

    render(<MemoryRouter><CalendarPage onBack={vi.fn()} /></MemoryRouter>)

    expect((await screen.findAllByText(/客户复盘/)).length).toBeGreaterThan(0)
    expect(screen.getByText('日历即时间型记忆')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '新建日程' }))
    expect(screen.getByRole('dialog', { name: '新建日程' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('日程标题')).toBeInTheDocument()
    vi.useRealTimers()
  })
})
