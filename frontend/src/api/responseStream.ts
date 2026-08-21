import { normalizeFinalAnswerEnvelope, type TurnMetaEnvelope } from '../utils/streamEnvelope'

export type ReasoningStage = 'ROUTE' | 'REASON' | 'DECIDE' | 'EXECUTE' | 'OBSERVE' | 'REFLECT' | 'PLAN' | 'ACT' | 'DRAFT' | 'CRITIC' | 'REWRITE' | 'FINAL' | 'FUSION' | 'EVIDENCE' | 'STEP'
export type ReasoningStatus = 'pending' | 'running' | 'done'
export type ToolRunStatus = 'idle' | 'running' | 'success' | 'error'

export interface ReasoningStep {
  id: string
  stage: ReasoningStage
  content: string
  status: ReasoningStatus
  node_id?: string
  tool?: {
    name: string
    status: ToolRunStatus
    preview?: string
  }
}

export interface ApprovalRequest {
  id: string
  call_id: string
  tool_name: string
  side_effect: 'write' | 'destructive'
  operation_class?: 'governed_read' | 'write' | 'destructive' | string
  arguments: Record<string, unknown>
  required_approvals?: number
  received_approvals?: number
  current_user_decision?: 'approved' | 'rejected' | null
}

export interface ResponseStreamEvent {
  sequence_number?: number
  type?: string
  data?: any
}

export interface ResponseStreamCallbacks {
  onEvent?: (event: ResponseStreamEvent) => void
  onResponseCreated?: (payload: any) => void
  onReasoningStep?: (step: ReasoningStep) => void
  onThinking?: (payload: any) => void
  onDelta?: (text: string) => void
  onToolCall?: (payload: any) => void
  onToolResult?: (payload: any) => void
  onApprovalRequired?: (approvals: ApprovalRequest[]) => void
  onFinalAnswer?: (envelope: TurnMetaEnvelope) => void | Promise<void>
  onError?: (err: any) => void | Promise<void>
}

const TOOL_PROGRESS: Record<string, { running: string; done: string }> = {
  production: { running: '正在核对生产资产与实时观测', done: '生产证据已返回，正在执行 Critic 校验' },
  config: { running: '正在执行配置的确定性分层校验', done: '配置校验完成，正在核对风险与冲突' },
  data: { running: '正在研究数据口径并生成安全查询草案', done: '数据草案已返回，正在核对治理证据' },
  execute_sql_draft: { running: '正在执行已批准的只读查询', done: '只读查询完成，正在固化结果证据' },
  rag: { running: '正在检索已发布企业知识', done: '知识证据已返回，正在核对引用' },
}

function toolProgress(name: unknown, phase: 'running' | 'done'): string {
  const toolName = String(name || '')
  return TOOL_PROGRESS[toolName]?.[phase]
    || (phase === 'running' ? `正在调用受治理能力：${toolName || '工具'}` : `受治理能力已返回：${toolName || '工具'}`)
}

function governanceProgress(type: string, data: any): Record<string, unknown> | null {
  if (type === 'opentrace.information_sources.enforced') {
    const selected = Array.isArray(data?.selected_sources) ? data.selected_sources.length : 0
    return { ...data, stage: `已执行默认拒绝的信息源策略${selected ? `（选择 ${selected} 类来源）` : ''}` }
  }
  if (type === 'opentrace.information_source.blocked') {
    return { ...data, stage: '未受治理的输入已被信息源策略阻断' }
  }
  if (type === 'opentrace.evidence.gate') {
    const status = String(data?.status || '')
    const stage = status === 'pass'
      ? '证据完整性与 Critic 校验通过'
      : status === 'blocked'
        ? '证据门禁已阻断不可靠结论'
        : '证据仍不完整，回答将明确保留意见'
    return { ...data, stage }
  }
  return null
}

export type ResponseLifecycleState = 'active' | 'requires_action' | 'terminal'

export function advanceResponseLifecycle(
  current: ResponseLifecycleState,
  eventType: string,
): ResponseLifecycleState {
  if (['response.completed', 'response.incomplete', 'response.cancelled', 'response.failed', 'error'].includes(eventType)) {
    return 'terminal'
  }
  if (eventType === 'response.requires_action') return 'requires_action'
  if (
    ['response.created', 'response.queued', 'response.in_progress', 'opentrace.approval.resolved']
      .includes(eventType)
  ) return 'active'
  return current
}

export function trackResponseStream(
  callbacks: ResponseStreamCallbacks,
  startingAfter = -1,
): {
  callbacks: ResponseStreamCallbacks
  cursor: () => number
  lifecycle: () => ResponseLifecycleState
} {
  let cursor = startingAfter
  let lifecycleState: ResponseLifecycleState = 'active'
  return {
    callbacks: {
      ...callbacks,
      onEvent: (event) => {
        if (typeof event.sequence_number === 'number') {
          cursor = Math.max(cursor, event.sequence_number)
        }
        lifecycleState = advanceResponseLifecycle(lifecycleState, String(event.type || ''))
        callbacks.onEvent?.(event)
      },
    },
    cursor: () => cursor,
    lifecycle: () => lifecycleState,
  }
}

function parseSseEventBlock(block: string): ResponseStreamEvent | null {
  const lines = block.split(/\r?\n/).filter(Boolean)
  const dataLines = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart())
  if (!dataLines.length) return null
  const raw = dataLines.join('\n')
  try {
    return JSON.parse(raw)
  } catch {
    return { type: 'message', data: raw }
  }
}

