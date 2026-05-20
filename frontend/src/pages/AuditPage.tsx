import { useEffect, useState } from 'react'
import { ChevronLeft, Download, ShieldAlert } from 'lucide-react'
import { t } from '../i18n'
import { useAuthStore } from '../store/auth'
import { apiExportAuditLogs, apiListAuditLogs, type AuditLogItem } from '../api/client'

export default function AuditPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((s) => s.token)!
  const [items, setItems] = useState<AuditLogItem[]>([])
  const [action, setAction] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')

  const load = async () => {
    try {
      const rows = await apiListAuditLogs(token, { action: action || undefined, start: start || undefined, end: end || undefined })
      setItems(Array.isArray(rows) ? rows : [])
    } catch (e) {
      console.error('load audit logs failed', e)
      setItems([])
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const exportCsv = async () => {
    const csv = await apiExportAuditLogs(token, { action: action || undefined, start: start || undefined, end: end || undefined, format: 'csv' })
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'audit_logs.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="flex flex-col h-screen bg-[var(--bg)] text-[var(--text)]">
      <div className="flex items-center gap-3 px-6 h-14 border-b border-[var(--border)]">
        <button onClick={onBack} className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
        <h1 className="text-sm font-semibold inline-flex items-center gap-2"><ShieldAlert size={14} />{t('nav.audit')}</h1>
      </div>
      <div className="p-4 space-y-3 overflow-y-auto">
        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 flex flex-wrap gap-2 items-end">
          <div>
            <label className="text-xs">Action</label>
            <input value={action} onChange={(e) => setAction(e.target.value)} className="block rounded border border-[var(--border)] bg-transparent px-2 py-1 text-sm" />
          </div>
          <div>
            <label className="text-xs">Start(ISO)</label>
            <input value={start} onChange={(e) => setStart(e.target.value)} className="block rounded border border-[var(--border)] bg-transparent px-2 py-1 text-sm" />
          </div>
          <div>
            <label className="text-xs">End(ISO)</label>
            <input value={end} onChange={(e) => setEnd(e.target.value)} className="block rounded border border-[var(--border)] bg-transparent px-2 py-1 text-sm" />
          </div>
          <button onClick={() => void load()} className="px-3 py-1.5 rounded border text-xs">查询</button>
          <button onClick={() => void exportCsv()} className="px-3 py-1.5 rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-xs inline-flex items-center gap-1"><Download size={12} />导出 CSV</button>
        </div>
        <div className="space-y-2">
          {items.length === 0 ? <p className="text-sm text-[var(--text-secondary)]">暂无审计记录</p> : items.map((x) => (
            <div key={x.id} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3">
              <p className="text-sm font-medium">{x.action}</p>
              <p className="text-xs text-[var(--text-secondary)]">{x.resource_type} · {x.resource_id} · {x.created_at}</p>
              <pre className="text-xs mt-2 whitespace-pre-wrap">{JSON.stringify(x.payload, null, 2)}</pre>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
