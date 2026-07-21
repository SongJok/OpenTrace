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

  it('restores a usable conversation so installed Skills can be powered on', async () => {
    const page = await import('../SkillsPage')
    const sessions = [
      { id: 'recent-session', title: '最近会话', turn_count: 1, created_at: '', last_active: '' },
      { id: 'older-session', title: '历史会话', turn_count: 1, created_at: '', last_active: '' },
    ]
    expect(page.resolveSkillSessionId('older-session', null, sessions)).toBe('older-session')
    expect(page.resolveSkillSessionId(null, 'older-session', sessions)).toBe('older-session')
    expect(page.resolveSkillSessionId(null, 'missing-session', sessions)).toBe('recent-session')
    expect(page.resolveSkillSessionId(null, null, [])).toBeNull()
    expect(page.default.toString()).toContain('目标会话')
  })
})
