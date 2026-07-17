import { describe, expect, it } from 'vitest'

import { createClientId } from '../clientId'

describe('createClientId', () => {
  it('uses randomUUID when the secure-context API exists', () => {
    expect(createClientId('attachment_', { randomUUID: () => 'native-uuid' })).toBe('attachment_native-uuid')
  })

  it('uses getRandomValues when randomUUID is unavailable over HTTP', () => {
    const cryptoApi = {
      getRandomValues: (values: Uint8Array) => {
        values.set(Array.from({ length: 16 }, (_, index) => index))
        return values
      },
    }
    const id = createClientId('attachment_', cryptoApi)

    expect(id).toBe('attachment_00010203-0405-4607-8809-0a0b0c0d0e0f')
  })

  it('still returns a unique-looking ID without Web Crypto', () => {
    expect(createClientId('attachment_', {})).toMatch(/^attachment_[a-z0-9]+-[a-z0-9]+$/)
  })
})
