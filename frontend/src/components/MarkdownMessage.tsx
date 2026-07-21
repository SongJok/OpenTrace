import { Children, isValidElement, type ReactNode, useState } from 'react'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import { Check, Copy, ExternalLink } from 'lucide-react'
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

function CodeBlock({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false)
  const normalizedLanguage = normalizeLanguage(language)
  const highlightLanguage = REGISTERED_LANGUAGES.has(normalizedLanguage) ? normalizedLanguage : undefined

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
    <div className="markdown-code-block not-prose" data-language={normalizedLanguage}>
      <div className="markdown-code-header">
        <span>{readableLanguage(language)}</span>
        <button type="button" onClick={() => void copy()} aria-label="复制代码" title={copied ? '已复制' : '复制代码'}>
          {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
          <span>{copied ? '已复制' : '复制代码'}</span>
        </button>
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
