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
    expect(source).toContain('brandName')
    expect(source).toContain('首页')
    expect(source).toContain('搜索 Skills')
    expect(source).toContain('热门下载')
    expect(source).toContain('最新发布')
    expect(source).toContain('安全通过')
    expect(source).toContain('当前会话启用')
  })

  it('exposes local mirror governance to administrators', async () => {
    const page = await import('../SkillsPage')
    const source = page.CatalogGovernancePanel.toString()
    expect(source).toContain('本地 Skill 镜像治理')
    expect(source).toContain('06:30')
    expect(source).toContain('不访问外网')
    expect(source).toContain('暂停使用')
    expect(source).toContain('立即同步')
  })

  it('installs only from the local mirror and does not expose Git installation', async () => {
    const page = await import('../SkillsPage')
    const source = page.default.toString()
    expect(source).toContain('本地镜像安装策略')
    expect(source).toContain('只复制本地镜像')
    expect(source).not.toContain('从 Git 安装')
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

  it('supports governed file and folder distillation with company publication', async () => {
    const page = await import('../SkillsPage')
    const source = page.default.toString()
    expect(source).toContain('蒸馏企业 Skill')
    expect(source).toContain('选择文件夹')
    expect(source).toContain('公司发布')
    expect(source).toContain('不运行文件中的代码')
  })
})
