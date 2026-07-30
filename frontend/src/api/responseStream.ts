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
  arguments: Record<string, unknown>
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
        if (type.startsWith('opentrace.intent.') || type.startsWith('opentrace.context.') || type.startsWith('opentrace.model.') || type.startsWith('opentrace.capabilities.') || type === 'opentrace.plan.replanned') {
          callbacks.onThinking?.(data)
          continue
        }
        if (type === 'response.reasoning_summary_text.done') {
          callbacks.onReasoningStep?.({ id: `summary-${event.sequence_number ?? Date.now()}`, stage: 'FINAL', content: String(data.text ?? ''), status: 'done' })
          continue
        }
        if (type === 'opentrace.tool.started') {
          callbacks.onToolCall?.(data)
          continue
        }
        if (type === 'opentrace.tool.completed' || type === 'opentrace.tool.failed') {
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
