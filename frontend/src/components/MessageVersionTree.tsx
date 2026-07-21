interface MessageVersion {
  version_id: string
  message_id: string
  parent_id?: string
  content: string
  created_at: string
}

export default function MessageVersionTree({
  versions,
  currentId,
}: {
  versions: MessageVersion[]
  currentId: string
}) {
  if (!versions?.length) return null
  return (
    <div className="mt-2 pt-2 border-t border-[var(--border)]">
      <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-secondary)] mb-2">版本历史</div>
      <div className="space-y-1">
        {versions.map((v) => (
          <div
            key={v.version_id}
            className={`text-xs px-2 py-1 rounded ${
              v.version_id === currentId
                ? 'bg-blue-50 text-blue-700 dark:bg-blue-900 dark:text-blue-300'
                : 'text-[var(--text-secondary)]'
            }`}
          >
            {new Date(v.created_at).toLocaleString()} {v.parent_id ? '(编辑)' : '(原始)'}
          </div>
        ))}
      </div>
    </div>
  )
}