/** SSE parser - exported through client.ts for stream protocol contract tests. */
export async function streamSseResponse(
  res: Response,
  callbacks: ResponseStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const reader = res.body?.getReader()
  if (!reader) throw new Error('Streaming response unavailable')
  const decoder = new TextDecoder()
  let buffer = ''
  let lifecycleState: ResponseLifecycleState = 'active'
  let pendingApprovals: ApprovalRequest[] | null = null

  try {
    while (true) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
      const { done, value } = await reader.read()
      if (done) {
        if (!buffer.trim()) break
        buffer += '\n\n'
      } else {
        buffer += decoder.decode(value, { stream: true })
      }
      let splitIndex: number
      while ((splitIndex = buffer.indexOf('\n\n')) >= 0) {
        const chunk = buffer.slice(0, splitIndex).trim()
        buffer = buffer.slice(splitIndex + 2)
        if (!chunk || chunk.startsWith(':')) continue
        const event = parseSseEventBlock(chunk)
        if (!event) continue
        const type = String(event.type || '')
        const data = event.data ?? {}
        const nextLifecycleState = advanceResponseLifecycle(lifecycleState, type)
        if (type === 'response.requires_action') {
          pendingApprovals = Array.isArray(data.approvals) ? data.approvals : []
        } else if (nextLifecycleState !== lifecycleState && nextLifecycleState !== 'requires_action') {
          pendingApprovals = null
        }
        lifecycleState = nextLifecycleState
        callbacks.onEvent?.(event)

        if (type === 'response.output_text.delta') {
          callbacks.onDelta?.(String(data.delta ?? ''))
          continue
        }
        if (type === 'response.created') {
          callbacks.onResponseCreated?.(data)
          continue
        }
        if (type === 'opentrace.plan.created') {
          const steps = Array.isArray(data?.plan?.steps) ? data.plan.steps : []
          const statuses = (data?.statuses && typeof data.statuses === 'object') ? data.statuses : {}
          for (const step of steps) {
            const durableStatus = String(statuses[String(step.id)] || 'pending')
            callbacks.onReasoningStep?.({
              id: String(step.id),
              node_id: String(step.id),
              stage: 'PLAN',
              content: String(step.objective || ''),
              status: durableStatus === 'running'
                ? 'running'
                : durableStatus === 'completed' || durableStatus === 'failed' || durableStatus === 'skipped'
                  ? 'done'
                  : 'pending',
            })
          }
          continue
        }
        if (type.startsWith('opentrace.plan.step.')) {
          const step = data?.step || {}
          callbacks.onReasoningStep?.({
            id: String(step.id || `plan-${event.sequence_number ?? Date.now()}`),
            node_id: String(step.id || ''),
            stage: 'PLAN',
            content: String(step.objective || ''),
            status: type.endsWith('.started')
              ? 'running'
              : type.endsWith('.deferred')
                ? 'pending'
                : 'done',
          })
          continue
        }
        const governance = governanceProgress(type, data)
        if (governance) {
          callbacks.onThinking?.(governance)
          continue
        }
        if (type.startsWith('opentrace.intent.') || type.startsWith('opentrace.context.') || type.startsWith('opentrace.model.') || type.startsWith('opentrace.capabilities.') || type.startsWith('opentrace.rag.') || type === 'opentrace.plan.replanned') {
          callbacks.onThinking?.(data)
          continue
        }
        if (type === 'response.reasoning_summary_text.done') {
          callbacks.onReasoningStep?.({ id: `summary-${event.sequence_number ?? Date.now()}`, stage: 'FINAL', content: String(data.text ?? ''), status: 'done' })
          continue
        }
        if (type === 'opentrace.tool.started') {
          callbacks.onThinking?.({ ...data, stage: toolProgress(data?.name || data?.tool_name, 'running') })
          callbacks.onToolCall?.(data)
          continue
        }
        if (type === 'opentrace.tool.completed' || type === 'opentrace.tool.failed' || type === 'opentrace.tool.incomplete') {
          callbacks.onThinking?.({
            ...data,
            stage: type.endsWith('.incomplete')
              ? `外部操作结果未知，已停止重试并进入人工核对：${String(data?.name || data?.tool_name || '工具')}`
              : type.endsWith('.failed')
              ? `受治理能力执行失败：${String(data?.name || data?.tool_name || '工具')}`
              : toolProgress(data?.name || data?.tool_name, 'done'),
          })
          callbacks.onToolResult?.(data)
          continue
        }
        if (type === 'response.requires_action') continue
        if (type === 'response.completed' || type === 'response.incomplete') {
          await callbacks.onFinalAnswer?.(normalizeFinalAnswerEnvelope(data))
          continue
        }
        if (type === 'response.cancelled') throw new DOMException('Aborted', 'AbortError')
        if (type === 'error' || type === 'response.failed') {
          throw new Error(data?.message ? String(data.message) : 'Streaming error')
        }
      }
      if (done) break
    }
  } finally {
    reader.releaseLock()
  }
  if (lifecycleState === 'requires_action') {
    callbacks.onApprovalRequired?.(pendingApprovals ?? [])
    return
  }
  if (lifecycleState !== 'terminal') throw new Error('响应流在终态前中断')
}
