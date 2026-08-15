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
    expect(source).not.toContain('当前会话启用')
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

  it('refreshes an initially empty local mirror without a manual reload', async () => {
    const page = await import('../SkillsPage')
    const source = page.default.toString()
    expect(source).toContain('window.setInterval')
    expect(source).toContain('refreshCatalog')
  })

  it('keeps Skills management independent from the question workflow', async () => {
    const page = await import('../SkillsPage')
    const source = page.default.toString()
    expect(source).toContain('管理当前账户已部署的本地能力')
    expect(source).not.toContain('目标会话')
    expect(source).not.toContain('apiSetSessionSkills')
  })

  it('uploads pre-distilled company skill packages without active project distillation', async () => {
    const page = await import('../SkillsPage')
    const source = page.default.toString()
    expect(source).toContain('上传公司 Skill')
    expect(source).toContain('选择 Skill 文件夹')
    expect(source).toContain('SKILL.md')
    expect(source).toContain('公司发布')
    expect(source).toContain('不调用模型蒸馏')
    expect(source).toContain('不执行包内代码')
    expect(source).not.toContain('蒸馏企业 Skill')
    expect(source).not.toContain('蒸馏并公司发布')
  })
})
