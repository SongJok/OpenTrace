import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { useAuthStore } from './store/auth'
import { applyTheme, useThemeStore } from './store/theme'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'

// 登录和注册页保持同步加载，业务页面按路由拆包，避免新用户首访下载整套工作台。
const ChatPage = lazy(() => import('./pages/ChatPage'))
const DocumentsPage = lazy(() => import('./pages/DocumentsPage'))
const PermissionsPage = lazy(() => import('./pages/PermissionsPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const TasksPage = lazy(() => import('./pages/TasksPage'))
const AuditPage = lazy(() => import('./pages/AuditPage'))
const MemoryPage = lazy(() => import('./pages/MemoryPage'))
const IntegrationsPage = lazy(() => import('./pages/IntegrationsPage'))
const DatabasesPage = lazy(() => import('./pages/DatabasesPage'))
const SkillsPage = lazy(() => import('./pages/SkillsPage'))
const RulesPage = lazy(() => import('./pages/RulesPage'))
const KnowledgeCenterPage = lazy(() => import('./pages/KnowledgeCenterPage'))
const EnterpriseKnowledgePage = lazy(() => import('./pages/EnterpriseKnowledgePage'))
const SharedConversationPage = lazy(() => import('./pages/SharedConversationPage'))
const WorkPage = lazy(() => import('./pages/WorkPage'))
const AlertsPage = lazy(() => import('./pages/AlertsPage'))
const EnterpriseAdminPage = lazy(() => import('./pages/EnterpriseAdminPage'))
const CalendarPage = lazy(() => import('./pages/CalendarPage'))

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

function WorkRoute() {
  const navigate = useNavigate()
  return <WorkPage onBack={() => navigate('/chat')} />
}

function AuditRoute() {
  const navigate = useNavigate()
  return <AuditPage onBack={() => navigate('/chat')} />
}

function MemoryRoute() {
  const navigate = useNavigate()
  return <MemoryPage onBack={() => navigate('/chat')} />
}

function IntegrationsRoute() {
  const navigate = useNavigate()
  return <IntegrationsPage onBack={() => navigate('/chat')} />
}

function DatabasesRoute() {
  const navigate = useNavigate()
  return <DatabasesPage onBack={() => navigate('/chat')} />
}

function SkillsRoute() {
  const navigate = useNavigate()
  return <SkillsPage onBack={() => navigate('/chat')} />
}

function RulesRoute() {
  const navigate = useNavigate()
  return <RulesPage onBack={() => navigate('/chat')} />
}

function KnowledgeRoute() {
  const navigate = useNavigate()
  return <KnowledgeCenterPage onBack={() => navigate('/chat')} />
}

function EnterpriseKnowledgeRoute() {
  const navigate = useNavigate()
  return <EnterpriseKnowledgePage onBack={() => navigate('/chat')} />
}

function AlertsRoute() {
  const navigate = useNavigate()
  return <AlertsPage onBack={() => navigate('/chat')} />
}

function EnterpriseAdminRoute() {
  const navigate = useNavigate()
  return <EnterpriseAdminPage onBack={() => navigate('/work')} />
}

function CalendarRoute() {
  const navigate = useNavigate()
  return <CalendarPage onBack={() => navigate('/chat')} />
}


export default function App() {
  const token = useAuthStore((s) => s.token)
  const mode = useThemeStore((s) => s.mode)
  const accent = useThemeStore((s) => s.accent)

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
        <Route path="/login" element={token ? <Navigate to="/work" replace /> : <LoginPage />} />
        <Route path="/register" element={token ? <Navigate to="/work" replace /> : <RegisterPage />} />

        <Route path="/" element={<Navigate to="/work" replace />} />
        <Route path="/chat" element={<Protected><ChatPage /></Protected>} />
        <Route path="/share/:publicId/:token" element={<SharedConversationPage />} />
        <Route path="/documents" element={<Protected><DocumentsRoute /></Protected>} />
        <Route path="/settings" element={<Protected><SettingsRoute /></Protected>} />
        <Route path="/tasks" element={<Protected><TasksRoute /></Protected>} />
        <Route path="/calendar" element={<Protected><CalendarRoute /></Protected>} />
        <Route path="/work" element={<Protected><WorkRoute /></Protected>} />
        <Route path="/audit" element={<Protected><AuditRoute /></Protected>} />
        <Route path="/memories" element={<Protected><MemoryRoute /></Protected>} />
        <Route path="/integrations" element={<Protected><IntegrationsRoute /></Protected>} />
        <Route path="/databases" element={<Protected><DatabasesRoute /></Protected>} />
        <Route path="/skills" element={<Protected><SkillsRoute /></Protected>} />
        <Route path="/rules" element={<Protected><RulesRoute /></Protected>} />
        <Route path="/knowledge-base" element={<Protected><EnterpriseKnowledgeRoute /></Protected>} />
        <Route path="/knowledge" element={<Protected><KnowledgeRoute /></Protected>} />
        <Route path="/alerts" element={<Protected><AlertsRoute /></Protected>} />
        <Route path="/permissions" element={<Protected><PermissionsPage /></Protected>} />
        <Route path="/enterprise-admin" element={<Protected><EnterpriseAdminRoute /></Protected>} />

        <Route path="*" element={<Navigate to={token ? '/work' : '/login'} replace />} />
      </Routes>
    </Suspense>
  )
}
