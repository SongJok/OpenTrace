import { create } from 'zustand'
import type { ReasoningStep, ToolRunStatus } from '../api/client'

export interface ExecutionGraphNode {
  id: string
  type: string
  stage: string
  status: string
  input?: Record<string, unknown>
  output?: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export interface ExecutionGraphEdge {
  source: string
  target: string
}

export interface ExecutionGraphData {
  nodes: ExecutionGraphNode[]
  edges: ExecutionGraphEdge[]
  state?: Record<string, unknown>
}

export type MessageStatus = 'streaming' | 'done'

export interface MessageAttachment {
  id: string
  filename: string
  file_size: number
  file_extension?: string
  mime_type?: string
  content_summary?: string
}

export interface CitationItem {
  id: number
  title: string
  url: string
  snippet?: string
}

export interface MessageAnnotation {
  id: string
  text: string
  annotation?: {
    level: string
    source_type: string
    confidence: number
    caveats?: string[]
    citations?: Array<{ id: string; source_name: string; snippet?: string; url?: string }>
  } | null
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  status: MessageStatus
  streamText: string
  finalText: string
  decision_type?: string
  validation_score?: number
  reasoning_steps?: ReasoningStep[]
  execution_graph?: ExecutionGraphData | null
  citations?: CitationItem[]
  annotations?: MessageAnnotation[]
  attachments?: MessageAttachment[]
}

export interface Conversation {
  id: string
  title: string
  turn_count: number
  created_at: string
  last_active: string
  archived_at?: string | null
}

interface ChatState {
  conversations: Conversation[]
  activeId: string | null
  messages: Record<string, Message[]>
  streaming: boolean
  reasoningSteps: Record<string, ReasoningStep[]>
  executionGraphs: Record<string, ExecutionGraphData | null>
  activeReasoningMessageId: Record<string, string | null>
  setConversations: (c: Conversation[]) => void
  setActiveId: (id: string | null) => void
  addConversation: (c: Conversation) => void
  removeConversation: (id: string) => void
  setMessages: (id: string, msgs: any[]) => void
  appendUserMessage: (id: string, msg: { id: string; content: string; attachments?: MessageAttachment[] }) => void
  appendAssistantStreamingMessage: (id: string, msg: { id: string }) => void
  setLastAssistantCitations: (id: string, citations: CitationItem[]) => void
  setLastAssistantAnnotations: (id: string, annotations: MessageAnnotation[]) => void
  appendStreamingChunk: (id: string, chunk: string) => void
  appendThinking: (id: string, text: string) => void
  finishLastAssistantMessage: (id: string, finalText: string) => void
  stopLastAssistantMessage: (id: string) => void
  failLastAssistantMessage: (id: string, text: string) => void
  setStreaming: (v: boolean) => void
  updateTitle: (id: string, title: string) => void
  updateConversationMeta: (conversation: Partial<Conversation> & { id: string }) => void
  resetReasoning: (sessionId: string, messageId: string) => void
  addReasoningStep: (sessionId: string, step: ReasoningStep) => void
  updateToolStatus: (sessionId: string, payload: { tool_name: string; status: ToolRunStatus | string; node_id?: string; preview?: string }) => void
  updateToolResult: (sessionId: string, payload: { tool_name?: string; preview: string; node_id?: string }) => void
  updateDagNodeEvent: (sessionId: string, payload: { node_id: string; agent_type: string; status: string; preview?: string; depends_on?: string[]; duration_ms?: number }) => void
  markDagNodeRunning: (sessionId: string, nodeId: string) => void
  setExecutionGraph: (sessionId: string, messageId: string, graph: ExecutionGraphData | null) => void
  upsertExecutionGraphNode: (sessionId: string, messageId: string, node: ExecutionGraphNode) => void
  getReasoningStepsForMessage: (sessionId: string, messageId: string) => ReasoningStep[]
  getExecutionGraphForMessage: (sessionId: string, messageId: string) => ExecutionGraphData | null
}

function normalizeMessageText(input: unknown): string {
  if (typeof input === 'string') return input
  if (input == null) return ''
  if (typeof input === 'object' && !Array.isArray(input)) {
    const obj = input as Record<string, unknown>
    // Card-rendered types — handled elsewhere, no raw text
    if (obj.type === 'table' || obj.type === 'time' || obj.type === 'weather') return ''
    if (obj.type === 'sql' || obj.type === 'tool' || obj.type === 'turn' || obj.type === 'agent_result') return ''
    if (typeof obj.content === 'string') return obj.content
    if (typeof obj.text === 'string') return obj.text
    if (typeof obj.answer === 'string') return obj.answer
    if (typeof obj.summary === 'string') return obj.summary
  }
  // Never render raw JSON
  return ''
}

function asDoneMessage(raw: any): Message {
  const text = normalizeMessageText(raw?.content ?? raw?.finalText ?? '')
  const reasoningSteps = Array.isArray(raw?.reasoning_steps) ? raw.reasoning_steps : undefined
  const executionGraph = raw?.execution_graph && typeof raw.execution_graph === 'object'
    ? (raw.execution_graph as ExecutionGraphData)
    : null
  const attachments = Array.isArray(raw?.attachments) ? raw.attachments as MessageAttachment[] : undefined
  return {
    id: String(raw?.id ?? `m_${Date.now()}`),
    role: (raw?.role ?? 'assistant') as Message['role'],
    status: 'done',
    streamText: '',
    finalText: text,
    decision_type: raw?.decision_type,
    validation_score: raw?.validation_score,
    reasoning_steps: reasoningSteps,
    execution_graph: executionGraph,
    attachments,
  }
}

function normalizeToolStatus(status: string): ToolRunStatus {
  if (status === 'running') return 'running'
  if (status === 'success') return 'success'
  if (status === 'error') return 'error'
  return 'idle'
}

function reasoningKey(sessionId: string, messageId: string | null) {
  return `${sessionId}:${messageId || 'none'}`
}

export const useChatStore = create<ChatState>()((set, get) => ({
  conversations: [],
  activeId: null,
  messages: {},
  streaming: false,
  reasoningSteps: {},
  executionGraphs: {},
  activeReasoningMessageId: {},

  setConversations: (c) => set({ conversations: c }),
  setActiveId: (id) => set({ activeId: id }),
  addConversation: (c) => set((s) => ({ conversations: [c, ...s.conversations] })),
  removeConversation: (id) =>
    set((s) => ({
      conversations: s.conversations.filter((c) => c.id !== id),
      activeId: s.activeId === id ? null : s.activeId,
    })),
  setMessages: (id, msgs) =>
    set((s) => {
      const normalized = (msgs ?? []).map(asDoneMessage)
      const nextReasoningSteps = { ...s.reasoningSteps }
      const nextExecutionGraphs = { ...s.executionGraphs }
      for (const msg of normalized) {
        if (msg.role !== 'assistant') continue
        nextReasoningSteps[reasoningKey(id, msg.id)] = msg.reasoning_steps ?? []
        nextExecutionGraphs[reasoningKey(id, msg.id)] = msg.execution_graph ?? null
      }
      return {
        messages: { ...s.messages, [id]: normalized },
        reasoningSteps: nextReasoningSteps,
        executionGraphs: nextExecutionGraphs,
      }
    }),

  appendUserMessage: (id, msg) =>
    set((s) => ({
      messages: {
        ...s.messages,
        [id]: [
          ...(s.messages[id] ?? []),
          {
            id: msg.id,
            role: 'user' as const,
            status: 'done' as const,
            streamText: '',
            finalText: msg.content,
            attachments: msg.attachments ?? undefined,
          },
        ],
      },
    })),

  appendAssistantStreamingMessage: (id, msg) =>
    set((s) => ({
      messages: {
        ...s.messages,
        [id]: [
          ...(s.messages[id] ?? []),
          {
            id: msg.id,
            role: 'assistant',
            status: 'streaming',
            streamText: '',
            finalText: '',
          },
        ],
      },
      activeReasoningMessageId: { ...s.activeReasoningMessageId, [id]: msg.id },
      streaming: true,
    })),

  appendStreamingChunk: (id, chunk) =>
    set((s) => {
      const list = [...(s.messages[id] ?? [])]
      if (!list.length) return {}
      const idx = list.length - 1
      const last = list[idx]
      if (last.role !== 'assistant' || last.status !== 'streaming') return {}
      list[idx] = { ...last, streamText: last.streamText + chunk }
      return { messages: { ...s.messages, [id]: list } }
    }),

  appendThinking: (id, text) =>
    set((s) => {
      const list = [...(s.messages[id] ?? [])]
      if (!list.length) return {}
      const idx = list.length - 1
      const last = list[idx]
      if (last.role !== 'assistant' || last.status !== 'streaming') return {}
      list[idx] = {
        ...last,
        streamText: last.streamText ? `${last.streamText}\n${text}` : text,
      }
      return { messages: { ...s.messages, [id]: list } }
    }),

  finishLastAssistantMessage: (id, finalText) =>
    set((s) => {
      const list = [...(s.messages[id] ?? [])]
      if (!list.length) return { streaming: false }
      const idx = list.length - 1
      const last = list[idx]
      if (last.role !== 'assistant') return { streaming: false }
      list[idx] = {
        ...last,
        status: 'done',
        finalText: normalizeMessageText(finalText),
        streamText: '',
      }
      return { messages: { ...s.messages, [id]: list }, streaming: false }
    }),

  setLastAssistantCitations: (id, citations) =>
    set((s) => {
      const list = [...(s.messages[id] ?? [])]
      if (!list.length) return {}
      const idx = list.length - 1
      const last = list[idx]
      if (last.role !== 'assistant') return {}
      list[idx] = { ...last, citations: citations ?? [] }
      return { messages: { ...s.messages, [id]: list } }
    }),

  setLastAssistantAnnotations: (id, annotations) =>
    set((s) => {
      const list = [...(s.messages[id] ?? [])]
      if (!list.length) return {}
      const idx = list.length - 1
      const last = list[idx]
      if (last.role !== 'assistant') return {}
      list[idx] = { ...last, annotations: annotations ?? [] }
      return { messages: { ...s.messages, [id]: list } }
    }),

  stopLastAssistantMessage: (id) =>
    set((s) => {
      const list = [...(s.messages[id] ?? [])]
      if (!list.length) return { streaming: false }
      const idx = list.length - 1
      const last = list[idx]
      if (last.role !== 'assistant' || last.status !== 'streaming') return { streaming: false }
      list[idx] = {
        ...last,
        status: 'done',
        finalText: last.streamText,
        streamText: '',
      }
      return { messages: { ...s.messages, [id]: list }, streaming: false }
    }),

  failLastAssistantMessage: (id, text) =>
    set((s) => {
      const list = [...(s.messages[id] ?? [])]
      if (!list.length) return { streaming: false }
      const idx = list.length - 1
      const last = list[idx]
      if (last.role !== 'assistant') return { streaming: false }
      list[idx] = {
        ...last,
        status: 'done',
        finalText: text,
        streamText: '',
      }
      return { messages: { ...s.messages, [id]: list }, streaming: false }
    }),

  setStreaming: (v) => set({ streaming: v }),
  updateTitle: (id, title) =>
    set((s) => ({
      conversations: s.conversations.map((c) => (c.id === id ? { ...c, title } : c)),
    })),

  updateConversationMeta: (conversation) =>
    set((s) => ({
      conversations: s.conversations.map((item) =>
        item.id === conversation.id ? { ...item, ...conversation } : item
      ),
    })),

  resetReasoning: (sessionId, messageId) =>
    set((s) => ({
      reasoningSteps: { ...s.reasoningSteps, [reasoningKey(sessionId, messageId)]: [] },
      executionGraphs: { ...s.executionGraphs, [reasoningKey(sessionId, messageId)]: null },
      activeReasoningMessageId: { ...s.activeReasoningMessageId, [sessionId]: messageId },
    })),

  addReasoningStep: (sessionId, step) =>
    set((s) => {
      const messageId = s.activeReasoningMessageId[sessionId] ?? null
      const key = reasoningKey(sessionId, messageId)
      const existing = s.reasoningSteps[key] ?? []
      const next = [...existing]
      const idx = next.findIndex((item) => item.id === step.id)
      const normalized: ReasoningStep = {
        ...step,
        status: step.status ?? 'running',
      }
      if (idx >= 0) next[idx] = { ...next[idx], ...normalized }
      else next.push(normalized)
      return { reasoningSteps: { ...s.reasoningSteps, [key]: next } }
    }),

  updateToolStatus: (sessionId, payload) =>
    set((s) => {
      const messageId = s.activeReasoningMessageId[sessionId] ?? null
      const key = reasoningKey(sessionId, messageId)
      const existing = [...(s.reasoningSteps[key] ?? [])]
      if (!existing.length) return {}
      const targetIndex = payload.node_id
        ? existing.findIndex((step) => step.node_id === payload.node_id)
        : existing.length - 1
      if (targetIndex < 0) return {}
      const target = existing[targetIndex]
      existing[targetIndex] = {
        ...target,
        status: payload.status === 'running' ? 'running' : 'done',
        tool: {
          name: payload.tool_name,
          status: normalizeToolStatus(payload.status),
          preview: payload.preview || target.tool?.preview,
        },
      }
      return { reasoningSteps: { ...s.reasoningSteps, [key]: existing } }
    }),

  updateToolResult: (sessionId, payload) =>
    set((s) => {
      const messageId = s.activeReasoningMessageId[sessionId] ?? null
      const key = reasoningKey(sessionId, messageId)
      const existing = [...(s.reasoningSteps[key] ?? [])]
      if (!existing.length) return {}
      const targetIndex = payload.node_id
        ? existing.findIndex((step) => step.node_id === payload.node_id)
        : existing.length - 1
      if (targetIndex < 0) return {}
      const target = existing[targetIndex]
      existing[targetIndex] = {
        ...target,
        status: 'done',
        content: payload.preview || target.content,
        tool: target.tool
          ? { ...target.tool, preview: payload.preview, status: 'success' }
          : payload.tool_name
            ? { name: payload.tool_name, preview: payload.preview, status: 'success' }
            : undefined,
      }
      return { reasoningSteps: { ...s.reasoningSteps, [key]: existing } }
    }),

  updateDagNodeEvent: (sessionId, payload) =>
    set((s) => {
      const messageId = s.activeReasoningMessageId[sessionId] ?? null
      if (!messageId) return {}
      const key = reasoningKey(sessionId, messageId)
      const graph = s.executionGraphs[key] ?? { nodes: [], edges: [], state: {} }
      const nodes = [...(graph.nodes ?? [])]
      const idx = nodes.findIndex((n) => n.id === payload.node_id)
      const nextNode: ExecutionGraphNode = {
        id: payload.node_id,
        type: 'agent_call',
        stage: 'AGENT',
        status: payload.status.toUpperCase(),
        metadata: {
          agent_type: payload.agent_type,
          preview: payload.preview,
          depends_on: payload.depends_on || [],
          duration_ms: payload.duration_ms,
        },
      }
      if (idx >= 0) nodes[idx] = { ...nodes[idx], ...nextNode }
      else nodes.push(nextNode)
      return { executionGraphs: { ...s.executionGraphs, [key]: { ...graph, nodes } } }
    }),

  setExecutionGraph: (sessionId, messageId, graph) =>
    set((s) => ({
      executionGraphs: { ...s.executionGraphs, [reasoningKey(sessionId, messageId)]: graph },
    })),

  upsertExecutionGraphNode: (sessionId, messageId, node) =>
    set((s) => {
      const key = reasoningKey(sessionId, messageId)
      const graph = s.executionGraphs[key] ?? { nodes: [], edges: [], state: {} }
      const nodes = [...(graph.nodes ?? [])]
      const idx = nodes.findIndex((n) => n.id === node.id)
      if (idx >= 0) nodes[idx] = { ...nodes[idx], ...node }
      else nodes.push(node)
      return { executionGraphs: { ...s.executionGraphs, [key]: { ...graph, nodes } } }
    }),

  markDagNodeRunning: (sessionId, nodeId) =>
    set((s) => {
      const messageId = s.activeReasoningMessageId[sessionId] ?? null
      if (!messageId) return {}
      const key = reasoningKey(sessionId, messageId)
      const graph = s.executionGraphs[key] ?? { nodes: [], edges: [], state: {} }
      const nodes = [...(graph.nodes ?? [])]
      const idx = nodes.findIndex((n) => n.id === nodeId)
      if (idx >= 0) nodes[idx] = { ...nodes[idx], status: 'RUNNING' }
      else nodes.push({ id: nodeId, type: 'agent_call', stage: 'AGENT', status: 'RUNNING' })
      return { executionGraphs: { ...s.executionGraphs, [key]: { ...graph, nodes } } }
    }),

  getReasoningStepsForMessage: (sessionId, messageId) => {
    const state = get()
    return state.reasoningSteps[reasoningKey(sessionId, messageId)] ?? []
  },

  getExecutionGraphForMessage: (sessionId, messageId) => {
    const state = get()
    return state.executionGraphs[reasoningKey(sessionId, messageId)] ?? null
  },
}))
