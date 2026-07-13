/** Normalize backend final_answer / sync chat payloads (enterprise + governance). */

export interface TurnMetaEnvelope {
  content: string
  execution_graph: Record<string, unknown> | null
  citations: unknown[]
  annotations: unknown[]
  metadata: Record<string, unknown>
  control_plane?: Record<string, unknown>
  capabilities_used?: string[]
  prompt_tokens?: number
  completion_tokens?: number
  enterprise_telemetry?: Record<string, unknown>
  result_refs?: unknown[]
  needs_clarification?: boolean
  clarification?: Record<string, unknown>
  turn_outcome?: string
  governance_warnings?: string[]
  evidence_refs?: unknown[]
  knowledge_operations?: unknown[]
  confidence?: number
  confidence_level?: string
  uncertainty?: string[]
  trace_id?: string
}

export function normalizeFinalAnswerEnvelope(data: unknown): TurnMetaEnvelope {
  const d = (data && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const meta = (d.metadata && typeof d.metadata === 'object' ? d.metadata : {}) as Record<string, unknown>
  const obs = (meta.semantic_observability && typeof meta.semantic_observability === 'object'
    ? meta.semantic_observability
  : {}) as Record<string, unknown>

  const content = String(d.content ?? d.answer ?? '')
  const execution_graph =
    d.execution_graph && typeof d.execution_graph === 'object'
      ? (d.execution_graph as Record<string, unknown>)
      : null

  const control_plane =
    (d.control_plane as Record<string, unknown> | undefined) ??
    (meta.control_plane as Record<string, unknown> | undefined)

  const enterprise_telemetry =
    (d.enterprise_telemetry as Record<string, unknown> | undefined) ??
    (obs.enterprise_telemetry as Record<string, unknown> | undefined)

  const capabilities_used = (d.capabilities_used as string[] | undefined) ??
    (meta.capabilities_used as string[] | undefined)

  const prompt_tokens =
    typeof d.prompt_tokens === 'number'
      ? d.prompt_tokens
      : typeof meta.prompt_tokens === 'number'
        ? meta.prompt_tokens
        : undefined

  const completion_tokens =
    typeof d.completion_tokens === 'number'
      ? d.completion_tokens
      : typeof meta.completion_tokens === 'number'
        ? meta.completion_tokens
        : undefined

  const result_refs = (d.result_refs as unknown[] | undefined) ?? (meta.result_refs as unknown[] | undefined)
  const evidence_refs = (d.evidence_refs as unknown[] | undefined) ?? (meta.evidence_refs as unknown[] | undefined)
  const knowledge_operations = (d.knowledge_operations as unknown[] | undefined) ?? (meta.knowledge_operations as unknown[] | undefined)

  const needs_clarification = Boolean(
    d.needs_clarification ?? meta.needs_clarification ?? meta.turn_outcome === 'clarification',
  )

  const clarification = (d.clarification ?? meta.clarification) as Record<string, unknown> | undefined

  const turn_outcome = String(
    d.turn_outcome ?? meta.turn_outcome ?? (needs_clarification ? 'clarification' : ''),
  )

  const degraded = meta.runtime_degraded
  const governance_warnings: string[] = []
  if (Array.isArray(degraded)) {
    for (const item of degraded) {
      if (item && typeof item === 'object' && (item as { subsystem?: string }).subsystem) {
        governance_warnings.push(String((item as { subsystem: string }).subsystem))
      }
    }
  }
  if (control_plane && control_plane.allowed === false) {
    governance_warnings.push('control_plane_denied')
  }

  return {
    content,
    execution_graph,
    citations: Array.isArray(d.citations) ? d.citations : [],
    annotations: Array.isArray(d.annotations) ? d.annotations : [],
    metadata: { ...meta },
    control_plane,
    capabilities_used,
    prompt_tokens,
    completion_tokens,
    enterprise_telemetry,
    result_refs,
    needs_clarification,
    clarification,
    turn_outcome: turn_outcome || undefined,
    governance_warnings,
    evidence_refs,
    knowledge_operations,
    confidence: typeof d.confidence === 'number' ? d.confidence : typeof meta.confidence === 'number' ? meta.confidence : undefined,
    confidence_level: typeof d.confidence_level === 'string' ? d.confidence_level : typeof meta.confidence_level === 'string' ? meta.confidence_level : undefined,
    uncertainty: Array.isArray(d.uncertainty) ? d.uncertainty as string[] : Array.isArray(meta.uncertainty) ? meta.uncertainty as string[] : [],
    trace_id: typeof d.trace_id === 'string' ? d.trace_id : typeof meta.trace_id === 'string' ? meta.trace_id : undefined,
  }
}
