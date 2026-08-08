import { apiFetch, authHeaders, readApiError } from './transport'

export interface DatabaseSchemaColumn {
  name: string
  type: string
  comment?: string
}

export interface DatabaseSchemaTable {
  name: string
  database?: string
  qualified_name?: string
  comment?: string
  columns: DatabaseSchemaColumn[]
}

export interface DatabaseSchemaPayload {
  schema?: string
  database_scope?: string
  databases?: string[]
  database_count?: number
  table_count?: number
  metadata_warning?: string | null
  tables_truncated?: boolean
  columns_truncated?: boolean
  sync_page_size?: number
  synced_at?: number
  tables: DatabaseSchemaTable[]
}

export interface DatabaseSchemaPagination {
  offset: number
  limit: number
  count: number
  total: number
  has_more: boolean
  next_offset?: number | null
}

export interface DatabaseSchemaResponse {
  data_source_id: string
  schema: DatabaseSchemaPayload
  pagination: DatabaseSchemaPagination
}

export async function apiGetDatabaseSchema(
  token: string,
  id: string,
  options: { search?: string; database?: string; offset?: number; limit?: number } = {},
): Promise<DatabaseSchemaResponse> {
  const params = new URLSearchParams()
  if (options.search?.trim()) params.set('search', options.search.trim())
  if (options.database?.trim()) params.set('database', options.database.trim())
  params.set('offset', String(Math.max(0, options.offset || 0)))
  params.set('limit', String(Math.max(1, options.limit || 100)))
  const res = await apiFetch(`/databases/${id}/schema?${params.toString()}`, {
    headers: authHeaders(token),
  })
  if (!res.ok) throw new Error(await readApiError(res, '读取数据库 Schema 失败'))
  return res.json()
}
