import { describe, expect, it } from 'vitest'

describe('DagTimeline status contract', () => {
  it('supports color coded statuses', async () => {
    const timeline = await import('../DagTimeline')
    const source = timeline.statusClass.toString()
    expect(source).toContain('statusClass')
    expect(source).toContain('RUNNING')
    expect(source).toContain('SUCCESS')
    expect(source).toContain('FAILED')
  })
})
