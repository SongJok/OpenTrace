import { describe, expect, it, vi } from 'vitest'
import { copyTextToClipboard, formatConversationForCopy } from '../clipboard'
import type { Message } from '../../store/chat'

function message(role: Message['role'], text: string, status: Message['status'] = 'done'): Message {
  return {
    id: `${role}-${text}`,
    role,
    status,
    streamText: status === 'streaming' ? text : '',
    finalText: status === 'streaming' ? '' : text,
  }
}

describe('clipboard helpers', () => {
  it('formats the complete user and assistant conversation while excluding internal messages', () => {
    expect(formatConversationForCopy([
      message('user', '你好'),
      message('assistant', '你好，我是 OpenTrace。'),
      message('tool', '{"internal":true}'),
      message('assistant', '正在生成', 'streaming'),
    ])).toBe('提问者\n你好\n\n────────────────\n\nOpenTrace\n你好，我是 OpenTrace。\n\n────────────────\n\nOpenTrace\n正在生成')
  })

  it('uses the Clipboard API when available', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })

    await expect(copyTextToClipboard('会话内容')).resolves.toBe(true)
    expect(writeText).toHaveBeenCalledWith('会话内容')
  })

  it('falls back to execCommand for HTTP or blocked Clipboard API', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
    const execCommand = vi.fn().mockReturnValue(true)
    Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand })

    await expect(copyTextToClipboard('会话内容')).resolves.toBe(true)
    expect(execCommand).toHaveBeenCalledWith('copy')
    expect(document.querySelector('textarea')).toBeNull()
  })
})
