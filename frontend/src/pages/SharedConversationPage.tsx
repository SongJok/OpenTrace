import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'

export default function SharedConversationPage() {
  const { publicId, token } = useParams()
  const [snapshot, setSnapshot] = useState<{ title?: string; messages?: Array<{ role: string; content: string; citations?: Array<{ title: string; url: string }> }> } | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!publicId || !token) return
    fetch(`/api/v2/shared/${encodeURIComponent(publicId)}/${encodeURIComponent(token)}`)
      .then(async (res) => res.ok ? res.json() : Promise.reject(new Error('分享链接无效或已撤销')))
      .then(setSnapshot)
      .catch((err) => setError(err.message || '无法加载分享内容'))
  }, [publicId, token])

  if (error) return <main className="mx-auto max-w-2xl p-8 text-center text-[var(--text-secondary)]">{error}</main>
  if (!snapshot) return <main className="mx-auto max-w-2xl p-8 text-center text-[var(--text-secondary)]">正在加载分享对话…</main>
  return <main className="mx-auto min-h-screen max-w-3xl bg-[var(--bg)] p-5 text-[var(--text)] sm:p-10"><h1 className="mb-8 text-xl font-semibold">{snapshot.title || 'OpenTrace 对话分享'}</h1><div className="space-y-5">{(snapshot.messages || []).map((message, index) => <article key={index} className={`rounded-2xl p-4 ${message.role === 'user' ? 'bg-[var(--surface)]' : 'bg-[var(--surface-raised)]'}`}><div className="mb-2 text-xs text-[var(--text-secondary)]">{message.role === 'user' ? '用户' : 'OpenTrace'}</div><div className="whitespace-pre-wrap leading-7">{message.content}</div>{message.citations?.map((citation, i) => <a key={i} className="mt-2 block text-sm text-[var(--accent)] hover:underline" href={citation.url} target="_blank" rel="noreferrer">{citation.title || citation.url}</a>)}</article>)}</div></main>
}
