import type { Message } from '../store/chat'

/** 在 HTTPS 与普通 HTTP 部署环境中都尽量可靠地写入剪贴板。 */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  if (!text) return false

  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 非安全上下文或浏览器权限限制时，继续尝试兼容方案。
  }

  if (typeof document === 'undefined') return false
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  textarea.style.top = '0'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()

  try {
    return typeof document.execCommand === 'function' && document.execCommand('copy')
  } catch {
    return false
  } finally {
    textarea.remove()
  }
}

/** 将当前会话整理为适合粘贴到文档或工单的纯文本。 */
export function formatConversationForCopy(messages: Message[]): string {
  return messages
    .filter((message) => message.role === 'user' || message.role === 'assistant')
    .map((message) => {
      const content = (message.status === 'streaming' ? message.streamText : message.finalText).trim()
      const speaker = message.role === 'user' ? '提问者' : 'OpenTrace'
      return `${speaker}\n${content}`
    })
    .filter((block) => block.split('\n').slice(1).join('\n').trim())
    .join('\n\n────────────────\n\n')
}
