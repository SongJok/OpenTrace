export default function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 py-2">
      <span className="h-2 w-2 animate-dot-1 rounded-full bg-[var(--text-secondary)]" />
      <span className="h-2 w-2 animate-dot-2 rounded-full bg-[var(--text-secondary)]" />
      <span className="h-2 w-2 animate-dot-3 rounded-full bg-[var(--text-secondary)]" />
    </div>
  )
}
