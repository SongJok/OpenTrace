/**
 * Stream Processor - 流式响应处理器
 * 
 * 处理 SSE (Server-Sent Events) 格式的流式响应
 * 参考 ChatGPT 的流式处理机制
 */

export interface StreamEvent {
  type: string
  data: any
  sequence_number?: number
  timestamp?: string
}

export interface ReasoningStep {
  id: string
  type: string
  title: string
  description: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  progress: number
  started_at?: string
  completed_at?: string
  tool_calls?: ToolCallInfo[]
  metadata?: Record<string, unknown>
}

export interface ToolCallInfo {
  tool_name: string
  parameters: Record<string, unknown>
  result_preview?: string
  execution_time_ms: number
}

export interface StreamCallbacks {
  onContent?: (text: string) => void
  onReasoning?: (steps: ReasoningStep[]) => void
  onToolStart?: (toolName: string, params: any) => void
  onToolComplete?: (toolName: string, result: any) => void
  onError?: (error: string) => void
  onComplete?: (metadata: { latency_ms: number }) => void
}

export class StreamProcessor {
  private callbacks: StreamCallbacks
  private buffer: string = ''
  private reasoningSteps: ReasoningStep[] = []
  private contentBuffer: string = ''

  constructor(callbacks: StreamCallbacks) {
    this.callbacks = callbacks
  }

  /**
   * 处理 SSE 数据块
   */
  processChunk(chunk: string): void {
    this.buffer += chunk
    let boundary = this.buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const block = this.buffer.slice(0, boundary)
      this.buffer = this.buffer.slice(boundary + 2)
      const data = block
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n')
      if (data) this.processEvent(data)
      boundary = this.buffer.indexOf('\n\n')
    }
  }

  /** Flush the final unterminated SSE frame when the connection closes. */
  finish(): void {
    if (!this.buffer.trim()) return
    const block = this.buffer
    this.buffer = ''
    const data = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n')
    if (data) this.processEvent(data)
  }

  /**
   * 处理单个事件
   */
  private processEvent(data: string): void {
    try {
      const event: StreamEvent = JSON.parse(data)
      this.handleEvent(event)
    } catch (e) {
      console.error('Failed to parse SSE event:', data, e)
    }
  }

  /**
   * 处理解析后的事件
   */
  private handleEvent(event: StreamEvent): void {
    switch (event.type) {
      case 'content':
      case 'response.output_text.delta':
        this.handleContent(event.data)
        break
      case 'reasoning':
        this.handleReasoning(event.data)
        break
      case 'response.progress':
        this.handleReasoning(event.data)
        break
      case 'tool_start':
      case 'response.output_item.added':
        this.handleToolStart(event.data)
        break
      case 'tool_complete':
      case 'response.output_item.done':
        this.handleToolComplete(event.data)
        break
      case 'error':
      case 'response.failed':
      case 'response.cancelled':
        this.handleError(event.data)
        break
      case 'done':
      case 'response.completed':
        this.handleComplete(event.data)
        break
      default:
        console.warn('Unknown event type:', event.type)
    }
  }

  private handleContent(data: { text?: string; delta?: string }): void {
    const text = data.text || data.delta || ''
    this.contentBuffer += text
    this.callbacks.onContent?.(text)
  }

  private handleReasoning(data: { steps?: ReasoningStep[]; session_id?: string; current_step_id?: string; source_type?: string; content?: string }): void {
    if (data.steps) {
      this.reasoningSteps = data.steps
      this.callbacks.onReasoning?.(this.reasoningSteps)
    } else if (data.source_type || data.content) {
      const step: ReasoningStep = {
        id: String(data.current_step_id || data.source_type || `progress-${this.reasoningSteps.length}`),
        type: String(data.source_type || 'progress'),
        title: String(data.content || data.source_type || '处理中'),
        description: '',
        status: 'in_progress',
        progress: 0,
        tool_calls: [],
      }
      this.reasoningSteps = [...this.reasoningSteps, step]
      this.callbacks.onReasoning?.(this.reasoningSteps)
    }
  }

  private handleToolStart(data: { tool_name?: string; name?: string; parameters?: any; arguments?: any }): void {
    const name = data.tool_name || data.name
    if (name) {
      this.callbacks.onToolStart?.(name, data.parameters ?? data.arguments)
    }
  }

  private handleToolComplete(data: { tool_name?: string; name?: string; result?: any; output?: any }): void {
    const name = data.tool_name || data.name
    if (name) {
      this.callbacks.onToolComplete?.(name, data.result ?? data.output)
    }
  }

  private handleError(data: { message?: string }): void {
    const error = data.message || 'Unknown error'
    this.callbacks.onError?.(error)
  }

  private handleComplete(data: { latency_ms?: number; complete?: boolean; metadata?: { latency_ms?: number } }): void {
    this.callbacks.onComplete?.({
      latency_ms: data.latency_ms || data.metadata?.latency_ms || 0
    })
  }

  /**
   * 获取累积的内容
   */
  getContent(): string {
    return this.contentBuffer
  }

  /**
   * 获取推理步骤
   */
  getReasoningSteps(): ReasoningStep[] {
    return [...this.reasoningSteps]
  }

  /**
   * 重置处理器
   */
  reset(): void {
    this.buffer = ''
    this.reasoningSteps = []
    this.contentBuffer = ''
  }
}

/**
 * 创建 SSE EventSource 的辅助函数
 */
export function createSSEConnection(
  url: string,
  callbacks: StreamCallbacks,
  options?: { headers?: Record<string, string> }
): { close: () => void } {
  const processor = new StreamProcessor(callbacks)
  
  // 使用 fetch + ReadableStream API
  const abortController = new AbortController()
  
  fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream',
      ...options?.headers
    },
    signal: abortController.signal
  }).then(async (response) => {
    if (!response.body) {
      throw new Error('No response body')
    }
    
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    
    while (true) {
      const { done, value } = await reader.read()
      
      if (done) {
        processor.finish()
        break
      }
      
      const chunk = decoder.decode(value, { stream: true })
      processor.processChunk(chunk)
    }
  }).catch((error) => {
    if (error.name !== 'AbortError') {
      console.error('SSE connection error:', error)
      callbacks.onError?.(error.message)
    }
  })
  
  return {
    close: () => {
      abortController.abort()
    }
  }
}

/**
 * 解析 SSE 响应为消息列表
 */
export async function parseSSEResponse(
  response: Response
): Promise<{ content: string; reasoningSteps: ReasoningStep[] }> {
  const content: string[] = []
  const reasoningSteps: ReasoningStep[] = []
  
  if (!response.body) {
    return { content: '', reasoningSteps: [] }
  }
  
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  
  while (true) {
    const { done, value } = await reader.read()
    
    if (done) {
      break
    }
    
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6))
          
          if (event.type === 'content' && event.data?.text) {
            content.push(event.data.text)
          } else if (event.type === 'reasoning' && event.data?.steps) {
            reasoningSteps.length = 0
            reasoningSteps.push(...event.data.steps)
          }
        } catch {
          // 忽略解析错误
        }
      }
    }
  }
  
  return {
    content: content.join(''),
    reasoningSteps
  }
}
