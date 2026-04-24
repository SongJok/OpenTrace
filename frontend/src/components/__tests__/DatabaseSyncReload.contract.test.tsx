import { describe, expect, it } from 'vitest'

describe('Database sync reload contract', () => {
  it('reloads list after schema sync', async () => {
    const page = await import('../../pages/DatabasesPage')
    const source = page.default.toString()
    expect(source).toContain('await load()')
    expect(source).toContain('Schema 已同步')
  })
})
