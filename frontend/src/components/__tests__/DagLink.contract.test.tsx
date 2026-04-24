import { describe, expect, it } from 'vitest'

describe('Dag link contract', () => {
  it('timeline can emit dag node selection event', async () => {
    const timeline = await import('../DagTimeline')
    const source = timeline.default.toString()
    expect(source).toContain('opentrace:select-dag-node')
  })

  it('execution graph panel reacts to dag node selection', async () => {
    const panel = await import('../ExecutionGraphPanel')
    const source = panel.default.toString()
    expect(source).toContain('opentrace:select-dag-node')
    expect(source).toContain('highlightNodeId')
  })
})
