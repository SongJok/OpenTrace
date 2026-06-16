import { describe, expect, it } from 'vitest'

describe('Dag timeline contract', () => {
  it('frontend stream supports dag node events', async () => {
    const mod = await import('../../api/client')
    const source = mod.streamSseResponse.toString()
    expect(source).toContain('dag_node_start')
    expect(source).toContain('dag_node_complete')
  })

  it('chat store supports dag node updates', async () => {
    const store = await import('../../store/chat')
    expect(typeof store.useChatStore.getState().updateDagNodeEvent).toBe('function')
  })
})
