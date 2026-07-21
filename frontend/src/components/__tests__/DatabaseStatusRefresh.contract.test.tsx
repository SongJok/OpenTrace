import { describe, expect, it } from 'vitest'

describe('Database status refresh contract', () => {
  it('keeps test connection and refresh affordances visible', async () => {
    const page = await import('../../pages/DatabasesPage')
    const source = page.default.toString()
    expect(source).toContain('测试连接')
    expect(source).toContain('同步Schema')
    expect(source).toContain('load()')
  })
})
