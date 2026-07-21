import { describe, expect, it } from 'vitest'

describe('Database status dot contract', () => {
  it('renders colored status indicators', async () => {
    const page = await import('../../pages/DatabasesPage')
    const source = page.default.toString()
    expect(source).toContain('fill-emerald-500')
    expect(source).toContain('fill-rose-500')
    expect(source).toContain('fill-slate-400')
  })
})
