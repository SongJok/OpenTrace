interface MultiQuestionCard {
  question: string
  answer?: string
  sub_questions?: MultiQuestionCard[]
}

export function parseMultiQuestionCards(content: string): MultiQuestionCard[] | null {
  if (!content) return null
  try {
    const parsed = JSON.parse(content)
    if (Array.isArray(parsed)) return parsed as MultiQuestionCard[]
    if (parsed?.questions && Array.isArray(parsed.questions)) return parsed.questions
    return null
  } catch {
    // Try extracting JSON block
    const match = content.match(/```(?:json)?\s*([\s\S]*?)```/)
    if (match) {
      try {
        const inner = JSON.parse(match[1])
        if (Array.isArray(inner)) return inner as MultiQuestionCard[]
        if (inner?.questions) return inner.questions
      } catch { /* ignore */ }
    }
    return null
  }
}
