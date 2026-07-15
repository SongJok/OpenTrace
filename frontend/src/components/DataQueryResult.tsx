import React, { useMemo, useState } from 'react'
import { useChatPreferences } from '../store/chatPreferences'

type Row = Record<string, any>

type Props = {
  result?: {
    title?: string
    summary?: string
    interpretation?: string
    sql?: string
    rows?: Row[]
    columns?: string[]
    join_path?: string[]
    table_count?: number
    // cognitive metadata
    confidence?: number
    ranked_candidates?: number
    semantic_mappings_count?: number
    schema?: Record<string, unknown>
  }
}

function inferChartSuggestion(rows: Row[], columns: string[]) {
  if (!rows.length || columns.length < 2) return null
  const numeric = columns.filter((col) => rows.some((row) => typeof row?.[col] === 'number'))
  if (numeric.length >= 1) {
    return {
      type: 'bar',
      x: columns.find((c) => c !== numeric[0]) || columns[0],
      y: numeric[0],
    }
  }
  return { type: 'table' }
}

export default function DataQueryResult({ result }: Props) {
  const requestPrefill = useChatPreferences((state) => state.requestPrefill)
  const rows = result?.rows || []
  const columns = result?.columns || Object.keys(rows[0] || {})
  const [showSql, setShowSql] = useState(false)
  const chart = useMemo(() => inferChartSuggestion(rows, columns), [rows, columns])

  if (!result) return null

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm text-[var(--text)]">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <div className="text-xs uppercase tracking-[0.2em] text-[var(--text-secondary)]">查询结果</div>
            {result.confidence != null && (
              <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                result.confidence >= 0.9 ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                  : result.confidence >= 0.75 ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
                  : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
              }`}>
                {(result.confidence * 100).toFixed(0)}% 置信
              </span>
            )}
          </div>
          <h3 className="mt-1 text-base font-semibold text-[var(--text)]">{result.title || 'Data Query Result'}</h3>
          {result.interpretation ? <p className="mt-2 text-sm text-[var(--text-secondary)]">{result.interpretation}</p> : null}
          {result.summary ? <p className="mt-1 text-sm text-[var(--text-secondary)]">{result.summary}</p> : null}
        </div>
        <div className="text-right text-xs text-[var(--text-secondary)] space-y-1">
          {typeof result.table_count === 'number' ? <div>{result.table_count} 张表</div> : null}
          {Array.isArray(result.join_path) && result.join_path.length > 0 ? <div>JOIN: {result.join_path.join(' → ')}</div> : null}
          {typeof result.ranked_candidates === 'number' && result.ranked_candidates > 0 && (
            <div>{result.ranked_candidates} 候选 SQL</div>
          )}
          {typeof result.semantic_mappings_count === 'number' && result.semantic_mappings_count > 0 && (
            <div>{result.semantic_mappings_count} 语义映射</div>
          )}
        </div>
      </div>

      {rows.length > 0 ? (
        <div className="mt-4 overflow-x-auto rounded-xl border border-[var(--border)]">
          <table className="min-w-full text-sm">
            <thead className="bg-[var(--bg-secondary)] text-[var(--text-secondary)]">
              <tr>
                {columns.map((col) => (
                  <th key={col} className="px-3 py-2 text-left font-medium whitespace-nowrap">{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 20).map((row, idx) => (
                <tr key={idx} className="border-t border-[var(--border)] odd:bg-[var(--surface)] even:bg-[var(--bg-secondary)]">
                  {columns.map((col) => (
                    <td key={col} className="px-3 py-2 align-top text-[var(--text)]">
                      {String(row?.[col] ?? '')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="mt-4 rounded-lg bg-[var(--bg-secondary)] p-3 text-sm text-[var(--text-secondary)]">没有可展示的行数据。</div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {chart ? (
          <button
            type="button"
            className="rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-[var(--bg)] hover:bg-[var(--accent-hover)]"
            onClick={() => requestPrefill(`请根据以下查询结果推荐一个${chart.type}图并解释原因：\n${JSON.stringify(rows.slice(0, 20), null, 2)}`)}
          >
            生成图表建议
          </button>
        ) : null}
        {result.sql ? (
          <button
            type="button"
            className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface-raised)]"
            onClick={() => setShowSql((v) => !v)}
          >
            {showSql ? '收起 SQL' : '查看 SQL'}
          </button>
        ) : null}
      </div>

      {showSql && result.sql ? (
        <pre className="mt-3 overflow-x-auto rounded-xl bg-[var(--bg-secondary)] p-3 text-xs text-[var(--text)]">{result.sql}</pre>
      ) : null}
    </div>
  )
}
