import { describe, expect, it } from 'vitest'

describe('password management contract', () => {
  it('lets the signed-in user change their own password from settings', async () => {
    const page = await import('../SettingsPage')
    const source = page.default.toString()

    expect(source).toContain('修改密码')
    expect(source).toContain('apiChangePassword')
    expect(source).toContain('oldPassword')
    expect(source).toContain('confirmPassword')
  })

  it('lets an administrator enter a new password on the permissions page', async () => {
    const page = await import('../PermissionsPage')
    const source = page.default.toString()

    expect(source).toContain('重置密码')
    expect(source).toContain('apiResetUserPassword')
    expect(source).toContain('resetTarget')
  })
})
