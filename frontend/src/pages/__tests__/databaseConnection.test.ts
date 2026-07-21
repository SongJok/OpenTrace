import { describe, expect, it } from 'vitest'

import { isAllowedDatabaseHost, parseJdbcLikeHostInput } from '../../lib/databaseConnection'

describe('databaseConnection helpers', () => {
  it('allows external domain hosts', () => {
    expect(isAllowedDatabaseHost('analytics.example.com')).toBe(true)
  })

  it('rejects docker internal service names', () => {
    expect(isAllowedDatabaseHost('mysql')).toBe(false)
  })

  it('parses full jdbc pasted into the host input', () => {
    const parsed = parseJdbcLikeHostInput('jdbc:mysql://127.0.0.1:3306/test_db?allowPublicKeyRetrieval=TRUE', {
      source_type: 'mysql',
      port: 3306,
      database: '',
    })

    expect(parsed).not.toBeNull()
    expect(parsed?.host).toBe('127.0.0.1')
    expect(parsed?.port).toBe(3306)
    expect(parsed?.database).toBe('test_db')
    expect(parsed?.params).toBe('allowPublicKeyRetrieval=TRUE')
  })
})
