import { useEffect } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { useAuthStore } from './store/auth'
import { applyTheme, useThemeStore } from './store/theme'
import ChatPage from './pages/ChatPage'
import DocumentsPage from './pages/DocumentsPage'
import LoginPage from './pages/LoginPage'
import SettingsPage from './pages/SettingsPage'
import TasksPage from './pages/TasksPage'
import AuditPage from './pages/AuditPage'
import MemoryPage from './pages/MemoryPage'
import IntegrationsPage from './pages/IntegrationsPage'
import DatabasesPage from './pages/DatabasesPage'
import SkillsPage from './pages/SkillsPage'

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
    <Routes>
      <Route path="/login" element={token ? <Navigate to="/chat" replace /> : <LoginPage />} />

      <Route path="/" element={<Navigate to="/chat" replace />} />
      <Route path="/chat" element={<Protected><ChatPage /></Protected>} />
      <Route path="/documents" element={<Protected><DocumentsRoute /></Protected>} />
      <Route path="/settings" element={<Protected><SettingsRoute /></Protected>} />
      <Route path="/tasks" element={<Protected><TasksRoute /></Protected>} />
      <Route path="/audit" element={<Protected><AuditRoute /></Protected>} />
      <Route path="/memories" element={<Protected><MemoryRoute /></Protected>} />
      <Route path="/integrations" element={<Protected><IntegrationsRoute /></Protected>} />
      <Route path="/databases" element={<Protected><DatabasesRoute /></Protected>} />
      <Route path="/skills" element={<Protected><SkillsRoute /></Protected>} />

      <Route path="*" element={<Navigate to={token ? '/chat' : '/login'} replace />} />
    </Routes>
  )
}
