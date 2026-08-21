import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  apiChatStream,
  apiResolveResponseApproval,
  apiResumeResponseWithRetry,
  streamSseResponse,
} from '../../api/client'

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

  it('surfaces RAG routing events as visible thinking stages', async () => {
    const stages: string[] = []
    const response = new Response(
      [
        'data: {"sequence_number":1,"type":"opentrace.rag.routing","data":{"stage":"知识库检索","required":true}}\n\n',
        'data: {"sequence_number":2,"type":"response.completed","data":{"content":"完成"}}\n\n',
      ].join(''),
      { headers: { 'content-type': 'text/event-stream' } },
    )

    await streamSseResponse(response, {
      onThinking: (payload) => { stages.push(String(payload.stage || '')) },
    })

    expect(stages).toEqual(['知识库检索'])
  })

  it('projects production governance and evidence gate events into public progress', async () => {
    const stages: string[] = []
    const response = new Response(
      [
        'data: {"sequence_number":1,"type":"opentrace.information_sources.enforced","data":{"mode":"deny_by_default","selected_sources":["production","config"]}}\n\n',
        'data: {"sequence_number":2,"type":"opentrace.tool.started","data":{"name":"production","call_id":"call-1"}}\n\n',
        'data: {"sequence_number":3,"type":"opentrace.tool.completed","data":{"name":"production","status":"completed"}}\n\n',
        'data: {"sequence_number":4,"type":"opentrace.evidence.gate","data":{"status":"blocked","missing":["live_observation"]}}\n\n',
        'data: {"sequence_number":5,"type":"response.completed","data":{"content":"已阻断"}}\n\n',
      ].join(''),
      { headers: { 'content-type': 'text/event-stream' } },
    )

    await streamSseResponse(response, {
      onThinking: (payload) => { stages.push(String(payload.stage || '')) },
    })

    expect(stages).toEqual([
      '已执行默认拒绝的信息源策略（选择 2 类来源）',
      '正在核对生产资产与实时观测',
      '生产证据已返回，正在执行 Critic 校验',
      '证据门禁已阻断不可靠结论',
    ])
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

  it('treats requires_action as a durable stream boundary', async () => {
    const approvals: unknown[][] = []
    const response = new Response(
      'data: {"sequence_number":8,"type":"response.requires_action","data":{"approvals":[{"id":"approval-1","tool_name":"create_calendar_event"}]}}\n\n',
      { headers: { 'content-type': 'text/event-stream' } },
    )

    await streamSseResponse(response, {
      onApprovalRequired: (items) => { approvals.push(items) },
    })

    expect(approvals).toHaveLength(1)
  })

  it('rejects a stream that ends before a terminal event', async () => {
    const response = new Response(
      'data: {"sequence_number":1,"type":"response.created","data":{"response_id":"resp-1"}}\n\n',
      { headers: { 'content-type': 'text/event-stream' } },
    )

    await expect(streamSseResponse(response, {})).rejects.toThrow('响应流在终态前中断')
  })

  it('rejects HTTP 200 approval business errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ approved: false, error: 'approval not found' }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    )))

    await expect(apiResolveResponseApproval('token', 'resp-1', 'approval-1', true))
      .rejects.toThrow('approval not found')
  })

  it('resumes an interrupted approval stream from the last observed sequence', async () => {
    const urls: string[] = []
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
      urls.push(String(url))
      if (urls.length === 1) {
        return Promise.resolve(new Response(
          'data: {"sequence_number":12,"type":"opentrace.tool.started","data":{"name":"create_calendar_event"}}\n\n',
          { headers: { 'content-type': 'text/event-stream' } },
        ))
      }
      return Promise.resolve(new Response(
        'data: {"sequence_number":13,"type":"response.completed","data":{"content":"日程已创建"}}\n\n',
        { headers: { 'content-type': 'text/event-stream' } },
      ))
    }))

    await apiResumeResponseWithRetry('token', 'resp-1', 10)

    expect(urls).toEqual([
      '/api/v2/responses/resp-1?stream=true&starting_after=10',
      '/api/v2/responses/resp-1?stream=true&starting_after=12',
    ])
  })

  it('does not treat a historical approval boundary as terminal after execution resumes', async () => {
    const urls: string[] = []
    const approvals: unknown[][] = []
    const finals: string[] = []
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
      urls.push(String(url))
      if (urls.length === 1) {
        return Promise.resolve(new Response([
          'data: {"sequence_number":8,"type":"response.requires_action","data":{"approvals":[{"id":"approval-1"}]}}\n\n',
          'data: {"sequence_number":9,"type":"response.in_progress","data":{"status":"in_progress"}}\n\n',
        ].join(''), { headers: { 'content-type': 'text/event-stream' } }))
      }
      return Promise.resolve(new Response(
        'data: {"sequence_number":10,"type":"response.completed","data":{"content":"日程已创建"}}\n\n',
        { headers: { 'content-type': 'text/event-stream' } },
      ))
    }))

    await apiResumeResponseWithRetry('token', 'resp-1', -1, {
      onApprovalRequired: (items) => { approvals.push(items) },
      onFinalAnswer: (answer) => { finals.push(answer.content) },
    })

    expect(urls).toEqual([
      '/api/v2/responses/resp-1?stream=true&starting_after=-1',
      '/api/v2/responses/resp-1?stream=true&starting_after=9',
    ])
    expect(approvals).toEqual([])
    expect(finals).toEqual(['日程已创建'])
  })

  it('clears a historical approval boundary when approval.resolved precedes an interrupted resume', async () => {
    const urls: string[] = []
    const finals: string[] = []
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
      urls.push(String(url))
      if (urls.length === 1) {
        return Promise.resolve(new Response([
          'data: {"sequence_number":8,"type":"response.requires_action","data":{"approvals":[{"id":"approval-1"}]}}\n\n',
          'data: {"sequence_number":9,"type":"opentrace.approval.resolved","data":{"approval_id":"approval-1","approved":true}}\n\n',
        ].join(''), { headers: { 'content-type': 'text/event-stream' } }))
      }
      return Promise.resolve(new Response(
        'data: {"sequence_number":10,"type":"response.completed","data":{"content":"日程已创建"}}\n\n',
        { headers: { 'content-type': 'text/event-stream' } },
      ))
    }))

    await apiResumeResponseWithRetry('token', 'resp-1', -1, {
      onFinalAnswer: (answer) => { finals.push(answer.content) },
    })

    expect(urls).toEqual([
      '/api/v2/responses/resp-1?stream=true&starting_after=-1',
      '/api/v2/responses/resp-1?stream=true&starting_after=9',
    ])
    expect(finals).toEqual(['日程已创建'])
  })

  it('projects durable execution-plan events into stable reasoning steps', async () => {
    const steps: Array<{ id: string; status: string; content: string }> = []
    const thinking: Array<Record<string, unknown>> = []
    const response = new Response(
      [
        'data: {"sequence_number":2,"type":"opentrace.plan.created","data":{"plan":{"steps":[{"id":"step-1","objective":"检索证据"},{"id":"step-2","objective":"综合答案"},{"id":"step-3","objective":"未使用的候选能力"}]},"statuses":{"step-1":"pending","step-2":"completed","step-3":"skipped"}}}\n\n',
        'data: {"sequence_number":3,"type":"opentrace.plan.step.started","data":{"step":{"id":"step-1","objective":"检索证据"}}}\n\n',
        'data: {"sequence_number":4,"type":"opentrace.plan.step.completed","data":{"step":{"id":"step-1","objective":"检索证据"}}}\n\n',
        'data: {"sequence_number":5,"type":"opentrace.plan.replanned","data":{"reason":"tool_failed","attempt":1}}\n\n',
        'data: {"sequence_number":6,"type":"response.completed","data":{"content":"完成"}}\n\n',
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
      { id: 'step-3', node_id: 'step-3', stage: 'PLAN', content: '未使用的候选能力', status: 'done' },
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

  it('does not allow the chat client to bind an enterprise data source', async () => {
    let body: any
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, init) => {
      body = JSON.parse(String(init?.body || '{}'))
      return Promise.resolve(new Response(
        'data: {"sequence_number":1,"type":"response.completed","data":{"content":"完成"}}\n\n',
        { headers: { 'content-type': 'text/event-stream' } },
      ))
    }))

    await apiChatStream('token', 'conversation-1', '结合数据库和知识库分析风险', {}, false, undefined, 'deep', {
      data_source_ids: ['doris-1'],
    })

    expect(body.opentrace).not.toHaveProperty('data_source_ids')
    expect(body.opentrace.knowledge_mode).toBe('auto')
  })

  it('maps /rag to the Responses knowledge_mode contract', async () => {
    let body: any
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, init) => {
      body = JSON.parse(String(init?.body || '{}'))
      return Promise.resolve(new Response(
        'data: {"sequence_number":1,"type":"response.completed","data":{"content":"完成"}}\n\n',
        { headers: { 'content-type': 'text/event-stream' } },
      ))
    }))

    await apiChatStream('token', 'conversation-1', '/rag 请假流程是什么', {})

    expect(body.opentrace.knowledge_mode).toBe('required')
    expect(body.input).toBe('/rag 请假流程是什么')
  })
})
