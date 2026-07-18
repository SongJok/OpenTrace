import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/auth'
import {
  apiApproveUser,
  apiDisableUser,
  apiEnableUser,
  apiGetMemoryConstitution,
  apiListMemoryConstitutionAudits,
  apiListUsers,
  apiUpdateMemoryConstitution,
  type MemoryConstitutionAuditItem,
  type MemoryConstitutionData,
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

export default function PermissionsPage() {
  const token = useAuthStore((s) => s.token)
  const role = useAuthStore((s) => s.role)

  const [users, setUsers] = useState<UserItem[]>([])
  const [activeTab, setActiveTab] = useState('pending')
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [section, setSection] = useState<'users' | 'constitution'>('users')
  const [constitution, setConstitution] = useState<MemoryConstitutionData | null>(null)
  const [constitutionContent, setConstitutionContent] = useState('')
  const [constitutionRules, setConstitutionRules] = useState<MemoryConstitutionRules | null>(null)
  const [constitutionAudits, setConstitutionAudits] = useState<MemoryConstitutionAuditItem[]>([])
  const [constitutionLoading, setConstitutionLoading] = useState(false)
  const [constitutionSaving, setConstitutionSaving] = useState(false)

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
      const [data, audits] = await Promise.all([
        apiGetMemoryConstitution(token),
        apiListMemoryConstitutionAudits(token),
      ])
      setConstitution(data)
      setConstitutionContent(data.content)
      setConstitutionRules(data.rules)
      setConstitutionAudits(audits)
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
      })
      setConstitution(data)
      setConstitutionContent(data.content)
      setConstitutionRules(data.rules)
      setMessage(`记忆宪法 v${data.version} 已实时生效，已隔离 ${data.quarantined_count || 0} 条旧记忆`)
      setConstitutionAudits(await apiListMemoryConstitutionAudits(token))
    } catch (err: any) {
      setMessage(err.message)
    } finally {
      setConstitutionSaving(false)
    }
  }

  function toggleCategory(category: string) {
    if (!constitutionRules || constitution?.immutable_categories.includes(category)) return
    const selected = constitutionRules.prohibited_categories.includes(category)
    setConstitutionRules({
      ...constitutionRules,
      prohibited_categories: selected
        ? constitutionRules.prohibited_categories.filter((item) => item !== category)
        : [...constitutionRules.prohibited_categories, category],
    })
  }

  function toggleProactiveKind(kind: string) {
    if (!constitutionRules) return
    const selected = constitutionRules.allowed_proactive_kinds.includes(kind)
    setConstitutionRules({
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
        <p className="mb-6 text-sm text-[#8e8ea0]">管理用户准入，以及工作区记忆可学习、保留和召回的边界。</p>

        <div className="mb-6 inline-flex rounded-xl bg-[#2f2f2f] p-1">
          {([
            ['users', '用户权限'],
            ['constitution', '记忆宪法'],
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

        {section === 'constitution' ? constitutionLoading || !constitutionRules || !constitution ? (
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
                <button
                  onClick={handleSaveConstitution}
                  disabled={constitutionSaving || constitutionContent.trim().length < 80}
                  className="rounded-lg bg-[#10a37f] px-4 py-2 text-sm font-medium text-white hover:bg-[#0d8c6d] disabled:opacity-50"
                >
                  {constitutionSaving ? '发布中…' : '发布新版本'}
                </button>
              </div>
              <textarea
                value={constitutionContent}
                onChange={(event) => setConstitutionContent(event.target.value)}
                rows={12}
                className="w-full resize-y rounded-xl border border-[#454545] bg-[#202020] px-4 py-3 text-sm leading-6 text-white outline-none focus:border-[#10a37f]"
                aria-label="记忆宪法内容"
              />
              <p className="mt-2 text-xs text-[#8e8ea0]">正文会实时约束模型提取；需要确定性拦截时，可在正文加入“禁止记忆词：词语A、词语B”，或使用下方禁用词。</p>
            </section>

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
                  <input type="range" min="0.6" max="1" step="0.01" value={constitutionRules.min_proactive_confidence} onChange={(event) => setConstitutionRules({ ...constitutionRules, min_proactive_confidence: Number(event.target.value) })} className="mt-2 w-full accent-[#10a37f]" />
                </label>
                <div className="grid grid-cols-3 gap-3">
                  <label className="text-xs text-[#a7a7b0]">重复观察次数
                    <input type="number" min="1" max="3" value={constitutionRules.proactive_activation_observations} onChange={(event) => setConstitutionRules({ ...constitutionRules, proactive_activation_observations: Number(event.target.value) })} className="mt-1 w-full rounded-lg border border-[#454545] bg-[#202020] px-3 py-2 text-sm text-white" />
                  </label>
                  <label className="text-xs text-[#a7a7b0]">保留天数
                    <input type="number" min="1" max="3650" value={constitutionRules.retention_days} onChange={(event) => setConstitutionRules({ ...constitutionRules, retention_days: Number(event.target.value) })} className="mt-1 w-full rounded-lg border border-[#454545] bg-[#202020] px-3 py-2 text-sm text-white" />
                  </label>
                  <label className="text-xs text-[#a7a7b0]">单条最大字数
                    <input type="number" min="200" max="10000" value={constitutionRules.max_memory_chars} onChange={(event) => setConstitutionRules({ ...constitutionRules, max_memory_chars: Number(event.target.value) })} className="mt-1 w-full rounded-lg border border-[#454545] bg-[#202020] px-3 py-2 text-sm text-white" />
                  </label>
                </div>
                <label className="mt-4 block text-xs text-[#a7a7b0]">自定义禁用词（每行一个，确定性拦截）
                  <textarea value={constitutionRules.custom_blocked_terms.join('\n')} onChange={(event) => setConstitutionRules({ ...constitutionRules, custom_blocked_terms: event.target.value.split('\n').map((item) => item.trim()).filter(Boolean) })} rows={4} className="mt-1 w-full rounded-lg border border-[#454545] bg-[#202020] px-3 py-2 text-sm text-white" />
                </label>
              </div>
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
                      </div></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
