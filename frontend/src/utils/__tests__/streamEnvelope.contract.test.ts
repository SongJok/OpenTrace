import { describe, expect, it } from 'vitest'
import { normalizeFinalAnswerEnvelope } from '../streamEnvelope'

describe('streamEnvelope contract', () => {
  it('merges enterprise fields from metadata.semantic_observability', () => {
    const env = normalizeFinalAnswerEnvelope({
      content: 'ok',
      metadata: {
        control_plane: { allowed: true },
        capabilities_used: ['data_query'],
        prompt_tokens: 12,
        semantic_observability: {
          enterprise_telemetry: { cognitive: { route: 'tier0' } },
        },
      },
    })
    expect(env.control_plane?.allowed).toBe(true)
    expect(env.capabilities_used).toEqual(['data_query'])
    expect(env.prompt_tokens).toBe(12)
    expect(env.enterprise_telemetry).toEqual({ cognitive: { route: 'tier0' } })
  })

  it('detects clarification turn_outcome', () => {
    const env = normalizeFinalAnswerEnvelope({
      content: '请指定表',
      metadata: {
        needs_clarification: true,
        turn_outcome: 'clarification',
        clarification: { question_text: '哪张表？', suggested_options: ['orders'] },
      },
    })
    expect(env.needs_clarification).toBe(true)
    expect(env.turn_outcome).toBe('clarification')
    expect(env.clarification?.question_text).toBe('哪张表？')
  })

  it('surfaces governance warnings from runtime_degraded', () => {
    const env = normalizeFinalAnswerEnvelope({
      content: 'x',
      metadata: {
        runtime_degraded: [{ subsystem: 'turn_metering' }],
      },
    })
    expect(env.governance_warnings).toContain('turn_metering')
  })
})