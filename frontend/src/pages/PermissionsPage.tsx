import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/auth'
import {
  apiApproveUser,
  apiDisableUser,
  apiEnableUser,
  apiGetChatConstitution,
  apiGetMemoryConstitution,
  apiListChatConstitutionAudits,
  apiListChatConstitutionHistory,
  apiListMemoryConstitutionAudits,
  apiListMemoryConstitutionHistory,
  apiListUsers,
  apiPreviewChatConstitution,
  apiPreviewMemoryConstitution,
  apiRestoreChatConstitution,
  apiRestoreMemoryConstitution,
  apiResetUserPassword,
  apiUpdateChatConstitution,
  apiUpdateMemoryConstitution,
  type ChatConstitutionAuditItem,
  type ChatConstitutionData,
  type ChatConstitutionHistoryItem,
  type ChatConstitutionPreview,
  type ChatConstitutionRules,
  type MemoryConstitutionAuditItem,
  type MemoryConstitutionData,
  type MemoryConstitutionHistoryItem,
  type MemoryConstitutionPreview,
  type MemoryConstitutionRules,
} from '../api/client'
import { t } from '../i18n'

interface UserItem {
  id: string
  email: string
  display_name: string | null
  status: string
  role: string
  is_superuser: boolean
  created_at: string
}

const STATUS_TABS = [
  { key: '', label: 'permissions.allUsers' },
  { key: 'pending', label: 'permissions.pending' },
  { key: 'active', label: 'permissions.active' },
  { key: 'disabled', label: 'permissions.disabled' },
]

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-yellow-500/20 text-yellow-400',
  active: 'bg-green-500/20 text-green-400',
  disabled: 'bg-red-500/20 text-red-400',
}

