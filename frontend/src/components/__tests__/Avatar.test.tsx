import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { QuestionerAvatar, ResponderAvatar } from '../Avatar'

describe('对话头像', () => {
  it('使用项目化图形区分提问者和回答者，不再展示 Q/A 字母占位符', () => {
    const { container } = render(
      <>
        <QuestionerAvatar />
        <ResponderAvatar />
      </>,
    )

    expect(screen.getByRole('img', { name: '提问者头像' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '回答者头像' })).toBeInTheDocument()
    expect(container.querySelectorAll('svg')).toHaveLength(2)
    expect(container).not.toHaveTextContent(/^Q|A$/)
  })

  it('回答者头像继承主题强调色，提问者头像继承表面与文本色', () => {
    render(
      <>
        <QuestionerAvatar />
        <ResponderAvatar />
      </>,
    )

    expect(screen.getByRole('img', { name: '回答者头像' })).toHaveClass('bg-[var(--accent)]')
    expect(screen.getByRole('img', { name: '提问者头像' })).toHaveClass(
      'bg-[var(--surface-raised)]',
    )
  })
})
