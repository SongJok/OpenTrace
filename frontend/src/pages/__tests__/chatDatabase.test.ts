import { describe, expect, it } from 'vitest'

import { inferDatabaseQuerySpec, isDatabaseQuestion } from '../../lib/chatDatabase'

describe('chatDatabase helpers', () => {
  it('detects chinese database questions in chat', () => {
    expect(isDatabaseQuestion('test_db库下有几张表')).toBe(true)
    expect(isDatabaseQuestion('test_db下面有哪些表')).toBe(true)
    expect(isDatabaseQuestion('帮我写一段 Python 代码')).toBe(false)
  })

  it('delegates table count and table list questions to backend text2sql', () => {
    expect(inferDatabaseQuerySpec('test_db库下有几张表', [{ name: 'orders' }])).toEqual({ sql: '', limit: 10 })
    expect(inferDatabaseQuerySpec('test_db下面有哪些表', [{ name: 'orders' }])).toEqual({ sql: '', limit: 10 })
  })

  it('keeps simple preview queries as direct select statements', () => {
    const spec = inferDatabaseQuerySpec('查看 orders 前 5 行数据', [{ name: 'orders' }])

    expect(spec.sql).toContain('SELECT * FROM orders')
    expect(spec.sql).toContain('LIMIT 5')
  })
})
