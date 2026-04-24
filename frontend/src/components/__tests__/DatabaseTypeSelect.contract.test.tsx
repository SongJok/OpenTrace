import { describe, expect, it } from 'vitest'

describe('DatabaseTypeSelect contract', () => {
  it('supports local and self-hosted database options only', async () => {
    const comp = await import('../DatabaseTypeSelect')
    const source = comp.default.toString()
    expect(source).toContain('本地 / 自建 MySQL')
    expect(source).toContain('本地 / 自建 ClickHouse')
    expect(source).toContain('本地 / 自建 Doris')
    expect(source).toContain('本地 / 自建 PostgreSQL')
  })
})
