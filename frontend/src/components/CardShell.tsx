import type { ReactNode } from 'react'
import { DarkPanel, DarkPanelBody, DarkPanelHeader } from './ui/DarkPanel'

export function CardShell({
  eyebrow,
  title,
  meta,
  children,
  className = '',
  accent = 'from-zinc-500/20',
}: {
  eyebrow: string
  title: string
  meta?: string
  children: ReactNode
  className?: string
  accent?: string
}) {
  return (
    <DarkPanel className={className} accent={accent}>
      <DarkPanelBody>
        <DarkPanelHeader eyebrow={eyebrow} title={title} meta={meta} />
        <div className="mt-4">{children}</div>
      </DarkPanelBody>
    </DarkPanel>
  )
}
