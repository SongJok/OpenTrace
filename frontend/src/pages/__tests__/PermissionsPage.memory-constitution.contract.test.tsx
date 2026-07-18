import { describe, expect, it } from 'vitest'

describe('PermissionsPage memory constitution contract', () => {
  it('exposes versioned constitution editing and immediate-effect feedback', async () => {
    const page = await import('../PermissionsPage')
    const source = page.default.toString()

    expect(source).toContain('记忆宪法')
    expect(source).toContain('发布新版本')
    expect(source).toContain('已实时生效')
    expect(source).toContain('不可被关闭')
  })

  it('keeps hard safety categories locked and exposes proactive controls', async () => {
    const page = await import('../PermissionsPage')
    const source = page.default.toString()

    expect(source).toContain('immutable_categories')
    expect(source).toContain('proactive_activation_observations')
    expect(source).toContain('min_proactive_confidence')
    expect(source).toContain('custom_blocked_terms')
  })

  it('shows privacy-safe constitution decision audits', async () => {
    const page = await import('../PermissionsPage')
    const source = page.default.toString()

    expect(source).toContain('最近宪法决策')
    expect(source).toContain('内容哈希')
    expect(source).not.toContain('content_hash}')
  })

  it('previews impact and protects concurrent administrator updates', async () => {
    const page = await import('../PermissionsPage')
    const source = page.default.toString()

    expect(source).toContain('影响预览')
    expect(source).toContain('would_quarantine_count')
    expect(source).toContain('expected_version')
  })

  it('exposes append-only history restore without rewriting old versions', async () => {
    const page = await import('../PermissionsPage')
    const source = page.default.toString()

    expect(source).toContain('版本历史')
    expect(source).toContain('恢复此版本')
    expect(source).toContain('apiRestoreMemoryConstitution')
  })
})
