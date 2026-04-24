const ENGLISH_DATABASE_PATTERN = /\b(sql|query|database|schema|tables?|columns?|describe|desc|show tables|table list|list tables|table count|data source|analysis|chart|report|stats|group by|count|sum|avg|limit)\b/i
const CHINESE_DATABASE_PATTERN = /(数据库|数据源|库下|数据表|表结构|字段|列名|几张表|多少张表|多少个表|表数量|有哪些表|有什么表|列出表|表名|查询|统计|分析|图表|条数|总数|报表|分组|近\s*\d+\s*天|最近|最新|多少|销量|订单|收入|金额)/
const TABLE_COUNT_PATTERN = /(几张表|多少张表|多少个表|表数量|多少表|table count|how many tables)/i
const TABLE_LIST_PATTERN = /(有哪些表|有什么表|列出表|表名|show tables|table list|list tables)/i
const TABLE_SCHEMA_PATTERN = /(表结构|字段|列名|schema|columns?|describe|desc\b)/i

export type ChatDatabaseFilter = {
  column: string
  operator: '=' | '!=' | '>' | '>=' | '<' | '<=' | 'like' | 'in'
  value: string | number | boolean | Array<string | number | boolean>
}

export type ChatDatabaseQuerySpec = {
  sql: string
  limit?: number
  filters?: ChatDatabaseFilter[]
  order_by?: string
  order_dir?: 'asc' | 'desc'
}

export const isDatabaseQuestion = (query: string) => {
  const text = query.trim()
  if (!text) return false
  return ENGLISH_DATABASE_PATTERN.test(text) || CHINESE_DATABASE_PATTERN.test(text)
}

export const inferDatabaseQuerySpec = (query: string, tables: Array<{ name: string }>): ChatDatabaseQuerySpec => {
  const q = query.toLowerCase()
  const firstTable = tables.find((t) => t?.name)?.name || ''
  const pickTable = () => tables.find((t) => t?.name && !/information_schema|sys|pg_/i.test(t.name))?.name || firstTable
  const matchLimit = q.match(/(top|前|最近|latest|first|limit)\s*(\d{1,3})/i)
  const limit = matchLimit?.[2] ? Math.max(1, Math.min(200, Number(matchLimit[2]))) : 10
  const orderDesc = /(最新|最近|倒序|desc|降序|从大到小)/i.test(query)
  const orderBy = /(时间|日期|created|updated|updated_at|created_at)/i.test(query) ? 'created_at' : ''
  const baseTable = pickTable()

  if (TABLE_COUNT_PATTERN.test(query) || TABLE_LIST_PATTERN.test(query) || TABLE_SCHEMA_PATTERN.test(query)) {
    return { sql: '', limit }
  }

  if (/(sample|preview|前几行|最近数据|数据\s*\d+\s*行|查看数据)/i.test(q)) {
    return {
      sql: baseTable ? `SELECT * FROM ${baseTable}${orderBy ? ` ORDER BY ${orderBy} ${orderDesc ? 'DESC' : 'ASC'}` : ''} LIMIT ${limit}` : '',
      limit,
      order_by: orderBy || undefined,
      order_dir: orderDesc ? 'desc' : 'asc',
    }
  }

  const hasCount = /(count|数量|多少|总数|条数|记录数|有几条)/i.test(query)
  const hasSum = /(sum|合计|总和|金额|总额|汇总)/i.test(query)
  const hasAvg = /(avg|平均|均值|平均值)/i.test(query)
  const hasGroup = /(按|每个|每月|每日|分组|group by|类别|类型|地区|状态)/i.test(query)
  const filterMatch = query.match(/(状态|status|type|类型|地区|city|name)\s*(是|为|=|等于|like)?\s*([\p{L}\p{N}_-]+)/iu)
  const columnMap: Record<string, string> = {
    '状态': 'status',
    status: 'status',
    type: 'type',
    '类型': 'type',
    '地区': 'city',
    city: 'city',
    name: 'name',
  }
  const rawOperator = (filterMatch?.[2] || '=').toLowerCase()
  const operator: ChatDatabaseFilter['operator'] = rawOperator === 'like' ? 'like' : '='
  const filters = filterMatch
    ? [{ column: columnMap[filterMatch[1]] || 'status', operator, value: filterMatch[3] || '' }]
    : []

  if (!baseTable) return { sql: '', limit }

  if (hasCount && !hasSum && !hasAvg) {
    if (hasGroup) {
      const groupCol = /(按|每个|每月|每日|类别|类型|地区|状态)/i.test(query) ? 'created_at' : 'status'
      return {
        sql: `SELECT ${groupCol}, COUNT(*) AS count FROM ${baseTable}${filters.length ? ` WHERE ${filters.map((f) => `${f.column} ${f.operator} '${String(f.value)}'`).join(' AND ')}` : ''} GROUP BY ${groupCol} ORDER BY count DESC LIMIT ${limit}`,
        limit,
        filters,
        order_by: 'count',
        order_dir: 'desc',
      }
    }
    return {
      sql: `SELECT COUNT(*) AS count FROM ${baseTable}${filters.length ? ` WHERE ${filters.map((f) => `${f.column} ${f.operator} '${String(f.value)}'`).join(' AND ')}` : ''}`,
      limit,
      filters,
    }
  }

  const numericColumn = /(金额|收入|销售额|数量|价格|总额|value|amount|price|revenue)/i.test(query) ? 'amount' : ''
  if ((hasSum || hasAvg) && numericColumn) {
    const aggFn = hasAvg ? 'AVG' : 'SUM'
    if (hasGroup) {
      return {
        sql: `SELECT DATE_TRUNC('month', created_at) AS period, ${aggFn}(${numericColumn}) AS value FROM ${baseTable}${filters.length ? ` WHERE ${filters.map((f) => `${f.column} ${f.operator} '${String(f.value)}'`).join(' AND ')}` : ''} GROUP BY period ORDER BY period DESC LIMIT ${limit}`,
        limit,
        filters,
        order_by: 'period',
        order_dir: 'desc',
      }
    }
    return {
      sql: `SELECT ${aggFn}(${numericColumn}) AS value FROM ${baseTable}${filters.length ? ` WHERE ${filters.map((f) => `${f.column} ${f.operator} '${String(f.value)}'`).join(' AND ')}` : ''}`,
      limit,
      filters,
    }
  }

  if (hasGroup) {
    return {
      sql: `SELECT created_at, COUNT(*) AS count FROM ${baseTable}${filters.length ? ` WHERE ${filters.map((f) => `${f.column} ${f.operator} '${String(f.value)}'`).join(' AND ')}` : ''} GROUP BY created_at ORDER BY created_at DESC LIMIT ${limit}`,
      limit,
      filters,
      order_by: 'created_at',
      order_dir: 'desc',
    }
  }

  return {
    sql: `SELECT * FROM ${baseTable}${filters.length ? ` WHERE ${filters.map((f) => `${f.column} ${f.operator} '${String(f.value)}'`).join(' AND ')}` : ''}${orderBy ? ` ORDER BY ${orderBy} ${orderDesc ? 'DESC' : 'ASC'}` : ''} LIMIT ${limit}`,
    limit,
    filters,
    order_by: orderBy || undefined,
    order_dir: orderDesc ? 'desc' : 'asc',
  }
}
