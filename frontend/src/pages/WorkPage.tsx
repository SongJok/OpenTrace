import { useEffect, useState } from 'react'
import { Ban, ChevronLeft, FolderKanban, Pause, Play, Plus, Target } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import { apiCreateAssistantProfile, apiCreateGoal, apiCreateProject, apiGoalAction, apiListAssistantProfiles, apiListGoals, apiListProjects, type AssistantProfileItem, type GoalItem, type ProjectItem } from '../api/client'

export default function WorkPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((state) => state.token)!
  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [goals, setGoals] = useState<GoalItem[]>([])
  const [profiles, setProfiles] = useState<AssistantProfileItem[]>([])
  const [projectName, setProjectName] = useState('')
  const [projectInstructions, setProjectInstructions] = useState('')
  const [objective, setObjective] = useState('')
  const [successCriteria, setSuccessCriteria] = useState('')
  const [projectId, setProjectId] = useState<string>('')
  const [profileName, setProfileName] = useState('')
  const [profileInstructions, setProfileInstructions] = useState('')
  const [personality, setPersonality] = useState<'none' | 'friendly' | 'pragmatic'>('none')

  const load = async () => {
    const [nextProjects, nextGoals, nextProfiles] = await Promise.all([apiListProjects(token), apiListGoals(token), apiListAssistantProfiles(token)])
    setProjects(nextProjects)
    setGoals(nextGoals)
    setProfiles(nextProfiles)
  }
  useEffect(() => { void load() }, [])

  const goalAction = async (goalId: string, action: 'pause' | 'resume' | 'cancel') => {
    await apiGoalAction(token, goalId, action)
    await load()
  }

  return (
    <div className="flex h-screen flex-col bg-[var(--bg)] text-[var(--text)]">
      <header className="flex h-14 items-center gap-3 border-b border-[var(--border)] px-6">
        <button onClick={onBack} className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-[var(--surface)]"><ChevronLeft size={18} /></button>
        <div><h1 className="text-sm font-semibold">Projects 与 Goals</h1><p className="text-xs text-[var(--text-secondary)]">组织上下文，并让长期目标可暂停、恢复和审计。</p></div>
      </header>
      <main className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 gap-6 overflow-auto p-6 xl:grid-cols-3">
        <section>
          <div className="mb-3 flex items-center gap-2"><FolderKanban size={17} /><h2 className="font-medium">Projects</h2></div>
          <div className="mb-4 space-y-2"><input value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="Project 名称" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /><textarea value={projectInstructions} onChange={(event) => setProjectInstructions(event.target.value)} rows={3} placeholder="Project 指令（可选）" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /><button onClick={() => void apiCreateProject(token, { name: projectName, description: '', instructions: projectInstructions, data_source_ids: [] }).then(() => { setProjectName(''); setProjectInstructions(''); return load() })} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-3 py-2 text-sm text-white"><Plus size={15} />新建 Project</button></div>
          <div className="space-y-3">{projects.map((project) => <article key={project.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><h3 className="font-medium">{project.name}</h3><p className="mt-1 text-sm text-[var(--text-secondary)]">{project.description || '独立指令、会话和记忆空间'}</p></article>)}</div>
        </section>
        <section>
          <div className="mb-3 flex items-center gap-2"><h2 className="font-medium">Assistant Profiles</h2></div>
          <div className="mb-4 space-y-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><input value={profileName} onChange={(event) => setProfileName(event.target.value)} placeholder="角色名称" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /><select value={personality} onChange={(event) => setPersonality(event.target.value as typeof personality)} className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-sm"><option value="none">中性</option><option value="friendly">友好</option><option value="pragmatic">务实</option></select><textarea value={profileInstructions} onChange={(event) => setProfileInstructions(event.target.value)} rows={3} placeholder="自定义角色指令" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /><button onClick={() => void apiCreateAssistantProfile(token, { name: profileName, personality, instructions: profileInstructions, default_model_profile: 'auto', tool_policy: {}, memory_policy: {}, is_default: false }).then(() => { setProfileName(''); setProfileInstructions(''); return load() })} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-3 py-2 text-sm text-white"><Plus size={15} />新建角色</button></div>
          <div className="space-y-3">{profiles.map((profile) => <article key={profile.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-center justify-between gap-2"><h3 className="font-medium">{profile.name}</h3>{profile.built_in && <span className="text-xs text-[var(--text-secondary)]">内置</span>}</div><p className="mt-1 text-sm text-[var(--text-secondary)]">{profile.personality} · {profile.default_model_profile}</p></article>)}</div>
        </section>
        <section>
          <div className="mb-3 flex items-center gap-2"><Target size={17} /><h2 className="font-medium">Goals</h2></div>
          <div className="mb-4 space-y-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><textarea value={objective} onChange={(event) => setObjective(event.target.value)} rows={4} placeholder="描述需要持续推进的目标" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /><input value={successCriteria} onChange={(event) => setSuccessCriteria(event.target.value)} placeholder="成功标准" className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /><select value={projectId} onChange={(event) => setProjectId(event.target.value)} className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-sm"><option value="">不绑定 Project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select><button onClick={() => void apiCreateGoal(token, { objective, success_criteria: successCriteria, project_id: projectId || undefined, execution_profile: 'deep' }).then(() => { setObjective(''); setSuccessCriteria(''); return load() })} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-white"><Plus size={15} />启动 Goal</button></div>
          <div className="space-y-3">{goals.map((goal) => <article key={goal.id} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="flex items-start justify-between gap-3"><h3 className="font-medium">{goal.objective}</h3><span className="rounded-full border border-[var(--border)] px-2 py-1 text-xs">{goal.status}</span></div><p className="mt-2 text-xs text-[var(--text-secondary)]">检查点 {goal.current_step} · Response {goal.response_id || '排队中'}</p><div className="mt-3 flex gap-2">{['queued','in_progress','requires_action'].includes(goal.status) && <button onClick={() => void goalAction(goal.id, 'pause')} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2 py-1 text-xs"><Pause size={12} />暂停</button>}{goal.status === 'paused' && <button onClick={() => void goalAction(goal.id, 'resume')} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2 py-1 text-xs"><Play size={12} />恢复</button>}{!['completed','cancelled'].includes(goal.status) && <button onClick={() => void goalAction(goal.id, 'cancel')} className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 px-2 py-1 text-xs text-red-500"><Ban size={12} />取消</button>}</div></article>)}</div>
        </section>
      </main>
    </div>
  )
}
