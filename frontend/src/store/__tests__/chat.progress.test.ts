import { beforeEach, describe, expect, it } from 'vitest'
import { useChatStore } from '../chat'

describe('chat progress channel', () => {
  beforeEach(() => {
    useChatStore.setState({
      conversations: [],
      activeId: 'session-1',
      messages: {},
      streaming: false,
      activeResponseId: null,
      reasoningSteps: {},
      executionGraphs: {},
      activeReasoningMessageId: {},
    })
  })

  it('keeps progress updates out of assistant answer text', () => {
    const store = useChatStore.getState()
    store.appendAssistantStreamingMessage('session-1', { id: 'assistant-1' })
    store.appendThinking('session-1', '正在检索知识库')
    store.appendStreamingChunk('session-1', '答案正文')

    const message = useChatStore.getState().messages['session-1'][0]
    expect(message.streamText).toBe('答案正文')
    expect(message.progress).toEqual(['正在检索知识库'])
  })

  it('deduplicates repeated progress events', () => {
    const store = useChatStore.getState()
    store.appendAssistantStreamingMessage('session-1', { id: 'assistant-1' })
    store.appendThinking('session-1', '调用工具')
    store.appendThinking('session-1', '调用工具')

    expect(useChatStore.getState().messages['session-1'][0].progress).toEqual(['调用工具'])
  })
})
