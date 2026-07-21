interface MultiQuestionCard {
  question: string
  answer?: string
  sub_questions?: MultiQuestionCard[]
}

function isMultiQuestionShape(item: unknown): boolean {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return false
  const o = item as Record<string, unknown>
  return typeof o.question === 'string' || Array.isArray(o.sub_questions)
}

function asMultiQuestionList(items: unknown[]): MultiQuestionCard[] | null {
  if (!items.length || !items.every(isMultiQuestionShape)) return null
  return items as MultiQuestionCard[]
}

export function parseMultiQuestionCards(content: string): MultiQuestionCard[] | null {
  if (!content) return null
  try {
    const parsed = JSON.parse(content)
    if (Array.isArray(parsed)) return asMultiQuestionList(parsed)
    if (parsed?.questions && Array.isArray(parsed.questions)) return asMultiQuestionList(parsed.questions)
    return null
  } catch {
    // Try extracting JSON block
    const match = content.match(/```(?:json)?\s*([\s\S]*?)```/)
    if (match) {
      try {
        const inner = JSON.parse(match[1])
        if (Array.isArray(inner)) return asMultiQuestionList(inner)
        if (inner?.questions && Array.isArray(inner.questions)) return asMultiQuestionList(inner.questions)
      } catch { /* ignore */ }
    }
    return null
  }
}
