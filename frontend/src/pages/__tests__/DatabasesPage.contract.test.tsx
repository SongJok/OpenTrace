import { describe, expect, it } from 'vitest'

describe('DatabasesPage contract', () => {
  it('keeps the add database flow focused on local and external databases', async () => {
    const mod = await import('../DatabasesPage')
    const source = mod.default.toString()

    expect(source).toContain('仅支持连接本机/宿主机或外部链接数据库')
    expect(source).toContain('DATABASE_HOST_MODE_OPTIONS')
    expect(source).toContain('localhost')
    expect(source).toContain('保存并测试连接')
  })
})
