import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'

function CopyButton({ text }: { text: string }) {
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard.writeText(text)
      }}
      className="absolute right-2 top-2 rounded bg-[var(--surface-raised)] px-2 py-1 text-[11px] text-[var(--text)] hover:bg-[var(--surface)]"
    >
      复制
    </button>
  )
}

export default function MarkdownMessage({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw]}
      components={{
        pre({ children, ...props }: any) {
          const text = Array.isArray(children)
            ? children
                .map((node: any) => (typeof node === 'string' ? node : node?.props?.children ?? ''))
                .join('')
            : typeof children === 'string'
            ? children
            : ''
          return (
            <div className="relative">
              <CopyButton text={text} />
              <pre
                className="whitespace-pre-wrap break-words text-[14px] leading-relaxed font-mono bg-[var(--bg-secondary)] text-[var(--text)] rounded-xl px-4 py-3 border border-[var(--border)] overflow-x-auto"
                {...props}
              >
                {children}
              </pre>
            </div>
          )
        },
        img({ ...props }: any) {
          return <img className="max-w-full rounded-lg border border-[var(--border)] my-2" alt="" {...props} />
        },
        code({ className, children, ...props }: any) {
          const isInline = !className
          if (isInline) {
            return (
              <code className="bg-[var(--surface-raised)] px-1.5 py-0.5 rounded text-[0.875em] text-[var(--text)]" {...props}>
                {children}
              </code>
            )
          }
          return (
            <code className={className} {...props}>
              {children}
            </code>
          )
        },
      }}
    >
      {content}
    </ReactMarkdown>
  )
}
