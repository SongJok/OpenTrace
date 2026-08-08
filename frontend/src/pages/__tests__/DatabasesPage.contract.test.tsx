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

  it('keeps Text2SQL generation separate from candidate execution', async () => {
    const page = await import('../DatabasesPage')
    const source = page.default.toString()

    expect(source).toContain('生成 SQL 草案')
    expect(source).toContain('SQL 候选')
    expect(source).toContain('executeDraft')
    expect(source).toContain('执行全部')
  })

  it('exposes SQL asset upload and review controls', async () => {
    const page = await import('../DatabasesPage')
    const source = page.default.toString()

    expect(source).toContain('SQL 资产')
    expect(source).toContain('上传 SQL')
    expect(source).toContain('校验通过')
    expect(source).toContain('changeSQLAssetStatus')
    expect(source).toContain('搜索标题、描述或 SQL')
    expect(source).toContain('saveSQLAssetMetadata')
    expect(source).toContain('SQL_ASSET_PAGE_SIZE')
    expect(source).toContain('ClickHouse 可不指定数据库')
  })

  it('uses dedicated draft and asset APIs', async () => {
    const client = await import('../../api/client')

    expect(client.apiUploadSQLAsset.toString()).toContain('/sql-assets/upload')
    expect(client.apiUpdateSQLAsset.toString()).toContain('/sql-assets/${assetId}')
    expect(client.apiExecuteSQLDraft.toString()).toContain('/sql-drafts/${draftId}/execute')
    expect(client.apiExecuteSQLDraft.toString()).toContain('retry_failed')
    expect(client.apiGetSQLDraft.toString()).toContain('/sql-drafts/${draftId}')
  })

  it('loads large schema catalogs through searchable server pagination', async () => {
    const page = await import('../DatabasesPage')
    const client = await import('../../api/client')
    const source = page.default.toString()

    expect(source).toContain('SCHEMA_TABLE_PAGE_SIZE')
    expect(source).toContain('schemaPagination')
    expect(source).toContain('搜索表名、注释或所属库')
    expect(source).toContain('继续加载')
    expect(client.apiGetDatabaseSchema.toString()).toContain('URLSearchParams')
    expect(client.apiGetDatabaseSchema.toString()).toContain('/schema?')
  })
})
