import type { ReactNode } from 'react'
import clsx from 'clsx'

export function DarkPanel({
  children,
  className = '',
  accent = 'from-[var(--accent)]/25',
}: {
  children: ReactNode
  className?: string
  accent?: string
}) {
  return (
    <div className={clsx('overflow-hidden rounded-[28px] border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] shadow-[0_20px_50px_rgba(0,0,0,0.18)]', className)}>
      <div className={clsx('h-1 bg-gradient-to-r', accent)} />
      {children}
    </div>
  )
}

export function DarkPanelBody({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={clsx('px-5 py-4', className)}>{children}</div>
}

export function DarkPanelHeader({
  eyebrow,
  title,
  meta,
}: {
  eyebrow: string
  title: string
  meta?: string
}) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--text-secondary)]">{eyebrow}</div>
      <div className="mt-1 text-lg font-semibold tracking-[-0.02em] text-[var(--text)]">{title}</div>
      {meta ? <div className="mt-1 text-sm text-[var(--text-secondary)]">{meta}</div> : null}
    </div>
  )
}

export function DarkPillButton({
  children,
  className = '',
  active = false,
  onClick,
  title,
  type = 'button',
}: {
  children: ReactNode
  className?: string
  active?: boolean
  onClick?: () => void
  title?: string
  type?: 'button' | 'submit' | 'reset'
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      title={title}
      className={clsx(
        'rounded-full border px-3 py-1 text-xs transition-colors',
        active ? 'border-[var(--accent)] bg-[var(--accent-dim)] text-[var(--text)]' : 'border-[var(--border)] bg-[var(--surface-raised)] text-[var(--text-secondary)] hover:bg-[var(--surface)] hover:text-[var(--text)]',
        className
      )}
    >
      {children}
    </button>
  )
}
