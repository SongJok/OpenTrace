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

  it('projects durable execution-plan events into stable reasoning steps', async () => {
    const steps: Array<{ id: string; status: string; content: string }> = []
    const thinking: Array<Record<string, unknown>> = []
    const response = new Response(
      [
        'data: {"sequence_number":2,"type":"opentrace.plan.created","data":{"plan":{"steps":[{"id":"step-1","objective":"检索证据"},{"id":"step-2","objective":"综合答案"}]},"statuses":{"step-1":"pending","step-2":"completed"}}}\n\n',
        'data: {"sequence_number":3,"type":"opentrace.plan.step.started","data":{"step":{"id":"step-1","objective":"检索证据"}}}\n\n',
        'data: {"sequence_number":4,"type":"opentrace.plan.step.completed","data":{"step":{"id":"step-1","objective":"检索证据"}}}\n\n',
        'data: {"sequence_number":5,"type":"opentrace.plan.replanned","data":{"reason":"tool_failed","attempt":1}}\n\n',
      ].join(''),
      { headers: { 'content-type': 'text/event-stream' } },
    )

    await streamSseResponse(response, {
      onReasoningStep: (step) => { steps.push(step) },
      onThinking: (payload) => { thinking.push(payload) },
    })

    expect(steps).toEqual([
      { id: 'step-1', node_id: 'step-1', stage: 'PLAN', content: '检索证据', status: 'pending' },
      { id: 'step-2', node_id: 'step-2', stage: 'PLAN', content: '综合答案', status: 'done' },
      { id: 'step-1', node_id: 'step-1', stage: 'PLAN', content: '检索证据', status: 'running' },
      { id: 'step-1', node_id: 'step-1', stage: 'PLAN', content: '检索证据', status: 'done' },
    ])
    expect(thinking).toEqual([{ reason: 'tool_failed', attempt: 1 }])
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

  it('sends the governed Project and enterprise data-source scope', async () => {
    let body: any
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, init) => {
      body = JSON.parse(String(init?.body || '{}'))
      return Promise.resolve(new Response(
        'data: {"sequence_number":1,"type":"response.completed","data":{"content":"完成"}}\n\n',
        { headers: { 'content-type': 'text/event-stream' } },
      ))
    }))

    await apiChatStream('token', 'conversation-1', '结合数据库和知识库分析风险', {}, false, undefined, 'deep', {
      project_id: 'project-1',
      data_source_ids: ['doris-1'],
    })

    expect(body.opentrace.project_id).toBe('project-1')
    expect(body.opentrace.data_source_ids).toEqual(['doris-1'])
  })
})
