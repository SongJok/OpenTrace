import { describe, expect, it } from 'vitest'

describe('Database list metadata contract', () => {
  it('lists metadata fields used by the database page', async () => {
    const page = await import('../../pages/DatabasesPage')
    const source = page.default.toString()
    expect(source).toContain('updated_at')
    expect(source).toContain('table_count')
    expect(source).toContain('连接成功')
  })
})