const ROLE_COLORS: Record<string, string> = {
  admin: 'bg-purple-500/20 text-purple-400',
  user: 'bg-blue-500/20 text-blue-400',
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function ChatConstitutionPanel({ token, setMessage }: { token: string; setMessage: (value: string) => void }) {
  const [constitution, setConstitution] = useState<ChatConstitutionData | null>(null)
  const [content, setContent] = useState('')
  const [rules, setRules] = useState<ChatConstitutionRules | null>(null)
  const [history, setHistory] = useState<ChatConstitutionHistoryItem[]>([])
  const [audits, setAudits] = useState<ChatConstitutionAuditItem[]>([])
  const [sampleInput, setSampleInput] = useState('')
  const [preview, setPreview] = useState<ChatConstitutionPreview | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [restoring, setRestoring] = useState<number | null>(null)

  async function load() {
    setLoading(true)
    try {
      const [data, nextHistory, nextAudits] = await Promise.all([
        apiGetChatConstitution(token),
        apiListChatConstitutionHistory(token),
        apiListChatConstitutionAudits(token),
      ])
      setConstitution(data)
      setContent(data.content)
      setRules(data.rules)
      setHistory(nextHistory)
      setAudits(nextAudits)
      setPreview(null)
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [token])

  function updateRules(next: ChatConstitutionRules) {
    setRules(next)
    setPreview(null)
  }

  function toggleCategory(category: string) {
    if (!rules || constitution?.immutable_categories.includes(category)) return
    const selected = rules.prohibited_categories.includes(category)
    updateRules({
      ...rules,
      prohibited_categories: selected
        ? rules.prohibited_categories.filter((item) => item !== category)
        : [...rules.prohibited_categories, category],
    })
  }

  async function save() {
    if (!rules) return
    setSaving(true)
    setMessage('')
    try {
      const data = await apiUpdateChatConstitution(token, {
        content,
        rules,
        expected_version: constitution?.version ?? 0,
      })
      setMessage(data.unchanged
        ? `聊天宪法 v${data.version} 内容未变化，无需生成新版本`
        : `聊天宪法 v${data.version} 已立即生效`)
      await load()
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function testDecision() {
    if (!rules || !sampleInput.trim()) return
    setPreviewing(true)
    setMessage('')
    try {
      setPreview(await apiPreviewChatConstitution(token, {
        content,
        rules,
        expected_version: constitution?.version ?? 0,
        sample_input: sampleInput,
      }))
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setPreviewing(false)
    }
  }

  async function restore(version: number) {
    if (!constitution || !confirm(`确认以聊天宪法 v${version} 的内容创建新的生效版本？`)) return
    setRestoring(version)
    setMessage('')
    try {
      const data = await apiRestoreChatConstitution(token, version, constitution.version)
      setMessage(data.unchanged
        ? `v${version} 与当前聊天宪法一致，无需恢复`
        : `已从 v${version} 恢复为新的 v${data.version}，并立即生效`)
      await load()
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setRestoring(null)
    }
  }

  if (loading || !constitution || !rules) {
    return <p className="text-sm text-[#8e8ea0]">{t('common.loading')}</p>
  }

  const categories = [...constitution.immutable_categories, ...Object.keys(constitution.editable_categories)]
  const labels = { ...constitution.immutable_category_labels, ...constitution.editable_categories }

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-[#3d3d3d] bg-[#292929] p-5">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-white">当前生效聊天宪法</h2>
              <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-300">v{constitution.version || '默认'}</span>
            </div>
            <p className="mt-1 text-xs text-[#a7a7b0]">新问题会先经过确定性判定；命中后不创建 Response、不调用模型与工具。</p>
          </div>
          <button onClick={save} disabled={saving || content.trim().length < 80} className="rounded-lg bg-[#10a37f] px-4 py-2 text-sm font-medium text-white hover:bg-[#0d8c6d] disabled:opacity-50">
            {saving ? '发布中…' : '发布新版本'}
          </button>
        </div>
        <textarea value={content} onChange={(event) => { setContent(event.target.value); setPreview(null) }} rows={12} aria-label="聊天宪法内容" className="w-full resize-y rounded-xl border border-[#454545] bg-[#202020] px-4 py-3 text-sm leading-6 text-white outline-none focus:border-[#10a37f]" />
        <p className="mt-2 text-xs text-[#8e8ea0]">可在正文加入“禁止问答词：词语A、词语B”或“允许问答词：词语C”；规则发布后按工作区立即生效。</p>
      </section>

      <section className="grid gap-5 md:grid-cols-2">
        <div className="rounded-2xl border border-[#3d3d3d] bg-[#292929] p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div><h3 className="font-medium text-white">拦截类别</h3><p className="mt-1 text-xs text-[#a7a7b0]">锁定项属于安全底线；政治敏感等工作区项可由管理员调整。</p></div>
            <label className="flex items-center gap-2 text-xs text-[#d4d4d8]">工作区策略<input type="checkbox" checked={rules.enabled} onChange={(event) => updateRules({ ...rules, enabled: event.target.checked })} className="accent-[#10a37f]" /></label>
          </div>
          <div className="space-y-2">
            {categories.map((category) => {
              const locked = constitution.immutable_categories.includes(category)
              return (
                <label key={category} className="flex items-center justify-between gap-3 rounded-lg bg-[#222] px-3 py-2 text-sm text-[#e4e4e7]">
                  <span>{labels[category] || category}</span>
                  <span className="flex items-center gap-2 text-xs text-[#8e8ea0]">{locked && '锁定'}<input type="checkbox" checked={rules.prohibited_categories.includes(category)} disabled={locked} onChange={() => toggleCategory(category)} className="accent-[#10a37f]" /></span>
                </label>
              )
            })}
          </div>
        </div>

        <div className="rounded-2xl border border-[#3d3d3d] bg-[#292929] p-5">
          <h3 className="font-medium text-white">判定与提示</h3>
          <label className="mt-4 block text-xs text-[#a7a7b0]">用户提示语
            <textarea value={rules.block_message} onChange={(event) => updateRules({ ...rules, block_message: event.target.value })} rows={3} className="mt-1 w-full rounded-lg border border-[#454545] bg-[#202020] px-3 py-2 text-sm text-white" />
          </label>
          <label className="mt-3 block text-xs text-[#a7a7b0]">单次输入最大字符数
            <input type="number" min="500" max="100000" value={rules.max_input_chars} onChange={(event) => updateRules({ ...rules, max_input_chars: Number(event.target.value) })} className="mt-1 w-full rounded-lg border border-[#454545] bg-[#202020] px-3 py-2 text-sm text-white" />
          </label>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="block text-xs text-[#a7a7b0]">自定义禁止词（每行一个）
              <textarea value={rules.custom_blocked_terms.join('\n')} onChange={(event) => updateRules({ ...rules, custom_blocked_terms: event.target.value.split('\n').map((item) => item.trim()).filter(Boolean) })} rows={5} className="mt-1 w-full rounded-lg border border-[#454545] bg-[#202020] px-3 py-2 text-sm text-white" />
            </label>
            <label className="block text-xs text-[#a7a7b0]">允许例外词（每行一个）
              <textarea value={rules.custom_allowed_terms.join('\n')} onChange={(event) => updateRules({ ...rules, custom_allowed_terms: event.target.value.split('\n').map((item) => item.trim()).filter(Boolean) })} rows={5} className="mt-1 w-full rounded-lg border border-[#454545] bg-[#202020] px-3 py-2 text-sm text-white" />
            </label>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-sky-500/30 bg-sky-500/5 p-5">
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-[260px] flex-1 text-xs text-[#a7a7b0]">发布前样例判定（不会写入审计）
            <textarea value={sampleInput} onChange={(event) => { setSampleInput(event.target.value); setPreview(null) }} rows={3} placeholder="输入一条测试问题" className="mt-1 w-full rounded-lg border border-[#454545] bg-[#202020] px-3 py-2 text-sm text-white" />
          </label>
          <button onClick={testDecision} disabled={previewing || !sampleInput.trim() || content.trim().length < 80} className="rounded-lg border border-sky-500/50 px-4 py-2 text-sm text-sky-200 hover:bg-sky-500/10 disabled:opacity-50">{previewing ? '判定中…' : '测试判定'}</button>
        </div>
        {preview && <div className="mt-3 flex flex-wrap items-center gap-2 text-xs"><span className={`rounded-full px-2 py-0.5 ${preview.decision === 'block' ? 'bg-red-500/15 text-red-300' : 'bg-emerald-500/15 text-emerald-300'}`}>{preview.decision === 'block' ? '将拦截' : '可问答'}</span><span className="text-[#d4d4d8]">{preview.reason_code}</span>{preview.categories.length > 0 && <span className="text-[#8e8ea0]">分类：{preview.categories.join('、')}</span>}<span className="text-[#777780]">v{preview.current_version} → v{preview.proposed_version}</span></div>}
      </section>

      <section className="rounded-2xl border border-[#3d3d3d] bg-[#292929] p-5">
        <h3 className="font-medium text-white">版本历史</h3>
        <p className="mb-3 mt-1 text-xs text-[#a7a7b0]">恢复历史内容时会创建新版本，不改写不可变历史。</p>
        {history.length === 0 ? <p className="text-sm text-[#8e8ea0]">当前使用内置默认宪法，尚无发布历史</p> : <div className="divide-y divide-[#3d3d3d]">{history.slice(0, 10).map((item) => <div key={item.id} className="flex flex-wrap items-center gap-3 py-2.5 text-xs"><span className={`rounded-full px-2 py-0.5 ${item.is_active ? 'bg-emerald-500/15 text-emerald-300' : 'bg-[#3a3a3a] text-[#b4b4bd]'}`}>v{item.version}{item.is_active ? ' · 当前' : ''}</span><span className="min-w-0 flex-1 truncate text-[#d4d4d8]">{item.summary}</span><span className="text-[#777780]">{item.created_at ? formatDate(item.created_at) : '-'}</span>{!item.is_active && <button onClick={() => restore(item.version)} disabled={restoring !== null} className="rounded-md border border-[#525252] px-2.5 py-1 text-[#d4d4d8] hover:border-[#10a37f] disabled:opacity-50">{restoring === item.version ? '恢复中…' : '恢复此版本'}</button>}</div>)}</div>}
      </section>

      <section className="rounded-2xl border border-[#3d3d3d] bg-[#292929] p-5">
        <h3 className="font-medium text-white">最近聊天宪法决策</h3>
        <p className="mb-3 mt-1 text-xs text-[#a7a7b0]">仅展示原因、分类与输入长度；原始问题不写入审计。</p>
        {audits.length === 0 ? <p className="text-sm text-[#8e8ea0]">暂无审计记录</p> : <div className="divide-y divide-[#3d3d3d]">{audits.slice(0, 12).map((audit) => <div key={audit.id} className="flex flex-wrap items-center gap-2 py-2 text-xs"><span className={`rounded-full px-2 py-0.5 ${audit.decision === 'block' ? 'bg-red-500/15 text-red-300' : 'bg-emerald-500/15 text-emerald-300'}`}>{audit.decision === 'block' ? '已拦截' : '已发布'}</span><span className="text-[#d4d4d8]">{audit.reason_code}</span>{audit.categories.length > 0 && <span className="text-[#8e8ea0]">{audit.categories.join('、')}</span>}<span className="text-[#777780]">{audit.source} · v{audit.constitution_version} · {audit.content_length} 字符</span><span className="ml-auto text-[#777780]">{audit.created_at ? formatDate(audit.created_at) : '-'}</span></div>)}</div>}
      </section>
    </div>
  )
}

export default function PermissionsPage() {
  const token = useAuthStore((s) => s.token)
  const role = useAuthStore((s) => s.role)

  const [users, setUsers] = useState<UserItem[]>([])
  const [activeTab, setActiveTab] = useState('pending')
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [section, setSection] = useState<'users' | 'constitution' | 'chat_constitution'>('users')
  const [constitution, setConstitution] = useState<MemoryConstitutionData | null>(null)
  const [constitutionContent, setConstitutionContent] = useState('')
  const [constitutionRules, setConstitutionRules] = useState<MemoryConstitutionRules | null>(null)
  const [constitutionAudits, setConstitutionAudits] = useState<MemoryConstitutionAuditItem[]>([])
  const [constitutionLoading, setConstitutionLoading] = useState(false)
  const [constitutionSaving, setConstitutionSaving] = useState(false)
  const [constitutionPreviewing, setConstitutionPreviewing] = useState(false)
  const [constitutionPreview, setConstitutionPreview] = useState<MemoryConstitutionPreview | null>(null)
  const [constitutionHistory, setConstitutionHistory] = useState<MemoryConstitutionHistoryItem[]>([])
  const [restoringVersion, setRestoringVersion] = useState<number | null>(null)
  const [resetTarget, setResetTarget] = useState<UserItem | null>(null)
  const [resetPassword, setResetPassword] = useState('')
  const [resetLoading, setResetLoading] = useState(false)

  async function loadUsers(status?: string) {
    if (!token) return
    setLoading(true)
    try {
      const data = await apiListUsers(token, status || undefined)
      setUsers(data.users || [])
    } catch {
      setUsers([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (section === 'users') loadUsers(activeTab || undefined)
  }, [activeTab, token, section])

  async function loadConstitution() {
    if (!token) return
    setConstitutionLoading(true)
    try {
      const [data, audits, history] = await Promise.all([
        apiGetMemoryConstitution(token),
        apiListMemoryConstitutionAudits(token),
        apiListMemoryConstitutionHistory(token),
      ])
      setConstitution(data)
      setConstitutionContent(data.content)
      setConstitutionRules(data.rules)
      setConstitutionAudits(audits)
      setConstitutionHistory(history)
      setConstitutionPreview(null)
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setConstitutionLoading(false)
    }
  }

  useEffect(() => {
    if (section === 'constitution') loadConstitution()
  }, [section, token])

  async function handleSaveConstitution() {
    if (!token || !constitutionRules) return
    setConstitutionSaving(true)
    setMessage('')
    try {
      const data = await apiUpdateMemoryConstitution(token, {
        content: constitutionContent,
        rules: constitutionRules,
        expected_version: constitution?.version ?? 0,
      })
      setConstitution(data)
      setConstitutionContent(data.content)
      setConstitutionRules(data.rules)
      setMessage(data.unchanged
        ? `记忆宪法 v${data.version} 内容未变化，无需生成新版本`
        : `记忆宪法 v${data.version} 已实时生效，已隔离 ${data.quarantined_count || 0} 条旧记忆`)
      const [audits, history] = await Promise.all([
        apiListMemoryConstitutionAudits(token),
        apiListMemoryConstitutionHistory(token),
      ])
      setConstitutionAudits(audits)
      setConstitutionHistory(history)
      setConstitutionPreview(null)
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setConstitutionSaving(false)
    }
  }

  async function handlePreviewConstitution() {
    if (!token || !constitutionRules) return
    setConstitutionPreviewing(true)
    setMessage('')
    try {
      const preview = await apiPreviewMemoryConstitution(token, {
        content: constitutionContent,
        rules: constitutionRules,
        expected_version: constitution?.version ?? 0,
      })
      setConstitutionPreview(preview)
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setConstitutionPreviewing(false)
    }
  }

  async function handleRestoreConstitution(version: number) {
    if (!token || !constitution || !confirm(`确认以 v${version} 的内容创建一个新的生效版本？`)) return
    setRestoringVersion(version)
    setMessage('')
    try {
      const data = await apiRestoreMemoryConstitution(token, version, constitution.version)
      setMessage(data.unchanged
        ? `v${version} 与当前宪法一致，无需恢复`
        : `已从 v${version} 恢复为新的 v${data.version}，并实时生效`)
      await loadConstitution()
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setRestoringVersion(null)
    }
  }

  function updateConstitutionRules(next: MemoryConstitutionRules) {
    setConstitutionRules(next)
    setConstitutionPreview(null)
  }

  function toggleCategory(category: string) {
    if (!constitutionRules || constitution?.immutable_categories.includes(category)) return
    const selected = constitutionRules.prohibited_categories.includes(category)
    updateConstitutionRules({
      ...constitutionRules,
      prohibited_categories: selected
        ? constitutionRules.prohibited_categories.filter((item) => item !== category)
        : [...constitutionRules.prohibited_categories, category],
    })
  }

  function toggleProactiveKind(kind: string) {
    if (!constitutionRules) return
    const selected = constitutionRules.allowed_proactive_kinds.includes(kind)
    updateConstitutionRules({
      ...constitutionRules,
      allowed_proactive_kinds: selected
        ? constitutionRules.allowed_proactive_kinds.filter((item) => item !== kind)
        : [...constitutionRules.allowed_proactive_kinds, kind],
    })
  }

  async function handleApprove(userId: string) {
    if (!token || !confirm('确认通过该用户的审核？')) return
    setActionLoading(userId)
    setMessage('')
    try {
      await apiApproveUser(token, userId)
      setMessage(t('permissions.approveSuccess'))
      loadUsers(activeTab || undefined)
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setActionLoading(null)
    }
  }

  async function handleDisable(userId: string) {
    if (!token || !confirm('确认禁用该用户？')) return
    setActionLoading(userId)
    setMessage('')
    try {
      await apiDisableUser(token, userId)
      setMessage(t('permissions.disableSuccess'))
      loadUsers(activeTab || undefined)
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setActionLoading(null)
    }
  }

  async function handleEnable(userId: string) {
    if (!token || !confirm('确认启用该用户？')) return
    setActionLoading(userId)
    setMessage('')
    try {
      await apiEnableUser(token, userId)
      setMessage(t('permissions.enableSuccess'))
      loadUsers(activeTab || undefined)
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setActionLoading(null)
    }
  }

  async function handleResetPassword() {
    if (!token || !resetTarget || resetPassword.length < 8) return
    setResetLoading(true)
    setMessage('')
    try {
      const result = await apiResetUserPassword(token, resetTarget.id, resetPassword)
      setMessage(result.message)
      setResetTarget(null)
      setResetPassword('')
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setResetLoading(false)
    }
  }

  if (role !== 'admin') {
    return (
      <div className="min-h-screen bg-[#212121] flex items-center justify-center px-4">
        <div className="text-center">
          <p className="text-white text-lg mb-2">{t('permissions.noAccess')}</p>
          <button
            onClick={() => window.location.href = '/chat'}
            className="text-sm text-[#10a37f] hover:underline"
          >
            {t('common.back')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#212121] px-6 py-8">
      <div className="max-w-5xl mx-auto animate-fade-in">
        <h1 className="text-2xl font-semibold text-white mb-2">{t('permissions.title')}</h1>
        <p className="mb-6 text-sm text-[#8e8ea0]">管理用户准入，以及工作区聊天和记忆的治理边界。</p>

        <div className="mb-6 inline-flex rounded-xl bg-[#2f2f2f] p-1">
          {([
            ['users', '用户权限'],
            ['constitution', '记忆宪法'],
            ['chat_constitution', '聊天宪法'],
          ] as const).map(([key, label]) => (
            <button
              key={key}
              onClick={() => { setSection(key); setMessage('') }}
              className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                section === key ? 'bg-[#10a37f] text-white' : 'text-[#b4b4bd] hover:text-white'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {message && (
          <p className={`text-sm mb-4 ${message.includes('Success') || message.includes('成功') || message.includes('已') ? 'text-green-400' : 'text-red-400'}`}>
            {message}
          </p>
        )}

        {section === 'chat_constitution' ? (
          <ChatConstitutionPanel token={token || ''} setMessage={setMessage} />
        ) : section === 'constitution' ? constitutionLoading || !constitutionRules || !constitution ? (
          <p className="text-[#8e8ea0] text-sm">{t('common.loading')}</p>
        ) : (
          <div className="space-y-5">
            <section className="rounded-2xl border border-[#3d3d3d] bg-[#292929] p-5">
              <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-semibold text-white">当前生效宪法</h2>
                    <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-300">v{constitution.version || '默认'}</span>
                  </div>
                  <p className="mt-1 text-xs text-[#a7a7b0]">每次写入与召回实时读取当前版本；安全底线不可被关闭。</p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={handlePreviewConstitution}
                    disabled={constitutionPreviewing || constitutionContent.trim().length < 80}
                    className="rounded-lg border border-[#525252] px-4 py-2 text-sm font-medium text-[#dedee3] hover:border-[#10a37f] hover:text-white disabled:opacity-50"
                  >
                    {constitutionPreviewing ? '评估中…' : '影响预览'}
                  </button>
                  <button
                    onClick={handleSaveConstitution}
                    disabled={constitutionSaving || constitutionContent.trim().length < 80}
                    className="rounded-lg bg-[#10a37f] px-4 py-2 text-sm font-medium text-white hover:bg-[#0d8c6d] disabled:opacity-50"
                  >
                    {constitutionSaving ? '发布中…' : '发布新版本'}
                  </button>
                </div>
              </div>
              <textarea
                value={constitutionContent}
                onChange={(event) => { setConstitutionContent(event.target.value); setConstitutionPreview(null) }}
                rows={12}
                className="w-full resize-y rounded-xl border border-[#454545] bg-[#202020] px-4 py-3 text-sm leading-6 text-white outline-none focus:border-[#10a37f]"
                aria-label="记忆宪法内容"
              />
              <p className="mt-2 text-xs text-[#8e8ea0]">正文会实时约束模型提取；需要确定性拦截时，可在正文加入“禁止记忆词：词语A、词语B”，或使用下方禁用词。</p>
            </section>

            {constitutionPreview && (
              <section className="rounded-2xl border border-sky-500/30 bg-sky-500/5 p-5">
                <div className="flex flex-wrap items-center gap-3">
                  <h3 className="font-medium text-white">发布影响预览</h3>
                  <span className="rounded-full bg-sky-500/15 px-2 py-0.5 text-xs text-sky-300">v{constitutionPreview.current_version} → v{constitutionPreview.proposed_version}</span>
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-xl bg-[#202020] p-3"><p className="text-xs text-[#92929b]">已扫描活动记忆</p><p className="mt-1 text-xl font-semibold text-white">{constitutionPreview.scanned_count}</p></div>
                  <div className="rounded-xl bg-[#202020] p-3"><p className="text-xs text-[#92929b]">发布后将隔离</p><p className={`mt-1 text-xl font-semibold ${constitutionPreview.would_quarantine_count ? 'text-amber-300' : 'text-emerald-300'}`}>{constitutionPreview.would_quarantine_count}</p></div>
                  <div className="rounded-xl bg-[#202020] p-3"><p className="text-xs text-[#92929b]">扫描状态</p><p className="mt-1 text-sm font-medium text-white">{constitutionPreview.scan_limited ? '已达扫描上限，召回时继续校验' : '扫描完整'}</p></div>
                </div>
                {Object.keys(constitutionPreview.category_counts).length > 0 && <p className="mt-3 text-xs text-[#a7a7b0]">命中类别：{Object.entries(constitutionPreview.category_counts).map(([category, count]) => `${category} × ${count}`).join('、')}</p>}
              </section>
            )}

            <section className="grid gap-5 md:grid-cols-2">
              <div className="rounded-2xl border border-[#3d3d3d] bg-[#292929] p-5">
                <h3 className="font-medium text-white">禁止记忆的类别</h3>
                <p className="mb-4 mt-1 text-xs text-[#a7a7b0]">锁定项属于系统安全底线；其他项可按工作区合规要求调整。</p>
                <div className="space-y-2">
                  {[...constitution.immutable_categories, ...Object.keys(constitution.editable_categories)].map((category) => {
                    const locked = constitution.immutable_categories.includes(category)
                    const checked = constitutionRules.prohibited_categories.includes(category)
                    const labels: Record<string, string> = {
                      credentials: '密码、令牌与私钥', identity_numbers: '身份号码', financial_accounts: '支付与金融账户',
                      memory_poisoning: '绕过规则或隐藏记忆的指令', third_party_personal: '第三方个人信息',
                    }
                    return (
                      <label key={category} className="flex cursor-pointer items-center justify-between gap-3 rounded-lg bg-[#222] px-3 py-2 text-sm text-[#e4e4e7]">
                        <span>{labels[category] || constitution.editable_categories[category] || category}</span>
                        <span className="flex items-center gap-2 text-xs text-[#8e8ea0]">
                          {locked && '锁定'}
                          <input type="checkbox" checked={checked} disabled={locked} onChange={() => toggleCategory(category)} className="accent-[#10a37f]" />
                        </span>
                      </label>
                    )
                  })}
                </div>
              </div>

              <div className="rounded-2xl border border-[#3d3d3d] bg-[#292929] p-5">
                <h3 className="font-medium text-white">主动学习强度</h3>
                <p className="mb-4 mt-1 text-xs text-[#a7a7b0]">限定自动学习的内容类型，并用置信度和重复观察控制自动激活。</p>
                <div className="mb-4 flex flex-wrap gap-2">
                  {(['profile', 'preference', 'workflow', 'fact', 'episodic'] as const).map((kind) => (
                    <button key={kind} onClick={() => toggleProactiveKind(kind)} className={`rounded-full border px-3 py-1.5 text-xs ${constitutionRules.allowed_proactive_kinds.includes(kind) ? 'border-[#10a37f] bg-[#10a37f]/15 text-emerald-300' : 'border-[#4a4a4a] text-[#9a9aa3]'}`}>
                      {{ profile: '用户画像', preference: '长期偏好', workflow: '工作流程', fact: '稳定事实', episodic: '事件经历' }[kind]}
                    </button>
                  ))}
                </div>
                <label className="mb-4 block text-sm text-[#d4d4d8]">
                  自动激活最低置信度：{constitutionRules.min_proactive_confidence.toFixed(2)}
                  <input type="range" min="0.6" max="1" step="0.01" value={constitutionRules.min_proactive_confidence} onChange={(event) => updateConstitutionRules({ ...constitutionRules, min_proactive_confidence: Number(event.target.value) })} className="mt-2 w-full accent-[#10a37f]" />
                </label>
                <div className="grid grid-cols-3 gap-3">
                  <label className="text-xs text-[#a7a7b0]">重复观察次数
                    <input type="number" min="1" max="3" value={constitutionRules.proactive_activation_observations} onChange={(event) => updateConstitutionRules({ ...constitutionRules, proactive_activation_observations: Number(event.target.value) })} className="mt-1 w-full rounded-lg border border-[#454545] bg-[#202020] px-3 py-2 text-sm text-white" />
                  </label>
                  <label className="text-xs text-[#a7a7b0]">保留天数
                    <input type="number" min="1" max="3650" value={constitutionRules.retention_days} onChange={(event) => updateConstitutionRules({ ...constitutionRules, retention_days: Number(event.target.value) })} className="mt-1 w-full rounded-lg border border-[#454545] bg-[#202020] px-3 py-2 text-sm text-white" />
                  </label>
                  <label className="text-xs text-[#a7a7b0]">单条最大字数
                    <input type="number" min="200" max="10000" value={constitutionRules.max_memory_chars} onChange={(event) => updateConstitutionRules({ ...constitutionRules, max_memory_chars: Number(event.target.value) })} className="mt-1 w-full rounded-lg border border-[#454545] bg-[#202020] px-3 py-2 text-sm text-white" />
                  </label>
                </div>
                <label className="mt-4 block text-xs text-[#a7a7b0]">自定义禁用词（每行一个，确定性拦截）
                  <textarea value={constitutionRules.custom_blocked_terms.join('\n')} onChange={(event) => updateConstitutionRules({ ...constitutionRules, custom_blocked_terms: event.target.value.split('\n').map((item) => item.trim()).filter(Boolean) })} rows={4} className="mt-1 w-full rounded-lg border border-[#454545] bg-[#202020] px-3 py-2 text-sm text-white" />
                </label>
              </div>
            </section>

            <section className="rounded-2xl border border-[#3d3d3d] bg-[#292929] p-5">
              <h3 className="font-medium text-white">版本历史</h3>
              <p className="mb-3 mt-1 text-xs text-[#a7a7b0]">历史版本不可修改；恢复操作会复制其内容并创建新的生效版本。</p>
              {constitutionHistory.length === 0 ? <p className="text-sm text-[#8e8ea0]">当前使用内置默认宪法，尚无发布历史</p> : (
                <div className="divide-y divide-[#3d3d3d]">
                  {constitutionHistory.slice(0, 10).map((item) => (
                    <div key={item.id} className="flex flex-wrap items-center gap-3 py-2.5 text-xs">
                      <span className={`rounded-full px-2 py-0.5 ${item.is_active ? 'bg-emerald-500/15 text-emerald-300' : 'bg-[#3a3a3a] text-[#b4b4bd]'}`}>v{item.version}{item.is_active ? ' · 当前' : ''}</span>
                      <span className="min-w-0 flex-1 truncate text-[#d4d4d8]">{item.summary}</span>
                      <span className="text-[#777780]">{item.created_at ? formatDate(item.created_at) : '-'}</span>
                      {!item.is_active && <button onClick={() => handleRestoreConstitution(item.version)} disabled={restoringVersion !== null} className="rounded-md border border-[#525252] px-2.5 py-1 text-[#d4d4d8] hover:border-[#10a37f] hover:text-white disabled:opacity-50">{restoringVersion === item.version ? '恢复中…' : '恢复此版本'}</button>}
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="rounded-2xl border border-[#3d3d3d] bg-[#292929] p-5">
              <h3 className="font-medium text-white">最近宪法决策</h3>
              <p className="mb-3 mt-1 text-xs text-[#a7a7b0]">审计记录只保留分类和内容哈希，不展示被拦截的敏感原文。</p>
              {constitutionAudits.length === 0 ? <p className="text-sm text-[#8e8ea0]">暂无审计记录</p> : (
                <div className="divide-y divide-[#3d3d3d]">
                  {constitutionAudits.slice(0, 12).map((audit) => (
                    <div key={audit.id} className="flex flex-wrap items-center gap-2 py-2 text-xs">
                      <span className={`rounded-full px-2 py-0.5 ${audit.decision === 'block' ? 'bg-red-500/15 text-red-300' : audit.decision === 'review' ? 'bg-amber-500/15 text-amber-300' : 'bg-emerald-500/15 text-emerald-300'}`}>{audit.decision === 'block' ? '已拦截' : audit.decision === 'review' ? '待确认' : '已发布'}</span>
                      <span className="text-[#d4d4d8]">{audit.reason_code}</span>
                      <span className="text-[#777780]">{audit.source} · v{audit.constitution_version}</span>
                      <span className="ml-auto text-[#777780]">{audit.created_at ? formatDate(audit.created_at) : '-'}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        ) : (
          <>
            <div className="flex gap-2 mb-6 flex-wrap">
              {STATUS_TABS.map((tab) => (
                <button key={tab.key} onClick={() => setActiveTab(tab.key)} className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${activeTab === tab.key ? 'bg-[#10a37f] text-white' : 'bg-[#2f2f2f] text-[#8e8ea0] hover:text-white'}`}>
                  {t(tab.label)}
                </button>
              ))}
            </div>
            {loading ? <p className="text-[#8e8ea0] text-sm">{t('common.loading')}</p> : users.length === 0 ? <p className="text-[#8e8ea0] text-sm">暂无数据</p> : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-left text-white">
                  <thead className="text-xs text-[#8e8ea0] uppercase bg-[#2f2f2f]"><tr><th className="px-4 py-3 rounded-l-lg">{t('permissions.email')}</th><th className="px-4 py-3">{t('permissions.displayName')}</th><th className="px-4 py-3">{t('permissions.status')}</th><th className="px-4 py-3">{t('permissions.role')}</th><th className="px-4 py-3">{t('permissions.createdAt')}</th><th className="px-4 py-3 rounded-r-lg">{t('permissions.actions')}</th></tr></thead>
                  <tbody>{users.map((u) => (
                    <tr key={u.id} className="border-b border-[#3d3d3d] hover:bg-[#2a2a2a] transition-colors">
                      <td className="px-4 py-3 font-mono text-xs">{u.email}</td><td className="px-4 py-3">{u.display_name || '-'}</td>
                      <td className="px-4 py-3"><span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[u.status] || 'bg-gray-500/20 text-gray-400'}`}>{u.status}</span></td>
                      <td className="px-4 py-3"><span className={`px-2 py-0.5 rounded-full text-xs font-medium ${ROLE_COLORS[u.role] || 'bg-gray-500/20 text-gray-400'}`}>{u.role}</span></td>
                      <td className="px-4 py-3 text-[#8e8ea0] text-xs">{formatDate(u.created_at)}</td>
                      <td className="px-4 py-3"><div className="flex gap-2">
                        {u.status === 'pending' && <button onClick={() => handleApprove(u.id)} disabled={actionLoading === u.id} className="px-3 py-1 text-xs bg-green-600 hover:bg-green-700 text-white rounded-md disabled:opacity-50">{actionLoading === u.id ? '...' : t('permissions.approve')}</button>}
                        {u.status === 'active' && u.role !== 'admin' && <button onClick={() => handleDisable(u.id)} disabled={actionLoading === u.id} className="px-3 py-1 text-xs bg-red-600 hover:bg-red-700 text-white rounded-md disabled:opacity-50">{actionLoading === u.id ? '...' : t('permissions.disable')}</button>}
                        {u.status === 'disabled' && <button onClick={() => handleEnable(u.id)} disabled={actionLoading === u.id} className="px-3 py-1 text-xs bg-blue-600 hover:bg-blue-700 text-white rounded-md disabled:opacity-50">{actionLoading === u.id ? '...' : t('permissions.enable')}</button>}
                        {u.status !== 'pending' && <button onClick={() => { setResetTarget(u); setResetPassword(''); setMessage('') }} className="px-3 py-1 text-xs border border-[#555] hover:border-[#10a37f] text-[#dedee3] rounded-md">重置密码</button>}
                      </div></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
      {resetTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 px-4" role="dialog" aria-modal="true" aria-labelledby="reset-password-title">
          <div className="w-full max-w-md rounded-2xl border border-[#454545] bg-[#292929] p-5 shadow-2xl">
            <h2 id="reset-password-title" className="text-lg font-semibold text-white">重置用户密码</h2>
            <p className="mt-1 text-sm text-[#a7a7b0]">为 {resetTarget.email} 直接设置新密码。</p>
            <label className="mt-5 block text-xs text-[#b4b4bd]">
              新密码（至少 8 位）
              <input
                autoFocus
                type="password"
                autoComplete="new-password"
                minLength={8}
                maxLength={72}
                value={resetPassword}
                onChange={(event) => setResetPassword(event.target.value)}
                onKeyDown={(event) => { if (event.key === 'Enter') void handleResetPassword() }}
                className="mt-2 w-full rounded-xl border border-[#4a4a4a] bg-[#202020] px-3 py-2.5 text-sm text-white outline-none focus:border-[#10a37f]"
              />
            </label>
            <div className="mt-5 flex justify-end gap-2">
              <button onClick={() => { setResetTarget(null); setResetPassword('') }} disabled={resetLoading} className="rounded-lg border border-[#525252] px-4 py-2 text-sm text-[#d4d4d8] disabled:opacity-50">取消</button>
              <button onClick={() => void handleResetPassword()} disabled={resetLoading || resetPassword.length < 8} className="rounded-lg bg-[#10a37f] px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{resetLoading ? '重置中…' : '确认重置'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
