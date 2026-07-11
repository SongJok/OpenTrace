import { describe, expect, it } from 'vitest'
import { streamSseResponse } from '../../api/client'

describe('Responses API stream compatibility', () => {
  it('renders typed text deltas and completes from a response.completed event', async () => {
    const deltas: string[] = []
    const finals: string[] = []
    const response = new Response(
      [
        'data: {"sequence_number":1,"type":"response.output_text.delta","data":{"delta":"你好"}}\n\n',
        'data: {"sequence_number":2,"type":"response.completed","data":{"content":"你好","metadata":{"trace_id":"trace_1"}}}\n\n',
      ].join(''),
      { headers: { 'content-type': 'text/event-stream' } },
    )

    await streamSseResponse(response, {
      onDelta: (text) => { deltas.push(text) },
      onFinalAnswer: (envelope) => { finals.push(envelope.content) },
    })

    expect(deltas).toEqual(['你好'])
    expect(finals).toEqual(['你好'])
  })
})
