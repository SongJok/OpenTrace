interface MultiQuestionCard {
  question: string
  answer?: string
  sub_questions?: MultiQuestionCard[]
}

export default function MultiQuestionCards({ cards }: { cards: MultiQuestionCard[] }) {
  if (!cards?.length) return null
  return (
    <div className="space-y-3">
      {cards.map((card, i) => (
        <div key={i} className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
          <h4 className="font-medium mb-2">{card.question}</h4>
          {card.answer ? <p className="text-sm text-[var(--text-secondary)]">{card.answer}</p> : null}
          {card.sub_questions?.length ? (
            <div className="mt-3 ml-4 space-y-2">
              {card.sub_questions.map((sq, j) => (
                <div key={j} className="text-sm">
                  <p className="font-medium">{sq.question}</p>
                  {sq.answer ? <p className="text-[var(--text-secondary)]">{sq.answer}</p> : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  )
}
