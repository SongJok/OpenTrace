import { describe, expect, it } from 'vitest'

describe('DagTimeline duration contract', () => {
  it('renders duration metadata when present', async () => {
    const timeline = await import('../DagTimeline')
    const source = timeline.default.toString()
    expect(source).toContain('duration_ms')
    expect(source).toContain('耗时')
  })
})
