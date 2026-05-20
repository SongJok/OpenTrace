import { useMemo } from 'react'
import { BarChart3, TrendingUp, PieChart, Table2 } from 'lucide-react'

// ── Types ──────────────────────────────────────────────────────────

export interface ChartConfig {
  chart_type: string
  title?: string
  x_axis?: string
  y_axis?: string[]
  series?: string[]
  alternatives?: string[]
  options?: Record<string, any>
  columns?: string[]
  data_source?: string
}

interface DataTableChartProps {
  rows?: Record<string, any>[]
  config?: ChartConfig | null
  sql?: string
  maxRows?: number
  onChartTypeChange?: (type: string) => void
  data?: { columns?: string[]; rows?: any[]; [key: string]: any }
}

// ── Color palette ──────────────────────────────────────────────────

const COLORS = ['#2563eb', '#dc2626', '#16a34a', '#ca8a04', '#9333ea', '#0891b2', '#db2777', '#ea580c', '#4f46e5', '#059669']

// ── Chart Sub-Components ────────────────────────────────────────────

function BarChart({ rows, config }: { rows: Record<string, any>[]; config: ChartConfig }) {
  const { x_axis, y_axis } = config
  const xKey = x_axis || Object.keys(rows[0] || {})[0]
  const yKeys = (y_axis && y_axis.length > 0) ? y_axis : [Object.keys(rows[0] || {})[1] || 'value']

  const maxVal = useMemo(() => {
    return Math.max(1, ...rows.flatMap(r => yKeys.map(k => Number(r[k]) || 0)))
  }, [rows, yKeys])

  if (!xKey) return <p style={{ color: '#9ca3af' }}>No axis configured</p>

  return (
    <div>
      {config.title && <h4 style={{ margin: '0 0 12px 0', fontSize: 13, fontWeight: 600 }}>{config.title}</h4>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {rows.map((row, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ width: 120, fontSize: 12, textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 0 }}>
              {String(row[xKey] ?? '')}
            </span>
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 4 }}>
              {yKeys.map((k, j) => {
                const v = Number(row[k]) || 0
                const w = Math.max(2, (v / maxVal) * 100)
                return (
                  <div key={k} style={{ flex: 1 }}>
                    <div style={{
                      height: 20, width: `${w}%`, minWidth: 4,
                      background: COLORS[j % COLORS.length],
                      borderRadius: 3, transition: 'width 0.3s',
                    }} />
                    <span style={{ fontSize: 10, color: '#6b7280' }}>{v.toLocaleString()}</span>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
      {/* Legend */}
      {yKeys.length > 1 && (
        <div style={{ display: 'flex', gap: 12, marginTop: 10 }}>
          {yKeys.map((k, j) => (
            <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
              <div style={{ width: 10, height: 10, borderRadius: 2, background: COLORS[j % COLORS.length] }} />
              {k}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function LineChart({ rows, config }: { rows: Record<string, any>[]; config: ChartConfig }) {
  const { x_axis, y_axis } = config
  const xKey = x_axis || Object.keys(rows[0] || {})[0]
  const yKey = (y_axis && y_axis.length > 0) ? y_axis[0] : Object.keys(rows[0] || {})[1] || 'value'

  const values = rows.map(r => Number(r[yKey]) || 0)
  const maxVal = Math.max(1, ...values)
  const minVal = Math.min(0, ...values)
  const range = maxVal - minVal || 1

  const points = values.map((v, i) => {
    const x = (i / Math.max(1, values.length - 1)) * 100
    const y = 100 - ((v - minVal) / range) * 100
    return `${x},${y}`
  }).join(' ')

  return (
    <div>
      {config.title && <h4 style={{ margin: '0 0 12px 0', fontSize: 13, fontWeight: 600 }}>{config.title}</h4>}
      <div style={{ position: 'relative', height: 200, border: '1px solid #e5e7eb', borderRadius: 8, padding: 12, background: '#fafafa' }}>
        <svg viewBox="0 0 100 100" style={{ width: '100%', height: '100%' }} preserveAspectRatio="none">
          {/* Grid lines */}
          {[0, 25, 50, 75, 100].map(y => (
            <line key={y} x1="0" y1={y} x2="100" y2={y} stroke="#e5e7eb" strokeWidth="0.3" />
          ))}
          {/* Line */}
          <polyline points={points} fill="none" stroke={COLORS[0]} strokeWidth="1.5" />
          {/* Points */}
          {values.map((v, i) => {
            const cx = (i / Math.max(1, values.length - 1)) * 100
            const cy = 100 - ((v - minVal) / range) * 100
            return <circle key={i} cx={cx} cy={cy} r="1.5" fill={COLORS[0]} />
          })}
        </svg>
        {/* X-axis labels */}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
          {rows.length > 0 && (
            <>
              <span style={{ fontSize: 10, color: '#9ca3af' }}>{String(rows[0][xKey] ?? '')}</span>
              {rows.length > 1 && <span style={{ fontSize: 10, color: '#9ca3af' }}>{String(rows[rows.length - 1][xKey] ?? '')}</span>}
            </>
          )}
        </div>
      </div>
      <span style={{ fontSize: 10, color: '#6b7280', marginTop: 4, display: 'block' }}>范围: {minVal.toLocaleString()} – {maxVal.toLocaleString()}</span>
    </div>
  )
}

function PieChartView({ rows, config }: { rows: Record<string, any>[]; config: ChartConfig }) {
  const { x_axis, y_axis } = config
  const catKey = x_axis || Object.keys(rows[0] || {})[0]
  const valKey = (y_axis && y_axis.length > 0) ? y_axis[0] : Object.keys(rows[0] || {})[1] || 'value'

  const total = rows.reduce((s, r) => s + (Number(r[valKey]) || 0), 0) || 1

  let cumulative = 0
  const slices = rows.map((r, i) => {
    const v = Number(r[valKey]) || 0
    const pct = (v / total) * 100
    const start = cumulative
    cumulative += pct
    return { label: String(r[catKey] ?? ''), value: v, pct, start, color: COLORS[i % COLORS.length] }
  })

  const pathData = slices.map(s => {
    const startAngle = (s.start / 100) * 360 - 90
    const endAngle = ((s.start + s.pct) / 100) * 360 - 90
    const r = 40
    const cx = 50; const cy = 50
    const x1 = cx + r * Math.cos((startAngle * Math.PI) / 180)
    const y1 = cy + r * Math.sin((startAngle * Math.PI) / 180)
    const x2 = cx + r * Math.cos((endAngle * Math.PI) / 180)
    const y2 = cy + r * Math.sin((endAngle * Math.PI) / 180)
    const large = (s.pct > 50) ? 1 : 0
    return { d: `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`, ...s }
  })

  return (
    <div>
      {config.title && <h4 style={{ margin: '0 0 12px 0', fontSize: 13, fontWeight: 600 }}>{config.title}</h4>}
      <div style={{ display: 'flex', gap: 20, alignItems: 'center' }}>
        <svg viewBox="0 0 100 100" style={{ width: 160, height: 160 }}>
          {pathData.map(s => (
            <path key={s.label} d={s.d} fill={s.color} stroke="#fff" strokeWidth="0.5" />
          ))}
        </svg>
        <div>
          {slices.slice(0, 8).map(s => (
            <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginBottom: 4 }}>
              <div style={{ width: 10, height: 10, borderRadius: 2, background: s.color, flexShrink: 0 }} />
              <span style={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.label}</span>
              <span style={{ color: '#6b7280' }}>{s.pct.toFixed(1)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function TableView({ rows, config, maxRows = 50 }: { rows: Record<string, any>[]; config: ChartConfig; maxRows?: number }) {
  const columns = config.columns || (rows[0] ? Object.keys(rows[0]) : [])
  const displayRows = rows.slice(0, maxRows)

  return (
    <div style={{ overflow: 'auto', maxHeight: 400 }}>
      {config.title && <h4 style={{ margin: '0 0 8px 0', fontSize: 13, fontWeight: 600 }}>{config.title}</h4>}
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: '#f9fafb', position: 'sticky', top: 0 }}>
            {columns.map(c => (
              <th key={c} style={{ padding: '6px 10px', textAlign: 'left', fontWeight: 600, color: '#6b7280', fontSize: 12, borderBottom: '2px solid #e5e7eb' }}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {displayRows.map((row, i) => (
            <tr key={i} style={{ borderBottom: '1px solid #f3f4f6' }}>
              {columns.map(c => (
                <td key={c} style={{ padding: '6px 10px', fontSize: 12 }}>
                  {row[c] === null ? <span style={{ color: '#d1d5db' }}>NULL</span> : String(row[c] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > maxRows && (
        <p style={{ fontSize: 11, color: '#9ca3af', marginTop: 8 }}>
          显示前 {maxRows} 行 (共 {rows.length} 行)
        </p>
      )}
    </div>
  )
}

function MetricCard({ rows, config }: { rows: Record<string, any>[]; config: ChartConfig }) {
  const val = rows[0] ? Object.values(rows[0])[0] : null
  return (
    <div style={{ padding: 24, background: '#f0f9ff', borderRadius: 12, border: '1px solid #bae6fd', textAlign: 'center' }}>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{config.options?.label || 'Value'}</div>
      <div style={{ fontSize: 36, fontWeight: 700, color: '#1e40af', marginTop: 8 }}>
        {typeof val === 'number' ? val.toLocaleString() : String(val ?? '-')}
      </div>
      {config.title && <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 4 }}>{config.title}</div>}
    </div>
  )
}

// ── Main Component ─────────────────────────────────────────────────

export default function DataTableChart({ rows: rowsProp, config, sql, maxRows = 50, onChartTypeChange, data }: DataTableChartProps) {
  const rows = rowsProp ?? data?.rows ?? []
  const chartType = config?.chart_type || 'table'
  const alternatives = config?.alternatives || []

  if (!rows || rows.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: 'center', color: '#9ca3af' }}>
        <BarChart3 size={32} />
        <p style={{ marginTop: 8 }}>暂无数据可显示</p>
      </div>
    )
  }

  // Render chart based on type
  const renderChart = () => {
    if (!config) return <TableView rows={rows} config={{ chart_type: 'table', columns: Object.keys(rows[0] || {}) }} maxRows={maxRows} />

    switch (chartType) {
      case 'bar': case 'grouped_bar': case 'horizontal_bar': case 'stacked_bar':
        return <BarChart rows={rows} config={config} />
      case 'line': case 'area': case 'multi_line':
        return <LineChart rows={rows} config={config} />
      case 'pie': case 'donut':
        return <PieChartView rows={rows} config={config} />
      case 'metric_card':
        return <MetricCard rows={rows} config={config} />
      case 'scatter': case 'heatmap':
        return <TableView rows={rows} config={config} maxRows={maxRows} />
      case 'table':
      default:
        return <TableView rows={rows} config={config} maxRows={maxRows} />
    }
  }

  // Chart type icons
  const chartIcon = (t: string) => {
    if (t.startsWith('bar') || t === 'grouped_bar' || t === 'horizontal_bar') return <BarChart3 size={12} />
    if (t === 'line' || t === 'area') return <TrendingUp size={12} />
    if (t === 'pie' || t === 'donut') return <PieChart size={12} />
    return <Table2 size={12} />
  }

  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, overflow: 'hidden' }}>
      {/* Toolbar */}
      <div style={{ padding: '8px 12px', background: '#f9fafb', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          {[chartType, ...alternatives].slice(0, 5).map(t => (
            <button key={t} onClick={() => onChartTypeChange?.(t)}
              style={{
                padding: '4px 10px', border: '1px solid #ddd', borderRadius: 4, cursor: 'pointer',
                background: t === chartType ? '#2563eb' : '#fff',
                color: t === chartType ? '#fff' : '#374151',
                fontSize: 11, display: 'flex', alignItems: 'center', gap: 4,
              }}
            >
              {chartIcon(t)} {t.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
        <span style={{ fontSize: 11, color: '#9ca3af' }}>{rows.length} rows</span>
      </div>

      {/* Chart body */}
      <div style={{ padding: 16 }}>
        {renderChart()}
      </div>

      {/* SQL display */}
      {sql && (
        <details style={{ borderTop: '1px solid #e5e7eb', padding: '8px 12px' }}>
          <summary style={{ fontSize: 11, color: '#6b7280', cursor: 'pointer' }}>SQL</summary>
          <pre style={{ fontSize: 11, background: '#f3f4f6', padding: 8, borderRadius: 4, overflow: 'auto', maxHeight: 200 }}>
            {sql}
          </pre>
        </details>
      )}
    </div>
  )
}
