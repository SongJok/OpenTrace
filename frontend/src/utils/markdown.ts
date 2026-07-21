import { codeToHtml } from 'shiki'

const FENCE_RE = /```([a-zA-Z0-9_-]+)?\n([\s\S]*?)```/g
const HIGHLIGHT_TIMEOUT_MS = 150
const MAX_HIGHLIGHT_CHARS = 20000

const aliasMap: Record<string, string> = {
  ts: 'typescript',
  js: 'javascript',
  py: 'python',
  sh: 'bash',
  shell: 'bash',
  md: 'markdown',
  yml: 'yaml',
}

const allowedLangs = new Set([
  'text', 'plaintext',
  'typescript', 'javascript', 'tsx', 'jsx',
  'json', 'bash', 'python', 'markdown', 'sql', 'yaml',
])

function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error('highlight-timeout')), timeoutMs)
    promise
      .then((v) => {
        window.clearTimeout(timer)
        resolve(v)
      })
      .catch((e) => {
        window.clearTimeout(timer)
        reject(e)
      })
  })
}

function normalizeLang(lang?: string) {
  const v = (lang || 'text').toLowerCase()
  const mapped = aliasMap[v] || v
  return allowedLangs.has(mapped) ? mapped : 'plaintext'
}

export async function parseMarkdownWithHighlight(markdownText: string): Promise<string> {
  if (!markdownText.includes('```')) return markdownText
  if (markdownText.length > MAX_HIGHLIGHT_CHARS) return markdownText

  const matches = [...markdownText.matchAll(FENCE_RE)]
  if (!matches.length) return markdownText

  let output = markdownText

  for (const m of matches) {
    const lang = normalizeLang(m[1])
    const code = m[2] || ''

    try {
      const html = await withTimeout(
        codeToHtml(code, {
          lang,
          theme: 'github-dark',
        }),
        HIGHLIGHT_TIMEOUT_MS,
      )
      output = output.replace(m[0], `\n${html}\n`)
    } catch {
      // 高亮失败或超时：保持原始 markdown，避免阻塞 UI
    }
  }

  return output
}
