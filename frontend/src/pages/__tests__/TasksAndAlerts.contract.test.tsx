import { describe, expect, it } from 'vitest'

describe('scheduled tasks and alerts experience', () => {
  it('supports immediate runs and visible run history', async () => {
    const tasksSource = (await import('../TasksPage')).default.toString()
    expect(tasksSource).toContain('apiRunScheduledTask')
    expect(tasksSource).toContain('apiGetScheduledTask')
    expect(tasksSource).toContain('立即运行')
    expect(tasksSource).toContain('运行记录')
  })

  it('uses a bounded visual schedule picker with upcoming run previews', async () => {
    const tasksSource = (await import('../TasksPage')).default.toString()
    const pickerSource = (await import('../../components/ScheduleTimePicker')).ScheduleTimePicker.toString()
    expect(tasksSource).toContain('ScheduleTimePicker')
    expect(tasksSource).toContain('apiPreviewScheduledTaskRule')
    expect(pickerSource).toContain('起止时间')
    expect(pickerSource).toContain('执行时间')
    expect(pickerSource).toContain('接下来五次执行时间')
  })

  it('surfaces alert retries and pending acknowledgements', async () => {
    const alertsSource = (await import('../AlertsPage')).default.toString()
    expect(alertsSource).toContain('系统将在“下次”时间自动重试')
    expect(alertsSource).toContain('setEventFilter')
    expect(alertsSource).toContain('待确认')
  })

  it('exposes a shared notification inbox', async () => {
    const sidebarSource = (await import('../../components/Sidebar')).default.toString()
    expect(sidebarSource).toContain('apiListNotifications')
    expect(sidebarSource).toContain('全部已读')
    expect(sidebarSource).toContain('任务完成与主动预警会显示在这里')
  })
})
