import type { DatabaseHostMode, DatabaseType } from '../components/DatabaseTypeSelect'

const SUPPORTED_DATABASE_TYPES = new Set<DatabaseType>(['mysql', 'clickhouse', 'doris', 'postgres'])
const LOCAL_DATABASE_HOSTS = new Set(['localhost', '127.0.0.1', '::1', 'host.docker.internal'])
const DOCKER_INTERNAL_DATABASE_HOSTS = new Set(['db', 'mysql', 'postgres', 'mariadb', 'clickhouse', 'doris', 'redis', 'service-db', 'database'])
const EXTERNAL_HOST_PATTERN = /^[a-z0-9.-]+$/i
const IPV4_SEGMENT = '(25[0-5]|2[0-4]\\d|1?\\d?\\d)'
const IPV4_PATTERN = new RegExp(`^${IPV4_SEGMENT}(\\.${IPV4_SEGMENT}){3}$`)
const IPV6_PATTERN = /^[0-9a-f:]+$/i

export type ParsedJdbc = {
  source_type: DatabaseType
  host: string
  port?: number
  database: string
  params: string
}

type JdbcLikeHostFallback = {
  source_type: DatabaseType
  port: number
  database: string
}

export const getDefaultHostForMode = (mode: DatabaseHostMode) => (mode === 'local' ? '127.0.0.1' : '')

export const getDefaultJdbcParams = (sourceType: DatabaseType) => (sourceType === 'mysql' ? 'allowPublicKeyRetrieval=true' : '')

export const buildJdbc = (sourceType: DatabaseType, host: string, port: number, database: string, params = getDefaultJdbcParams(sourceType)) => {
  const base = `jdbc:${sourceType}://${host}:${port}${database ? `/${database}` : ''}`
  return params.trim() ? `${base}?${params.trim().replace(/^\?/, '')}` : base
}

export const normalizeDatabaseHost = (host: string) => host.trim()

export const isLocalHost = (host: string) => LOCAL_DATABASE_HOSTS.has(normalizeDatabaseHost(host).toLowerCase())

export const isAllowedDatabaseHost = (host: string) => {
  const normalized = normalizeDatabaseHost(host).toLowerCase()
  if (!normalized || DOCKER_INTERNAL_DATABASE_HOSTS.has(normalized)) return false
  if (LOCAL_DATABASE_HOSTS.has(normalized)) return true
  if (IPV4_PATTERN.test(normalized)) return true
  if (normalized.includes(':') && IPV6_PATTERN.test(normalized)) return true
  return EXTERNAL_HOST_PATTERN.test(normalized)
}

export const parseJdbc = (jdbc: string): ParsedJdbc | null => {
  const raw = jdbc.trim()
  const matched = raw.match(/^jdbc:([a-z]+):\/\/(\[[^\]]+\]|[^:/?#]+)(?::(\d+))?(?:\/([^?#]*))?(?:\?(.*))?$/i)
  if (!matched) return null
  const [, scheme, rawHost, port, database = '', query = ''] = matched
  const sourceType = scheme.toLowerCase()
  if (!SUPPORTED_DATABASE_TYPES.has(sourceType as DatabaseType)) return null
  const host = rawHost.startsWith('[') && rawHost.endsWith(']') ? rawHost.slice(1, -1) : rawHost
  return {
    source_type: sourceType as DatabaseType,
    host,
    port: port ? Number(port) : undefined,
    database,
    params: query,
  }
}

export const parseJdbcLikeHostInput = (hostInput: string, fallback: JdbcLikeHostFallback) => {
  const parsed = parseJdbc(hostInput)
  if (!parsed) return null
  const nextSourceType = parsed.source_type
  const nextHost = normalizeDatabaseHost(parsed.host)
  const nextPort = parsed.port || fallback.port
  const nextDatabase = parsed.database.trim() || fallback.database
  const nextParams = parsed.params || getDefaultJdbcParams(nextSourceType)
  const nextHostMode: DatabaseHostMode = isLocalHost(nextHost) ? 'local' : 'external'
  return {
    source_type: nextSourceType,
    host_mode: nextHostMode,
    host: nextHost,
    port: nextPort,
    database: nextDatabase,
    params: nextParams,
    jdbc: buildJdbc(nextSourceType, nextHost, nextPort, nextDatabase, nextParams),
  }
}
