import { describe, expect, it } from 'vitest'

describe('PermissionsPage chat constitution contract', () => {
  it('places administrator-managed chat constitution on permissions page', async () => {
    const page = await import('../PermissionsPage')
    const pageSource = page.default.toString()
    const panelSource = page.ChatConstitutionPanel.toString()

    expect(pageSource).toContain('chat_constitution')
    expect(pageSource).toContain('聊天宪法')
    expect(pageSource).toContain('ChatConstitutionPanel')
    expect(panelSource).toContain('发布新版本')
    expect(panelSource).toContain('apiUpdateChatConstitution')
  })

  it('supports test, immutable categories, history restore and privacy-safe audits', async () => {
    const page = await import('../PermissionsPage')
    const source = page.ChatConstitutionPanel.toString()

    expect(source).toContain('发布前样例判定')
    expect(source).toContain('immutable_categories')
    expect(source).toContain('恢复此版本')
    expect(source).toContain('apiRestoreChatConstitution')
    expect(source).toContain('原始问题不写入审计')
    expect(source).toContain('content_length')
  })
})
