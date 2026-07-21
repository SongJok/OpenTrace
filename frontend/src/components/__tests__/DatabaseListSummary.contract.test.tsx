import { describe, expect, it } from 'vitest'

describe('Database list summary contract', () => {
  it('shows sync metadata on cards', async () => {
    const page = await import('../../pages/DatabasesPage')
    const source = page.default.toString()
    expect(source).toContain('table_count')
    expect(source).toContain('last_schema_sync_at')
    expect(source).toContain('synced_at')
  })
})
