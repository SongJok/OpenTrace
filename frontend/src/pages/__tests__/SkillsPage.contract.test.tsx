import { describe, expect, it } from 'vitest'
describe('SkillsPage marketplace contract', () => {
  it('keeps discovery, account installs and developer tools separated', async () => {
    const page = await import('../SkillsPage')
    const source = page.default.toString()
    expect(source).toContain('技能广场')
    expect(source).toContain('我的 Skills')
    expect(source).toContain('开发者工具')
  })

  it('presents the governed registry discovery hierarchy', async () => {
    const page = await import('../SkillsPage')
    const source = page.default.toString()
    expect(source).toContain('OpenTrace')
    expect(source).toContain('首页')
    expect(source).toContain('搜索 Skills')
    expect(source).toContain('热门下载')
    expect(source).toContain('最新发布')
    expect(source).toContain('安全通过')
    expect(source).toContain('当前会话启用')
  })

  it('exposes append-only catalog governance to administrators', async () => {
    const page = await import('../SkillsPage')
    const source = page.CatalogGovernancePanel.toString()
    expect(source).toContain('平台目录治理')
    expect(source).toContain('只增不删')
    expect(source).toContain('暂停使用')
    expect(source).toContain('立即同步')
  })
})
