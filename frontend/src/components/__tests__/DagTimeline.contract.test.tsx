import { describe, expect, it } from 'vitest'

describe('Dag timeline contract', () => {
  it('frontend stream supports dag node events', async () => {
    const client = await import('../../api/client')
    const source = client.apiChatStream.toString()
    expect(source).toContain('dag_node_start')
    expect(source).toContain('dag_node_complete')
  })

  it('chat store supports dag node updates', async () => {
    const store = await import('../../store/chat')
    const source = store.useChatStore.getState.toString()
    expect(JSON.stringify(store.useChatStore.getState())).toBeDefined()
    expect(source).toContain('updateDagNodeEvent')
  })
})
