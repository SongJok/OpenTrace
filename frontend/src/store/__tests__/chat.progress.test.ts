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

  it('keeps approval content on resolve failure and removes only the resolved card while resuming', () => {
    useChatStore.setState({
      messages: {
        'session-1': [{
          id: 'assistant-1',
          role: 'assistant',
          status: 'done',
          streamText: '',
          finalText: '请确认日程',
          approvals: [{
            id: 'approval-1',
            call_id: 'call-1',
            tool_name: 'create_calendar_event',
            side_effect: 'write',
            arguments: { title: '客户复盘' },
          }],
        }],
      },
    })

    const store = useChatStore.getState()
    store.resumeAssistantMessage('session-1', 'assistant-1')
    let message = useChatStore.getState().messages['session-1'][0]
    expect(message.status).toBe('streaming')
    expect(message.approvals).toEqual([])

    useChatStore.setState({
      messages: {
        'session-1': [{ ...message, approvals: [{
          id: 'approval-1',
          call_id: 'call-1',
          tool_name: 'create_calendar_event',
          side_effect: 'write',
          arguments: { title: '客户复盘' },
        }] }],
      },
    })
    useChatStore.getState().restoreAssistantApproval('session-1', 'assistant-1')
    message = useChatStore.getState().messages['session-1'][0]
    expect(message.status).toBe('done')
    expect(message.finalText).toBe('请确认日程')
    expect(message.approvals).toHaveLength(1)
  })

  it('keeps an approved response in the running state after stream recovery is exhausted', () => {
    useChatStore.setState({
      messages: {
        'session-1': [{
          id: 'assistant-1',
          role: 'assistant',
          status: 'done',
          streamText: '',
          finalText: '请确认日程',
          approvals: [{
            id: 'approval-1',
            call_id: 'call-1',
            tool_name: 'create_calendar_event',
            side_effect: 'write',
            arguments: { title: '客户复盘' },
          }],
        }],
      },
    })

    useChatStore.getState().keepAssistantResponseRunning('session-1', 'assistant-1')

    const state = useChatStore.getState()
    const message = state.messages['session-1'][0]
    expect(message.status).toBe('streaming')
    expect(message.approvals).toEqual([])
    expect(state.streaming).toBe(true)
    expect(state.activeReasoningMessageId['session-1']).toBe('assistant-1')
  })
})
