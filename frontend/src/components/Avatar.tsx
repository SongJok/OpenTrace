import type { ReactNode } from 'react'

interface AvatarFrameProps {
  label: string
  variant: 'questioner' | 'responder'
  children: ReactNode
}

function AvatarFrame({ label, variant, children }: AvatarFrameProps) {
  const responder = variant === 'responder'
  return (
    <div
      role="img"
      aria-label={label}
      title={label}
      className={`relative flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-xl border shadow-sm ${
        responder
          ? 'border-[var(--accent-border)] bg-[var(--accent)] text-[var(--accent-foreground)]'
          : 'border-[var(--border)] bg-[var(--surface-raised)] text-[var(--text-secondary)]'
      }`}
    >
      <span
        aria-hidden="true"
        className={`absolute inset-0 ${
          responder
            ? 'bg-gradient-to-br from-white/20 via-transparent to-black/10'
            : 'bg-gradient-to-br from-[var(--accent-dim)] via-transparent to-transparent'
        }`}
      />
      <span className="relative flex h-full w-full items-center justify-center">{children}</span>
    </div>
  )
}

export function QuestionerAvatar() {
  return (
    <AvatarFrame label="提问者头像" variant="questioner">
      <svg aria-hidden="true" viewBox="0 0 24 24" className="h-[19px] w-[19px]" fill="none">
        <circle cx="12" cy="8.25" r="3.25" fill="currentColor" opacity="0.92" />
        <path
          d="M5.75 19c.42-3.35 2.68-5.35 6.25-5.35s5.83 2 6.25 5.35"
          stroke="currentColor"
          strokeWidth="2.15"
          strokeLinecap="round"
        />
      </svg>
      <span
        aria-hidden="true"
        className="absolute bottom-1 right-1 h-1.5 w-1.5 rounded-full bg-[var(--accent)] ring-2 ring-[var(--surface-raised)]"
      />
    </AvatarFrame>
  )
}

export function ResponderAvatar() {
  return (
    <AvatarFrame label="回答者头像" variant="responder">
      <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none">
        <path
          d="M5.2 15.3 9.1 8.8l4.2 5.1 5.5-6"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="5.2" cy="15.3" r="1.75" fill="currentColor" />
        <circle cx="9.1" cy="8.8" r="1.75" fill="currentColor" />
        <circle cx="13.3" cy="13.9" r="1.75" fill="currentColor" />
        <circle cx="18.8" cy="7.9" r="1.75" fill="currentColor" />
      </svg>
    </AvatarFrame>
  )
}
