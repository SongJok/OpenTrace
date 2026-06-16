import React from 'react'

export type DatabaseType = 'mysql' | 'clickhouse' | 'doris' | 'postgres'

/** Exported for contract tests and database UI copy (local / self-hosted only). */
export const DATABASE_TYPE_OPTIONS: Array<{ value: DatabaseType; label: string; hint: string; defaultPort: number }> = [
  { value: 'postgres', label: 'PostgreSQL', hint: '本地 / 自建 PostgreSQL', defaultPort: 5432 },
  { value: 'mysql', label: 'MySQL', hint: '本地 / 自建 MySQL', defaultPort: 3306 },
  { value: 'clickhouse', label: 'ClickHouse', hint: '本地 / 自建 ClickHouse', defaultPort: 9000 },
  { value: 'doris', label: 'Doris', hint: '本地 / 自建 Doris', defaultPort: 9030 },
]

const OPTIONS = DATABASE_TYPE_OPTIONS

export const DATABASE_HOST_MODE_OPTIONS = [
  { value: 'local' as const, label: '本机 / 宿主机', hint: '例如 localhost、127.0.0.1、host.docker.internal（宿主机上的 MySQL 也放这里）' },
  { value: 'external' as const, label: '外部链接', hint: '例如宿主机局域网 IP、云数据库、公网地址、内网可达地址' },
]

export type DatabaseHostMode = (typeof DATABASE_HOST_MODE_OPTIONS)[number]['value']

export default function DatabaseTypeSelect({
  value,
  onChange,
}: {
  value: DatabaseType
  onChange: (next: DatabaseType) => void
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`rounded-xl border px-3 py-2 text-left transition ${value === opt.value ? 'border-[var(--accent)] bg-[var(--accent)]/10' : 'border-[var(--border)] bg-[var(--surface-raised)] hover:bg-[var(--surface)]'}`}
        >
          <div className="text-sm font-semibold">{opt.label}</div>
          <div className="mt-0.5 text-[11px] text-[var(--text-secondary)]">{opt.hint}</div>
          <div className="mt-1 text-[10px] text-[var(--text-secondary)]">默认端口 {opt.defaultPort}</div>
        </button>
      ))}
    </div>
  )
}
