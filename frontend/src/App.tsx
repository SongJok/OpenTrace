import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { useAuthStore } from './store/auth'
import { applyTheme, useThemeStore } from './store/theme'
import { apiGetCompanyProfile } from './api/client'
import { useCompanyStore } from './store/company'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'

// 登录和注册页保持同步加载，业务页面按路由拆包，避免新用户首访下载所有管理页面。
const ChatPage = lazy(() => import('./pages/ChatPage'))
const DocumentsPage = lazy(() => import('./pages/DocumentsPage'))
const PermissionsPage = lazy(() => import('./pages/PermissionsPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const TasksPage = lazy(() => import('./pages/TasksPage'))
const MemoryPage = lazy(() => import('./pages/MemoryPage'))
const DatabasesPage = lazy(() => import('./pages/DatabasesPage'))
const SkillsPage = lazy(() => import('./pages/SkillsPage'))
const KnowledgeCenterPage = lazy(() => import('./pages/KnowledgeCenterPage'))
const EnterpriseKnowledgePage = lazy(() => import('./pages/EnterpriseKnowledgePage'))
const SharedConversationPage = lazy(() => import('./pages/SharedConversationPage'))
const CompanyBrainPage = lazy(() => import('./pages/CompanyBrainPage'))

function RouteLoading() {
  return (
    <div
      className="grid min-h-screen place-items-center bg-[var(--bg)] text-sm text-[var(--text-secondary)]"
      role="status"
      aria-live="polite"
    >
      正在加载…
    </div>
  )
}

function Protected({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token)
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function AdminProtected({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token)
  const role = useAuthStore((s) => s.role)
  if (!token) return <Navigate to="/login" replace />
  if (role !== 'admin') return <Navigate to="/chat" replace />
  return <>{children}</>
}

function DocumentsRoute() {
  const navigate = useNavigate()
  return <DocumentsPage onBack={() => navigate('/chat')} />
}

function SettingsRoute() {
  const navigate = useNavigate()
  return <SettingsPage onBack={() => navigate('/chat')} />
}

function TasksRoute() {
  const navigate = useNavigate()
  return <TasksPage onBack={() => navigate('/chat')} />
}

function MemoryRoute() {
  const navigate = useNavigate()
  return <MemoryPage onBack={() => navigate('/chat')} />
}

function DatabasesRoute() {
  const navigate = useNavigate()
  return <DatabasesPage onBack={() => navigate('/chat')} />
}

function SkillsRoute() {
  const navigate = useNavigate()
  return <SkillsPage onBack={() => navigate('/chat')} />
}

function KnowledgeRoute() {
  const navigate = useNavigate()
  return <KnowledgeCenterPage onBack={() => navigate('/chat')} />
}

function EnterpriseKnowledgeRoute() {
  const navigate = useNavigate()
  return <EnterpriseKnowledgePage onBack={() => navigate('/chat')} />
}

function CompanyBrainRoute() {
  const navigate = useNavigate()
  return <CompanyBrainPage onBack={() => navigate('/chat')} />
}


export default function App() {
  const token = useAuthStore((s) => s.token)
  const mode = useThemeStore((s) => s.mode)
  const accent = useThemeStore((s) => s.accent)
  const brandName = useCompanyStore((s) => s.brandName)
  const setCompanyProfile = useCompanyStore((s) => s.setProfile)

  useEffect(() => {
    void apiGetCompanyProfile().then(setCompanyProfile).catch(() => undefined)
  }, [setCompanyProfile, token])

  useEffect(() => {
    document.title = brandName
  }, [brandName])

  useEffect(() => {
    applyTheme(mode, accent)
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => {
      if (mode === 'system') applyTheme('system', accent)
    }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [mode, accent])

  return (
    <Suspense fallback={<RouteLoading />}>
      <Routes>
        <Route path="/login" element={token ? <Navigate to="/chat" replace /> : <LoginPage />} />
        <Route path="/register" element={token ? <Navigate to="/chat" replace /> : <RegisterPage />} />

        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={<Protected><ChatPage /></Protected>} />
        <Route path="/share/:publicId/:token" element={<SharedConversationPage />} />
        <Route path="/documents" element={<Protected><DocumentsRoute /></Protected>} />
        <Route path="/settings" element={<Protected><SettingsRoute /></Protected>} />
        <Route path="/tasks" element={<Protected><TasksRoute /></Protected>} />
        <Route path="/memories" element={<Protected><MemoryRoute /></Protected>} />
        <Route path="/databases" element={<Protected><DatabasesRoute /></Protected>} />
        <Route path="/skills" element={<Protected><SkillsRoute /></Protected>} />
        <Route path="/company-brain" element={<AdminProtected><CompanyBrainRoute /></AdminProtected>} />
        <Route path="/knowledge-base" element={<AdminProtected><EnterpriseKnowledgeRoute /></AdminProtected>} />
        <Route path="/knowledge" element={<AdminProtected><KnowledgeRoute /></AdminProtected>} />
        <Route path="/permissions" element={<AdminProtected><PermissionsPage /></AdminProtected>} />

        <Route path="*" element={<Navigate to={token ? '/chat' : '/login'} replace />} />
      </Routes>
    </Suspense>
  )
}
