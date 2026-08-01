import { Children, isValidElement, type ReactNode, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import { Check, Copy, ExternalLink, Eye, X } from 'lucide-react'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash'
import csharp from 'react-syntax-highlighter/dist/esm/languages/prism/csharp'
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css'
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go'
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java'
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript'
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json'
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx'
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown'
import markup from 'react-syntax-highlighter/dist/esm/languages/prism/markup'
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import rust from 'react-syntax-highlighter/dist/esm/languages/prism/rust'
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql'
import tsx from 'react-syntax-highlighter/dist/esm/languages/prism/tsx'
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript'
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import 'katex/dist/katex.min.css'
import { useCompanyStore } from '../store/company'

const HIGHLIGHT_LANGUAGES = {
  bash,
  csharp,
  css,
  go,
  java,
  javascript,
  json,
  jsx,
  markdown,
  markup,
  python,
  rust,
  sql,
  tsx,
  typescript,
  yaml,
} as const

Object.entries(HIGHLIGHT_LANGUAGES).forEach(([name, syntax]) => {
  SyntaxHighlighter.registerLanguage(name, syntax)
})

const REGISTERED_LANGUAGES = new Set(Object.keys(HIGHLIGHT_LANGUAGES))

const LANGUAGE_ALIASES: Record<string, string> = {
  csharp: 'csharp',
  cs: 'csharp',
  html: 'markup',
  js: 'javascript',
  md: 'markdown',
  py: 'python',
  rb: 'ruby',
  sh: 'bash',
  shell: 'bash',
  ts: 'typescript',
  yml: 'yaml',
}

function normalizeLanguage(value?: string) {
  const language = (value || 'text').trim().toLowerCase()
  return LANGUAGE_ALIASES[language] || language || 'text'
}

function readableLanguage(value?: string) {
  const language = normalizeLanguage(value)
  return language === 'text' || language === 'plaintext' ? '纯文本' : language
}

function nodeText(value: ReactNode): string {
  return Children.toArray(value)
    .map((child) => {
      if (typeof child === 'string' || typeof child === 'number') return String(child)
      if (isValidElement<{ children?: ReactNode }>(child)) return nodeText(child.props.children)
      return ''
    })
    .join('')
}

function HtmlPreviewDialog({ code, onClose }: { code: string; onClose: () => void }) {
  const brandName = useCompanyStore((state) => state.brandName)
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return createPortal(
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-3 backdrop-blur-sm sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="html-preview-title"
      onClick={onClose}
    >
      <div
        className="flex h-[min(88vh,900px)] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface-raised)] shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-[var(--border)] px-4 py-3">
          <div className="min-w-0">
            <h2 id="html-preview-title" className="text-sm font-semibold text-[var(--text)]">HTML 效果预览</h2>
            <p className="mt-0.5 text-xs text-[var(--text-secondary)]">内容在隔离沙箱中运行，与 {brandName} 页面相互隔离。</p>
          </div>
          <button
            type="button"
            autoFocus
            onClick={onClose}
            className="ml-auto inline-flex h-8 w-8 items-center justify-center rounded-lg text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
            aria-label="关闭 HTML 预览"
            title="关闭"
          >
            <X size={17} aria-hidden="true" />
          </button>
        </div>
        <div className="min-h-0 flex-1 bg-white">
          <iframe
            title="HTML 效果预览画布"
            srcDoc={code}
            sandbox="allow-scripts"
            referrerPolicy="no-referrer"
            className="h-full w-full border-0 bg-white"
          />
        </div>
      </div>
    </div>,
    document.body,
  )
}

function CodeBlock({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false)
  const [showPreview, setShowPreview] = useState(false)
  const normalizedLanguage = normalizeLanguage(language)
  const highlightLanguage = REGISTERED_LANGUAGES.has(normalizedLanguage) ? normalizedLanguage : undefined
  const canPreview = normalizedLanguage === 'markup'

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopied(false)
    }
  }

  return (
    <>
      <div className="markdown-code-block not-prose" data-language={normalizedLanguage}>
        <div className="markdown-code-header">
          <span>{readableLanguage(language)}</span>
          <div className="markdown-code-actions">
            {canPreview && (
              <button
                type="button"
                onClick={() => setShowPreview(true)}
                aria-label="查看 HTML 效果"
                title="查看效果"
              >
                <Eye size={14} aria-hidden="true" />
                <span>查看效果</span>
              </button>
            )}
            <button type="button" onClick={() => void copy()} aria-label="复制代码" title={copied ? '已复制' : '复制代码'}>
              {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
              <span>{copied ? '已复制' : '复制代码'}</span>
            </button>
          </div>
        </div>
        <SyntaxHighlighter
          language={highlightLanguage}
          style={oneDark}
          PreTag="div"
          customStyle={{
            background: 'transparent',
            border: 0,
            borderRadius: 0,
            fontSize: '13px',
            lineHeight: '1.65',
            margin: 0,
            overflowX: 'auto',
            padding: '16px 18px 18px',
          }}
          codeTagProps={{
            className: 'markdown-code-source',
            style: {
              fontFamily: "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace",
            },
          }}
          wrapLongLines={false}
        >
          {code}
        </SyntaxHighlighter>
      </div>
      {showPreview && <HtmlPreviewDialog code={code} onClose={() => setShowPreview(false)} />}
    </>
  )
}

function safeUrl(url: string) {
  const value = url.trim()
  const lower = value.toLowerCase()
  const hasScheme = /^[a-z][a-z0-9+.-]*:/i.test(value)
  if (
    !hasScheme ||
    value.startsWith('#') ||
    lower.startsWith('https://') ||
    lower.startsWith('http://') ||
    lower.startsWith('mailto:')
  ) {
    return defaultUrlTransform(value)
  }
  return ''
}

export default function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="markdown-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        skipHtml
        urlTransform={safeUrl}
        components={{
          pre({ children }) {
            const items = Children.toArray(children)
            const child = items.length === 1 && isValidElement<{ className?: string; children?: ReactNode }>(items[0])
              ? items[0]
              : null
            const className = child?.props.className || ''
            const language = className.match(/language-([^\s]+)/)?.[1]
            const code = nodeText(child?.props.children ?? children).replace(/\n$/, '')
            return <CodeBlock code={code} language={language} />
          },
          code({ className, children, ...props }) {
            return (
              <code className={className} {...props}>
                {children}
              </code>
            )
          },
          table({ children, ...props }) {
            return (
              <div className="markdown-table-wrap" data-testid="markdown-table-wrap">
                <table {...props}>{children}</table>
              </div>
            )
          },
          a({ href = '', children, ...props }) {
            const safeHref = safeUrl(href)
            const external = /^https?:\/\//i.test(safeHref)
            return (
              <a
                href={safeHref || undefined}
                target={external ? '_blank' : undefined}
                rel={external ? 'noopener noreferrer' : undefined}
                {...props}
              >
                {children}
                {external && <ExternalLink className="markdown-external-icon" size={12} aria-hidden="true" />}
              </a>
            )
          },
          img({ alt = '', ...props }) {
            return <img loading="lazy" decoding="async" alt={alt} {...props} />
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
