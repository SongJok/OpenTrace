import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiListCalendarEvents } from '../../api/client'

describe('personal calendar product contracts', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('offers a DingTalk-inspired month and agenda workspace', async () => {
    const source = (await import('../CalendarPage')).default.toString()
    expect(source).toContain('我的日历')
    expect(source).toContain('setView("month")')
    expect(source).toContain('setView("agenda")')
    expect(source).toContain('新建日程')
    expect(source).toContain('通过 AI 添加')
    expect(source).toContain('日历即时间型记忆')
  })

  it('supports manual create, edit and cancel flows', async () => {
    const source = (await import('../CalendarPage')).default.toString()
    expect(source).toContain('apiCreateCalendarEvent')
    expect(source).toContain('apiUpdateCalendarEvent')
    expect(source).toContain('apiCancelCalendarEvent')
    expect(source).toContain('recurrence_rule')
    expect(source).toContain('reminder_minutes')
  })

  it('links calendar from the authenticated app shell and chat assistant', async () => {
    const appSource = (await import('../../App')).default.toString()
    const sidebarSource = (await import('../../components/Sidebar')).default.toString()
    const chatInputSource = (await import('../../components/ChatInput')).default.toString()
    expect(appSource).toContain('path: "/calendar"')
    expect(sidebarSource).toContain('我的日历')
    expect(chatInputSource).toContain('resolvedOptions().timeZone')
    expect(sidebarSource).toContain('notification.kind === "calendar"')
  })

  it('reads calendar events from the scoped v2 API', async () => {
    const payload = { items: [{ id: 'event-1', title: '客户复盘' }] }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiListCalendarEvents(
      'token',
      '2026-07-29T00:00:00.000Z',
      '2026-08-10T00:00:00.000Z',
      'Asia/Shanghai',
    )

    expect(result).toHaveLength(1)
    expect(fetchMock.mock.calls[0][0]).toContain('/api/v2/calendar/events?')
    expect(fetchMock.mock.calls[0][0]).toContain('timezone=Asia%2FShanghai')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      headers: expect.objectContaining({ Authorization: 'Bearer token' }),
    })
  })
})
