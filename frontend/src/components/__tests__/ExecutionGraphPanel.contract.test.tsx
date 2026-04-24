import { describe, expect, it } from 'vitest'

describe('ExecutionGraphPanel contract', () => {
  it('highlights running nodes', async () => {
    const panel = await import('../ExecutionGraphPanel')
    const source = panel.default.toString()
    expect(source).toContain('animate-pulse')
    expect(source).toContain('ring-2 ring-sky-400')
  })
})
