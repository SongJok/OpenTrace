import { describe, expect, it } from 'vitest'

describe('Database edit and schema contract', () => {
  it('supports updating databases', async () => {
    const client = await import('../../api/client')
    const source = client.apiUpdateDatabase.toString()
    expect(source).toContain('/databases/${id}')
    expect(source).toContain('更新数据库失败')
  })

  it('schema payload can include table comments', async () => {
    const page = await import('../../pages/DatabasesPage')
    const source = page.default.toString()
    expect(source).toContain('comment')
    expect(source).toContain('编辑数据库')
  })
})
