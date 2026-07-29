import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MarkdownMessage from '../MarkdownMessage'

describe('MarkdownMessage', () => {
  const writeText = vi.fn().mockResolvedValue(undefined)

  beforeEach(() => {
    writeText.mockClear()
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
  })

  it('renders mature GFM structures and keeps wide tables scrollable', () => {
    render(
      <MarkdownMessage
        content={'## 结论\n\n- 第一项\n- 第二项\n\n| 项目 | 结果 |\n| --- | --- |\n| API | 通过 |'}
      />,
    )

    expect(screen.getByRole('heading', { name: '结论' })).toBeInTheDocument()
    expect(screen.getByText('第一项')).toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByTestId('markdown-table-wrap')).toHaveClass('markdown-table-wrap')
  })

  it('highlights fenced code, shows its language and copies source text', async () => {
    render(<MarkdownMessage content={'```ts\nconst ready = true\n```'} />)

    expect(screen.getByText('typescript')).toBeInTheDocument()
    const copyButton = screen.getByRole('button', { name: '复制代码' })
    fireEvent.click(copyButton)

    await waitFor(() => expect(writeText).toHaveBeenCalledWith('const ready = true'))
    expect(screen.getByText('已复制')).toBeInTheDocument()
  })

  it('previews fenced HTML in an isolated sandbox after user confirmation', () => {
    const html = '<!doctype html><html><body><button>演示按钮</button><script>document.body.dataset.ready = "true"</script></body></html>'
    render(<MarkdownMessage content={`\`\`\`html\n${html}\n\`\`\``} />)

    expect(screen.queryByRole('dialog', { name: 'HTML 效果预览' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看 HTML 效果' }))

    expect(screen.getByRole('dialog', { name: 'HTML 效果预览' })).toBeInTheDocument()
    const frame = screen.getByTitle('HTML 效果预览画布')
    expect(frame).toHaveAttribute('srcdoc', html)
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts')
    expect(frame.getAttribute('sandbox')).not.toContain('allow-same-origin')

    fireEvent.click(screen.getByRole('button', { name: '关闭 HTML 预览' }))
    expect(screen.queryByRole('dialog', { name: 'HTML 效果预览' })).not.toBeInTheDocument()
  })

  it('does not show the effect preview action for non-HTML code', () => {
    render(<MarkdownMessage content={'```ts\nconst ready = true\n```'} />)
    expect(screen.queryByRole('button', { name: '查看 HTML 效果' })).not.toBeInTheDocument()
  })

  it('renders LaTeX formulas', () => {
    const { container } = render(<MarkdownMessage content={'质能方程：$E = mc^2$'} />)
    expect(container.querySelector('.katex')).not.toBeNull()
  })

  it('opens trusted external links safely and blocks executable URLs', () => {
    const { container } = render(
      <MarkdownMessage content={'[文档](https://example.com/docs) [危险](javascript:alert(1))'} />,
    )
    const trusted = screen.getByRole('link', { name: /文档/ })
    expect(trusted).toHaveAttribute('target', '_blank')
    expect(trusted).toHaveAttribute('rel', 'noopener noreferrer')
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull()
  })

  it('does not execute or mount raw HTML from model output', () => {
    const { container } = render(
      <MarkdownMessage content={'正常内容<script>alert(1)</script><iframe src="https://example.com"></iframe>'} />,
    )
    expect(container).toHaveTextContent('正常内容')
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('iframe')).toBeNull()
  })
})
