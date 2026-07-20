import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiChatStream, streamSseResponse } from '../../api/client'

describe('Responses API stream compatibility', () => {
  afterEach(() => vi.unstubAllGlobals())

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

  it('treats response.incomplete as a terminal answer with resumable details', async () => {
    const finals: string[] = []
    const response = new Response(
      'data: {"sequence_number":9,"type":"response.incomplete","data":{"content":"已达到步骤上限","metadata":{"incomplete_details":{"reason":"max_tool_rounds"}}}}\n\n',
      { headers: { 'content-type': 'text/event-stream' } },
    )

    await streamSseResponse(response, {
      onFinalAnswer: (envelope) => { finals.push(envelope.content) },
    })

    expect(finals).toEqual(['已达到步骤上限'])
  })

  it('surfaces JSON policy errors instead of rendering an empty final answer', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({
        code: 208001,
        message: '该内容有悖聊天宪法，无法进行问答。请调整问题后重试。',
      }),
      { status: 400, headers: { 'content-type': 'application/json' } },
    )))
    const errors: string[] = []
    const finals: string[] = []

    await expect(apiChatStream('token', 'conversation-1', '政治问题', {
      onError: (error) => { errors.push(error.message) },
      onFinalAnswer: (answer) => { finals.push(answer.content) },
    })).rejects.toThrow('该内容有悖聊天宪法')

    expect(errors).toEqual(['该内容有悖聊天宪法，无法进行问答。请调整问题后重试。'])
    expect(finals).toEqual([])
  })
})
