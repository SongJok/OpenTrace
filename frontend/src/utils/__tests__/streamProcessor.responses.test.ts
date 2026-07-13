import { describe, expect, it, vi } from 'vitest'
import { StreamProcessor } from '../streamProcessor'

describe('StreamProcessor Responses events', () => {
  it('buffers partial SSE frames and consumes canonical text and completion events', () => {
    const onContent = vi.fn()
    const onComplete = vi.fn()
    const processor = new StreamProcessor({ onContent, onComplete })

    processor.processChunk('data: {"sequence_number":1,"type":"response.output_text.delta","data":{"delta":"你"}}\n')
    expect(onContent).not.toHaveBeenCalled()
    processor.processChunk('\ndata: {"sequence_number":2,"type":"response.completed","data":{"status":"completed"}}\n\n')

    expect(onContent).toHaveBeenCalledWith('你')
    expect(onComplete).toHaveBeenCalledWith({ latency_ms: 0 })
  })
})
