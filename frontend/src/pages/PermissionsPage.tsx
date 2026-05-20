import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/auth'
import { apiListUsers, apiApproveUser, apiDisableUser, apiEnableUser } from '../api/client'
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
    loadUsers(activeTab || undefined)
  }, [activeTab, token])

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
        <h1 className="text-2xl font-semibold text-white mb-6">{t('permissions.title')}</h1>

        {/* Tab bar */}
        <div className="flex gap-2 mb-6 flex-wrap">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                activeTab === tab.key
                  ? 'bg-[#10a37f] text-white'
                  : 'bg-[#2f2f2f] text-[#8e8ea0] hover:text-white'
              }`}
            >
              {t(tab.label)}
            </button>
          ))}
        </div>

        {message && (
          <p className={`text-sm mb-4 ${message.includes('Success') || message.includes('成功') || message.includes('已') ? 'text-green-400' : 'text-red-400'}`}>
            {message}
          </p>
        )}

        {loading ? (
          <p className="text-[#8e8ea0] text-sm">{t('common.loading')}</p>
        ) : users.length === 0 ? (
          <p className="text-[#8e8ea0] text-sm">暂无数据</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left text-white">
              <thead className="text-xs text-[#8e8ea0] uppercase bg-[#2f2f2f]">
                <tr>
                  <th className="px-4 py-3 rounded-l-lg">{t('permissions.email')}</th>
                  <th className="px-4 py-3">{t('permissions.displayName')}</th>
                  <th className="px-4 py-3">{t('permissions.status')}</th>
                  <th className="px-4 py-3">{t('permissions.role')}</th>
                  <th className="px-4 py-3">{t('permissions.createdAt')}</th>
                  <th className="px-4 py-3 rounded-r-lg">{t('permissions.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b border-[#3d3d3d] hover:bg-[#2a2a2a] transition-colors">
                    <td className="px-4 py-3 font-mono text-xs">{u.email}</td>
                    <td className="px-4 py-3">{u.display_name || '-'}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[u.status] || 'bg-gray-500/20 text-gray-400'}`}>
                        {u.status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${ROLE_COLORS[u.role] || 'bg-gray-500/20 text-gray-400'}`}>
                        {u.role}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[#8e8ea0] text-xs">{formatDate(u.created_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2">
                        {u.status === 'pending' && (
                          <button
                            onClick={() => handleApprove(u.id)}
                            disabled={actionLoading === u.id}
                            className="px-3 py-1 text-xs bg-green-600 hover:bg-green-700 text-white rounded-md transition-colors disabled:opacity-50"
                          >
                            {actionLoading === u.id ? '...' : t('permissions.approve')}
                          </button>
                        )}
                        {u.status === 'active' && u.role !== 'admin' && (
                          <button
                            onClick={() => handleDisable(u.id)}
                            disabled={actionLoading === u.id}
                            className="px-3 py-1 text-xs bg-red-600 hover:bg-red-700 text-white rounded-md transition-colors disabled:opacity-50"
                          >
                            {actionLoading === u.id ? '...' : t('permissions.disable')}
                          </button>
                        )}
                        {u.status === 'disabled' && (
                          <button
                            onClick={() => handleEnable(u.id)}
                            disabled={actionLoading === u.id}
                            className="px-3 py-1 text-xs bg-blue-600 hover:bg-blue-700 text-white rounded-md transition-colors disabled:opacity-50"
                          >
                            {actionLoading === u.id ? '...' : t('permissions.enable')}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
