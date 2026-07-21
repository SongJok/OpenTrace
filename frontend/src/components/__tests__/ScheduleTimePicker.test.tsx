import { describe, expect, it } from 'vitest'
import { DEFAULT_SCHEDULE_EDITOR, buildScheduleRRule } from '../ScheduleTimePicker'

describe('ScheduleTimePicker', () => {
  it('builds stable rules for the visual schedule modes', () => {
    expect(buildScheduleRRule(DEFAULT_SCHEDULE_EDITOR)).toBe('FREQ=DAILY;INTERVAL=1;BYHOUR=9;BYMINUTE=0;BYSECOND=0')
    expect(buildScheduleRRule({ ...DEFAULT_SCHEDULE_EDITOR, frequency: 'week', weekdays: ['MO', 'WE'], hour: 10, minute: 30 })).toBe('FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,WE;BYHOUR=10;BYMINUTE=30;BYSECOND=0')
    expect(buildScheduleRRule({ ...DEFAULT_SCHEDULE_EDITOR, frequency: 'month', monthDay: 15 })).toContain('BYMONTHDAY=15')
  })

  it('clamps unsafe numeric values before creating a rule', () => {
    expect(buildScheduleRRule({ ...DEFAULT_SCHEDULE_EDITOR, frequency: 'hour', interval: 0, minute: 80 })).toBe('FREQ=HOURLY;INTERVAL=1;BYMINUTE=59;BYSECOND=0')
  })
})
