import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, Wrench, Plus, Trash2, Play, Save, Code, FileText, TestTube, Download, Power, Search, ShieldCheck, Star, RefreshCw, ExternalLink, PackageCheck, ArrowRight, BadgeCheck, Boxes, Building2, FolderOpen, UploadCloud } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import { useChatStore } from '../store/chat'
import {
  apiListSkills,
  apiCreateSkill,
  apiGetSkill,
  apiTestSkill,
  apiUninstallSkill,
  apiInstallSkill,
  apiGetSessionSkills,
  apiSetSessionSkills,
  apiListSkillCatalog,
  apiListMyInstalledSkills,
  apiListAdminSkillCatalog,
  apiInstallCatalogSkill,
  apiUninstallCatalogSkill,
  apiSyncSkillCatalog,
  apiSetCatalogSkillAvailability,
  apiListConversations,
  apiDistillCompanySkill,
  apiListCompanySkills,
  type SkillItem,
  type SkillCatalogItem,
  type SkillCatalogSyncPolicy,
  type ConversationItem,
  type EnterpriseSkillItem,
} from '../api/client'

type ViewMode = 'list' | 'create' | 'detail' | 'test' | 'distill'
type MarketplaceTab = 'discover' | 'search' | 'installed' | 'developer'
type CatalogCategory = '全部' | '办公效率' | '数据分析' | '开发工具' | '搜索研究' | '内容创作' | '自动化'

export default function SkillsPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((s) => s.token)!
  const role = useAuthStore((s) => s.role)
  const activeSessionId = useChatStore((s) => s.activeId)
  const setActiveSessionId = useChatStore((s) => s.setActiveId)
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [view, setView] = useState<ViewMode>('list')
  const [selectedSkill, setSelectedSkill] = useState<SkillItem | null>(null)
  const [output, setOutput] = useState('')
  const [loading, setLoading] = useState(false)
  const [enabledSkills, setEnabledSkills] = useState<string[]>([])
  const [disabledSkills, setDisabledSkills] = useState<string[]>([])
  const [gitUrl, setGitUrl] = useState('')
  const [gitRef, setGitRef] = useState('main')
  const [popularCatalog, setPopularCatalog] = useState<SkillCatalogItem[]>([])
  const [recentCatalog, setRecentCatalog] = useState<SkillCatalogItem[]>([])
  const [accountCatalog, setAccountCatalog] = useState<SkillCatalogItem[]>([])
  const [adminCatalog, setAdminCatalog] = useState<SkillCatalogItem[]>([])
  const [catalogPolicy, setCatalogPolicy] = useState<SkillCatalogSyncPolicy | null>(null)
  const [catalogSort, setCatalogSort] = useState<'popular' | 'recent'>('popular')
  const [catalogQuery, setCatalogQuery] = useState('')
  const [busyCatalogId, setBusyCatalogId] = useState<string | null>(null)
  const [marketplaceTab, setMarketplaceTab] = useState<MarketplaceTab>('discover')
  const [category, setCategory] = useState<CatalogCategory>('全部')
  const [sessionChoices, setSessionChoices] = useState<ConversationItem[]>([])
  const [companySkills, setCompanySkills] = useState<EnterpriseSkillItem[]>([])
  const [distillName, setDistillName] = useState('')
  const [distillDescription, setDistillDescription] = useState('')
  const [distillClassification, setDistillClassification] = useState<EnterpriseSkillItem['classification']>('internal')
  const [distillFiles, setDistillFiles] = useState<File[]>([])

  // Create form
  const [name, setName] = useState('')
  const [version, setVersion] = useState('0.1.0')
  const [entrypoint, setEntrypoint] = useState('main.py')
  const [code, setCode] = useState('')
  const [description, setDescription] = useState('')
  const [skillType, setSkillType] = useState('generic')
  const [testCasesJson, setTestCasesJson] = useState('')
  const [dataSourceId, setDataSourceId] = useState('')

  // Test form
  const [testInputJson, setTestInputJson] = useState('{}')

  const load = async () => {
    try {
      const [popular, recent, installed, published] = await Promise.all([
        apiListSkillCatalog(token, 'popular', catalogQuery),
        apiListSkillCatalog(token, 'recent', catalogQuery),
        apiListMyInstalledSkills(token),
        apiListCompanySkills(token),
      ])
      setPopularCatalog(popular)
      setRecentCatalog(recent)
      setAccountCatalog(installed)
      setCompanySkills(published)
      if (role === 'admin') {
        const [ss, governance] = await Promise.all([apiListSkills(token), apiListAdminSkillCatalog(token)])
        setSkills(Array.isArray(ss) ? ss : [])
        setAdminCatalog(governance.items)
        setCatalogPolicy(governance.policy)
      } else setSkills([])
      if (activeSessionId) {
        const binding = await apiGetSessionSkills(token, activeSessionId)
        setEnabledSkills(binding.enabled_skills)
        setDisabledSkills(binding.disabled_skills)
      } else {
        setEnabledSkills([])
        setDisabledSkills([])
      }
    } catch (e) {
      console.error('load skills failed', e)
      setSkills([])
    }
  }

  useEffect(() => {
    let cancelled = false
    void apiListConversations(token).then((items) => {
      if (cancelled) return
      setSessionChoices(items)
      const requestedSessionId = new URLSearchParams(window.location.search).get('session')
      const resolvedSessionId = resolveSkillSessionId(requestedSessionId, useChatStore.getState().activeId, items)
      if (resolvedSessionId !== useChatStore.getState().activeId) setActiveSessionId(resolvedSessionId)
    }).catch((error) => {
      if (!cancelled) console.error('load skill sessions failed', error)
    })
    return () => { cancelled = true }
  }, [token, setActiveSessionId])

  useEffect(() => {
    void load()
  }, [activeSessionId])

  const refreshCatalog = async (query = catalogQuery) => {
    try {
      const [popular, recent, installed] = await Promise.all([
        apiListSkillCatalog(token, 'popular', query),
        apiListSkillCatalog(token, 'recent', query),
        apiListMyInstalledSkills(token),
      ])
      setPopularCatalog(popular)
      setRecentCatalog(recent)
      setAccountCatalog(installed)
      if (role === 'admin') {
        const governance = await apiListAdminSkillCatalog(token)
        setAdminCatalog(governance.items)
        setCatalogPolicy(governance.policy)
      }
    } catch (e: any) { setOutput(`读取 SkillHub 失败：${e?.message || e}`) }
  }

  const syncCatalog = async () => {
    setLoading(true)
    try {
      const result = await apiSyncSkillCatalog(token)
      await refreshCatalog()
      const synced = result?.synced || {}
      setOutput(`目录同步完成：新增 ${synced.added ?? 0}，更新 ${synced.updated ?? 0}，保留停用 ${synced.preserved_disabled ?? 0}。`)
    } catch (e: any) { setOutput(`同步 SkillHub 失败：${e?.message || e}`) }
    finally { setLoading(false) }
  }

  const setCatalogAvailability = async (item: SkillCatalogItem) => {
    setBusyCatalogId(item.id)
    const enabled = item.platform_disabled
    try {
      await apiSetCatalogSkillAvailability(token, item.id, enabled, enabled ? '' : '管理员暂停平台使用')
      await refreshCatalog()
      setOutput(`${item.name} 已${enabled ? '恢复使用' : '暂停使用'}；目录记录将永久保留。`)
    } catch (e: any) { setOutput(`更新 Skill 状态失败：${e?.message || e}`) }
    finally { setBusyCatalogId(null) }
  }

  const installCatalog = async (item: SkillCatalogItem) => {
    setBusyCatalogId(item.id)
    try {
      await apiInstallCatalogSkill(token, item.id)
      setOutput(`已将 ${item.name} 安装到当前账户；需要时可为当前会话启用。`)
      await load()
    } catch (e: any) { setOutput(`安装失败：${e?.message || e}`) }
    finally { setBusyCatalogId(null) }
  }

  const uninstallCatalog = async (item: SkillCatalogItem) => {
    if (!item.installation_id) return
    setBusyCatalogId(item.id)
    try { await apiUninstallCatalogSkill(token, item.installation_id); await load() }
    catch (e: any) { setOutput(`卸载失败：${e?.message || e}`) }
    finally { setBusyCatalogId(null) }
  }

  const handleInstall = async () => {
    if (!gitUrl.trim()) return
    setLoading(true)
    setOutput('')
    try {
      await apiInstallSkill(token, gitUrl.trim(), gitRef.trim() || 'main')
      setGitUrl('')
      setGitRef('main')
      setOutput('Skill 已安装。请先测试，再为当前会话启用。')
      await load()
    } catch (e: any) {
      setOutput(`安装失败：${e?.message || e}`)
    } finally {
      setLoading(false)
    }
  }

  const toggleSessionSkill = async (skillId: string) => {
    if (!activeSessionId) return
    const currentlyEnabled = enabledSkills.includes(skillId)
    const nextEnabled = currentlyEnabled
      ? enabledSkills.filter((id) => id !== skillId)
      : [...new Set([...enabledSkills, skillId])]
    const nextDisabled = currentlyEnabled
      ? [...new Set([...disabledSkills, skillId])]
      : disabledSkills.filter((id) => id !== skillId)
    try {
      const result = await apiSetSessionSkills(token, activeSessionId, nextEnabled, nextDisabled)
      setEnabledSkills(result.enabled_skills)
      setDisabledSkills(result.disabled_skills)
    } catch (e: any) {
      setOutput(`会话配置保存失败：${e?.message || e}`)
    }
  }

  const resetCreateForm = () => {
    setName('')
    setVersion('0.1.0')
    setEntrypoint('main.py')
    setCode('')
    setDescription('')
    setSkillType('generic')
    setTestCasesJson('')
    setDataSourceId('')
  }

  const handleCreate = async () => {
    if (!name.trim()) return
    setLoading(true)
    setOutput('')
    try {
      const testCases = testCasesJson.trim() ? JSON.parse(testCasesJson) : []
      await apiCreateSkill(token, {
        name: name.trim(),
        version: version.trim() || '0.1.0',
        entrypoint: entrypoint.trim() || 'main.py',
        code: code,
        description: description.trim(),
        skill_type: skillType,
        test_cases: testCases,
        data_source_id: dataSourceId.trim(),
      })
      setOutput('Skill created successfully!')
      resetCreateForm()
      await load()
      setView('list')
    } catch (e: any) {
      setOutput(`Create failed: ${e?.message || e}`)
    } finally {
      setLoading(false)
    }
  }

  const handleDistill = async () => {
    if (!distillName.trim() || !distillFiles.length) return
    setLoading(true)
    setOutput('')
    try {
      const result = await apiDistillCompanySkill(token, {
        name: distillName.trim(),
        description: distillDescription.trim(),
        classification: distillClassification,
        files: distillFiles,
        paths: distillFiles.map((file) => file.webkitRelativePath || file.name),
      })
      setOutput(result.deduplicated ? '相同来源已蒸馏过，已返回现有公司 Skill。' : '蒸馏完成，新的 Skill 已作为“公司发布”展示。')
      setDistillName('')
      setDistillDescription('')
      setDistillFiles([])
      await load()
      setView('list')
      setMarketplaceTab('discover')
    } catch (e: any) {
      setOutput(`蒸馏失败：${e?.message || e}`)
    } finally {
      setLoading(false)
    }
  }

  const handleSelectSkill = async (skill: SkillItem) => {
    setLoading(true)
    try {
      const detail = await apiGetSkill(token, skill.skill_id || skill.id)
      setSelectedSkill(detail)
      setView('detail')
      setOutput('')
    } catch (e: any) {
      setOutput(`Failed to load skill: ${e?.message || e}`)
    } finally {
      setLoading(false)
    }
  }

  const handleUninstall = async (id: string) => {
    try {
      await apiUninstallSkill(token, id)
      await load()
      if (selectedSkill && (selectedSkill.skill_id === id || selectedSkill.id === id)) {
        setSelectedSkill(null)
        setView('list')
      }
    } catch (e: any) {
      setOutput(`Uninstall failed: ${e?.message || e}`)
    }
  }

  const handleTest = async () => {
    if (!selectedSkill) return
    setLoading(true)
    setOutput('')
    try {
      const input = JSON.parse(testInputJson)
      const result = await apiTestSkill(token, selectedSkill.skill_id || selectedSkill.id, input)
      setOutput(JSON.stringify(result.result, null, 2))
    } catch (e: any) {
      setOutput(`Test failed: ${e?.message || e}`)
    } finally {
      setLoading(false)
    }
  }

  const allCatalog = useMemo(() => {
    const byId = new Map<string, SkillCatalogItem>()
    for (const item of [...popularCatalog, ...recentCatalog, ...accountCatalog]) byId.set(item.id, item)
    return [...byId.values()]
  }, [popularCatalog, recentCatalog, accountCatalog])

  const filterCatalog = (items: SkillCatalogItem[]) => category === '全部'
    ? items
    : items.filter((item) => catalogCategory(item) === category)

  const installedCatalog = allCatalog.filter((item) => item.installed)
  const displayedCatalog = filterCatalog(catalogSort === 'popular' ? popularCatalog : recentCatalog)
  const safeCatalogCount = allCatalog.filter((item) => item.security_status === 'pass').length
  const defaultCodeTemplate = `def execute(input: dict) -> dict:
    """Skill entry point — receives a dict, returns a dict."""
    return {
        "status": "ok",
        "message": f"Received: {input}",
    }
`

  const switchMarketplaceTab = (tab: MarketplaceTab) => {
    setMarketplaceTab(tab)
    if (tab === 'discover' && catalogQuery) {
      setCatalogQuery('')
      setCategory('全部')
      void refreshCatalog('')
    }
  }

  return (
    <div className="flex flex-col h-screen bg-[var(--bg)] text-[var(--text)]">
      <header className="shrink-0 border-b border-[var(--border)] bg-[var(--surface)] backdrop-blur">
        <div className="mx-auto flex h-16 max-w-[1120px] items-center gap-4 px-4 sm:px-6">
          <button onClick={onBack} className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[var(--text-secondary)] transition hover:bg-[var(--surface-raised)] hover:text-[var(--text)]" title="返回主问答"><ChevronLeft size={18} /></button>
          <Wrench size={17} className="mr-auto text-[var(--accent)] sm:hidden" />
          <div className="mr-auto hidden whitespace-nowrap text-base font-bold tracking-tight sm:block"><span className="bg-gradient-to-r from-[var(--accent)] to-violet-500 bg-clip-text text-transparent">OpenTrace</span> SkillHub</div>
          <nav className="flex h-full items-center gap-1 overflow-x-auto" aria-label="Skills 导航">
            {([
              ['discover', '首页'],
              ['search', '搜索'],
              ['installed', '我的 Skills'],
              ...(role === 'admin' ? [['developer', '管理']] : []),
            ] as Array<[MarketplaceTab, string]>).map(([key, label]) => <button key={key} onClick={() => switchMarketplaceTab(key)} className={`relative h-9 whitespace-nowrap rounded-full px-3 text-xs transition sm:px-4 ${marketplaceTab === key ? 'bg-[var(--accent)] font-medium text-[var(--accent-foreground)] shadow-sm' : 'text-[var(--text-secondary)] hover:bg-[var(--surface-raised)] hover:text-[var(--text)]'}`}>{label}{key === 'installed' && installedCatalog.length > 0 && <span className="ml-1 opacity-80">{installedCatalog.length}</span>}</button>)}
          </nav>
          <div className="hidden items-center gap-2 text-[11px] text-[var(--text-secondary)] lg:flex"><ShieldCheck size={14} className="text-emerald-500" /><span>{safeCatalogCount} 个安全 Skills</span></div>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        {view === 'list' && (
          <main className="mx-auto max-w-[1120px] px-4 pb-16 pt-8 sm:px-6 sm:pt-10">
            {output && <div className="flex items-start justify-between rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-xs"><span className="whitespace-pre-wrap">{output}</span><button onClick={() => setOutput('')} className="text-[var(--text-secondary)]">×</button></div>}

            {marketplaceTab === 'discover' && <div className="space-y-20">
              {allCatalog.length === 0 ? <EmptyCatalog /> : <>
                <section className="space-y-6"><SectionTitle title="热门下载" subtitle="社区最受欢迎的技能" action={<button onClick={() => { setCatalogSort('popular'); setMarketplaceTab('search') }} className="inline-flex items-center gap-1 text-xs font-medium hover:text-[var(--accent)]">查看全部 <ArrowRight size={13} /></button>} /><CatalogGrid items={popularCatalog.slice(0, 6)} busyId={busyCatalogId} activeSessionId={activeSessionId} enabledSkills={enabledSkills} onInstall={installCatalog} onUninstall={uninstallCatalog} onToggle={toggleSessionSkill} /></section>
                <section className="space-y-6"><SectionTitle title="最新发布" subtitle="刚刚发布的新技能" action={<button onClick={() => { setCatalogSort('recent'); setMarketplaceTab('search') }} className="inline-flex items-center gap-1 text-xs font-medium hover:text-[var(--accent)]">查看全部 <ArrowRight size={13} /></button>} /><CatalogGrid items={recentCatalog.slice(0, 6)} busyId={busyCatalogId} activeSessionId={activeSessionId} enabledSkills={enabledSkills} onInstall={installCatalog} onUninstall={uninstallCatalog} onToggle={toggleSessionSkill} /></section>
              </>}
              <section className="grid gap-4 border-t border-[var(--border)] pt-7 sm:grid-cols-4">{[[allCatalog.length, '已同步'], [safeCatalogCount, '安全通过'], [installedCatalog.length, '账户已安装'], [enabledSkills.length, '当前会话启用']].map(([value, label]) => <div key={label} className="text-center sm:text-left"><p className="text-xl font-semibold">{value}</p><p className="mt-1 text-[11px] text-[var(--text-secondary)]">{label}</p></div>)}</section>
            </div>}

            {marketplaceTab === 'search' && <section className="space-y-7">
              <SectionTitle title="搜索 Skills" subtitle="查找、审核并安装适合当前项目的能力" action={<button onClick={() => void refreshCatalog()} className="rounded-full border border-[var(--border)] p-2.5 text-[var(--text-secondary)] hover:text-[var(--text)]" title="刷新目录"><RefreshCw size={14} /></button>} />
              <div className="flex items-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-2 shadow-sm">
                <Search size={18} className="ml-3 shrink-0 text-[var(--text-secondary)]" />
                <input value={catalogQuery} onChange={(e) => setCatalogQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void refreshCatalog() }} placeholder="搜索 Skill 名称、描述或 GitHub 仓库" className="min-w-0 flex-1 bg-transparent px-2 py-2.5 text-sm outline-none" />
                <button onClick={() => void refreshCatalog()} className="rounded-xl bg-[var(--accent)] px-5 py-2.5 text-xs font-medium text-[var(--accent-foreground)]">搜索</button>
              </div>
              <div className="flex flex-wrap items-center gap-2">{(['全部', '办公效率', '数据分析', '开发工具', '搜索研究', '内容创作', '自动化'] as CatalogCategory[]).map((item) => <button key={item} onClick={() => setCategory(item)} className={`rounded-full border px-3 py-1.5 text-[11px] transition ${category === item ? 'border-[var(--accent)] bg-[var(--accent-dim)] font-medium text-[var(--accent)]' : 'border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--text)]'}`}>{item}</button>)}{role === 'admin' && <button disabled={loading} onClick={() => void syncCatalog()} className="ml-auto rounded-full border border-[var(--border)] px-3 py-1.5 text-[11px] disabled:opacity-50">{loading ? '同步中…' : '同步目录'}</button>}</div>
              <div className="flex items-center justify-between border-b border-[var(--border)] pb-3"><p className="text-xs text-[var(--text-secondary)]">找到 {displayedCatalog.length} 个结果</p><div className="flex gap-5">{(['popular', 'recent'] as const).map((sort) => <button key={sort} onClick={() => setCatalogSort(sort)} className={`text-xs ${catalogSort === sort ? 'font-medium text-[var(--accent)]' : 'text-[var(--text-secondary)]'}`}>{sort === 'popular' ? '热门优先' : '最新优先'}</button>)}</div></div>
              {displayedCatalog.length ? <CatalogGrid items={displayedCatalog} busyId={busyCatalogId} activeSessionId={activeSessionId} enabledSkills={enabledSkills} onInstall={installCatalog} onUninstall={uninstallCatalog} onToggle={toggleSessionSkill} /> : <EmptyCatalog />}
            </section>}

            {marketplaceTab === 'installed' && <section className="space-y-5"><SectionTitle title="我的 Skills" subtitle="管理当前账户已部署的能力，并决定哪些 Skill 可以进入当前会话" action={sessionChoices.length ? <label className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] px-3 py-1.5 text-[11px] text-[var(--text-secondary)]"><span>目标会话</span><select aria-label="目标会话" value={activeSessionId || ''} onChange={(event) => setActiveSessionId(event.target.value || null)} className="max-w-48 bg-transparent font-medium text-[var(--text)] outline-none">{sessionChoices.map((session) => <option key={session.id} value={session.id}>{session.title || '未命名会话'}</option>)}</select><span>已启用 {enabledSkills.length} 个</span></label> : <div className="rounded-full border border-[var(--border)] px-3 py-1.5 text-[11px] text-[var(--text-secondary)]">请先在主问答创建会话</div>} />{installedCatalog.length ? <CatalogGrid items={installedCatalog} busyId={busyCatalogId} activeSessionId={activeSessionId} enabledSkills={enabledSkills} onInstall={installCatalog} onUninstall={uninstallCatalog} onToggle={toggleSessionSkill} /> : <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface)] py-20 text-center"><PackageCheck size={30} className="mx-auto text-[var(--text-secondary)]" /><p className="mt-3 text-sm font-medium">还没有安装 Skill</p><p className="mt-1 text-xs text-[var(--text-secondary)]">前往技能广场，选择通过安全审核的能力。</p><button onClick={() => setMarketplaceTab('discover')} className="mt-4 rounded-lg bg-[var(--accent)] px-4 py-2 text-xs text-[var(--accent-foreground)]">浏览技能广场</button></div>}</section>}

            {marketplaceTab === 'developer' && role === 'admin' && <CatalogGovernancePanel items={adminCatalog} policy={catalogPolicy} busyId={busyCatalogId} syncing={loading} onSync={syncCatalog} onSetAvailability={setCatalogAvailability} />}

            {marketplaceTab === 'developer' && role === 'admin' && <section className="space-y-5"><SectionTitle title="开发者工具" subtitle="创建、测试和管理平台自有的可执行 Skills" action={<button onClick={() => { resetCreateForm(); setCode(defaultCodeTemplate); setView('create') }} className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-2 text-xs text-[var(--accent-foreground)]"><Plus size={13} />创建 Skill</button>} /><div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5"><div className="flex items-center gap-2 text-sm font-medium"><Download size={14} />从 Git 安装</div><div className="mt-3 grid gap-2 sm:grid-cols-[1fr_140px_auto]"><input value={gitUrl} onChange={(e) => setGitUrl(e.target.value)} placeholder="https://github.com/org/skill.git" className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /><input value={gitRef} onChange={(e) => setGitRef(e.target.value)} placeholder="分支或标签" className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm" /><button disabled={loading || !gitUrl.trim()} onClick={() => void handleInstall()} className="rounded-lg bg-[var(--accent)] px-3 py-2 text-xs text-[var(--accent-foreground)] disabled:opacity-50">安装</button></div><p className="mt-2 text-[11px] text-[var(--text-secondary)]">可执行 Skill 受平台策略控制，生产环境默认禁止动态安装。</p></div>{skills.length === 0 ? <div className="rounded-2xl border border-dashed border-[var(--border)] p-12 text-center text-xs text-[var(--text-secondary)]">暂无平台自有 Skill</div> : <div className="space-y-2">{skills.map((skill) => <div key={skill.skill_id || skill.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4"><div className="grid h-9 w-9 place-items-center rounded-lg bg-[var(--accent-dim)] text-[var(--accent)]"><Boxes size={16} /></div><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{skill.name || skill.id}</p><p className="text-[11px] text-[var(--text-secondary)]">v{skill.version} · {skill.skill_type || 'generic'} · {skill.entrypoint || 'main.py'}</p></div><button onClick={() => void handleSelectSkill(skill)} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs"><FileText size={12} className="mr-1 inline" />详情</button><button onClick={() => void handleUninstall(skill.skill_id || skill.id)} className="rounded-lg border border-red-500/20 px-3 py-1.5 text-xs text-red-500"><Trash2 size={12} className="mr-1 inline" />移除</button></div>)}</div>}</section>}

            <CompanySkillsSection skills={companySkills} role={role} activeSessionId={activeSessionId} enabledSkills={enabledSkills} onDistill={() => setView('distill')} onToggle={toggleSessionSkill} />
          </main>
        )}

        {view === 'distill' && role === 'admin' && (
          <main className="mx-auto max-w-3xl space-y-6 px-4 py-10 sm:px-6">
            <div className="flex items-center gap-3"><button onClick={() => setView('list')} className="text-xs text-[var(--text-secondary)] hover:text-[var(--text)]">&larr; 返回</button><div><h2 className="text-xl font-semibold">蒸馏企业 Skill</h2><p className="mt-1 text-xs text-[var(--text-secondary)]">从文件或文件夹提炼流程、规则与检查项，发布为企业内可复用能力。</p></div></div>
            {output && <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 text-xs">{output}</div>}
            <section className="space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6">
              <input value={distillName} onChange={(event) => setDistillName(event.target.value)} placeholder="Skill 名称，例如：客户交付验收规范" className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm" />
              <textarea value={distillDescription} onChange={(event) => setDistillDescription(event.target.value)} rows={3} placeholder="说明它解决什么企业问题；留空时系统会根据资料生成企业价值说明。" className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm" />
              <select value={distillClassification} onChange={(event) => setDistillClassification(event.target.value as EnterpriseSkillItem['classification'])} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm"><option value="public">公开</option><option value="internal">内部</option><option value="confidential">机密</option></select>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-dashed border-[var(--border)] p-5 text-sm hover:border-[var(--accent)]"><UploadCloud size={17} />选择文件<input type="file" multiple accept=".pdf,.docx,.md,.txt,.text,.csv,.json,.yaml,.yml" className="hidden" onChange={(event) => setDistillFiles(Array.from(event.target.files || []))} /></label>
                <label className="flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-dashed border-[var(--border)] p-5 text-sm hover:border-[var(--accent)]"><FolderOpen size={17} />选择文件夹<input type="file" multiple accept=".pdf,.docx,.md,.txt,.text,.csv,.json,.yaml,.yml" className="hidden" ref={(element) => { if (element) element.setAttribute('webkitdirectory', '') }} onChange={(event) => setDistillFiles(Array.from(event.target.files || []))} /></label>
              </div>
              <div className="rounded-xl bg-[var(--bg)] p-3 text-xs text-[var(--text-secondary)]">已选择 {distillFiles.length} 个文件{distillFiles.length > 0 && `：${distillFiles.slice(0, 4).map((file) => file.webkitRelativePath || file.name).join('、')}${distillFiles.length > 4 ? '…' : ''}`}</div>
              <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-3 text-xs leading-5 text-amber-600">公司发布由管理员执行。系统只提炼文字和工作方法，不运行文件中的代码、宏或脚本；发布后仍受租户、工作区、会话启用、审批与审计约束。</div>
              <button disabled={loading || !distillName.trim() || !distillFiles.length} onClick={() => void handleDistill()} className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2.5 text-sm text-[var(--accent-foreground)] disabled:opacity-40"><Building2 size={15} />{loading ? '蒸馏中…' : '蒸馏并公司发布'}</button>
            </section>
          </main>
        )}

        {view === 'create' && (
          <div className="max-w-4xl mx-auto space-y-4">
            <div className="flex items-center gap-3">
              <button onClick={() => setView('list')} className="text-xs text-[var(--text-secondary)] hover:text-[var(--text)]">&larr; Back</button>
              <h2 className="text-base font-semibold">Create Skill</h2>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-4">
                <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-3">
                  <h3 className="text-sm font-semibold">Metadata</h3>
                  <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Skill name" className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm" />
                  <div className="grid grid-cols-2 gap-2">
                    <input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="version" className="rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm" />
                    <input value={entrypoint} onChange={(e) => setEntrypoint(e.target.value)} placeholder="entrypoint" className="rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm" />
                  </div>
                  <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Description" className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm" />
                  <select value={skillType} onChange={(e) => setSkillType(e.target.value)} className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm">
                    <option value="generic">Generic</option>
                    <option value="data_query">Data Query</option>
                    <option value="text_analysis">Text Analysis</option>
                    <option value="code_gen">Code Generation</option>
                  </select>
                  <input value={dataSourceId} onChange={(e) => setDataSourceId(e.target.value)} placeholder="Data source ID (optional)" className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-sm" />
                </div>

                <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-2">
                  <h3 className="text-sm font-semibold inline-flex items-center gap-1.5"><TestTube size={13} /> Test Cases (JSON array)</h3>
                  <textarea
                    value={testCasesJson}
                    onChange={(e) => setTestCasesJson(e.target.value)}
                    placeholder={`[{"input": {"query": "hello"}, "expected": {"status": "ok"}}]`}
                    rows={4}
                    className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs font-mono"
                  />
                </div>
              </div>

              <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-2">
                <h3 className="text-sm font-semibold inline-flex items-center gap-1.5"><Code size={13} /> Code</h3>
                <textarea
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  rows={18}
                  className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs font-mono"
                />
              </div>
            </div>

            {output && (
              <pre className="text-xs whitespace-pre-wrap rounded border border-[var(--border)] p-3 bg-black/20">{output}</pre>
            )}

            <button onClick={() => void handleCreate()} disabled={loading || !name.trim()} className="px-4 py-2 rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-sm inline-flex items-center gap-1.5 disabled:opacity-50">
              <Save size={14} /> {loading ? 'Creating...' : 'Create'}
            </button>
          </div>
        )}

        {view === 'detail' && selectedSkill && (
          <div className="max-w-4xl mx-auto space-y-4">
            <div className="flex items-center gap-3">
              <button onClick={() => { setView('list'); setSelectedSkill(null) }} className="text-xs text-[var(--text-secondary)] hover:text-[var(--text)]">&larr; Back</button>
              <h2 className="text-base font-semibold">{selectedSkill.name}</h2>
              <span className="text-xs text-[var(--text-secondary)]">v{selectedSkill.version}</span>
            </div>

            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-2">
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div><span className="text-[var(--text-secondary)]">Type:</span> {selectedSkill.skill_type || 'generic'}</div>
                <div><span className="text-[var(--text-secondary)]">Entrypoint:</span> {selectedSkill.entrypoint}</div>
                {selectedSkill.data_source_id && <div><span className="text-[var(--text-secondary)]">Data Source:</span> {selectedSkill.data_source_id}</div>}
              </div>
              {selectedSkill.description && <p className="text-sm text-[var(--text-secondary)]">{selectedSkill.description}</p>}
            </div>

            {selectedSkill.code && (
              <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-2">
                <h3 className="text-sm font-semibold inline-flex items-center gap-1.5"><Code size={13} /> Code</h3>
                <pre className="text-xs font-mono whitespace-pre-wrap rounded border border-[var(--border)] p-3 bg-black/20 max-h-64 overflow-y-auto">{selectedSkill.code}</pre>
              </div>
            )}

            {selectedSkill.test_cases && selectedSkill.test_cases.length > 0 && (
              <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-2">
                <h3 className="text-sm font-semibold inline-flex items-center gap-1.5"><TestTube size={13} /> Test Cases</h3>
                <pre className="text-xs font-mono whitespace-pre-wrap rounded border border-[var(--border)] p-3 bg-black/20 max-h-48 overflow-y-auto">{JSON.stringify(selectedSkill.test_cases, null, 2)}</pre>
              </div>
            )}

            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-3">
              <h3 className="text-sm font-semibold inline-flex items-center gap-1.5"><Play size={13} /> Test Skill</h3>
              <textarea
                value={testInputJson}
                onChange={(e) => setTestInputJson(e.target.value)}
                rows={3}
                className="w-full rounded border border-[var(--border)] bg-transparent px-2 py-1.5 text-xs font-mono"
                placeholder='{"query": "your test input"}'
              />
              <button onClick={() => void handleTest()} disabled={loading} className="px-3 py-1.5 rounded bg-[var(--accent)] text-[var(--accent-foreground)] text-xs inline-flex items-center gap-1.5 disabled:opacity-50">
                <Play size={12} /> {loading ? 'Running...' : 'Run Test'}
              </button>
            </div>

            {output && (
              <pre className="text-xs whitespace-pre-wrap rounded border border-[var(--border)] p-3 bg-black/20 max-h-64 overflow-y-auto">{output}</pre>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export function CatalogGovernancePanel({ items, policy, busyId, syncing, onSync, onSetAvailability }: {
  items: SkillCatalogItem[]
  policy: SkillCatalogSyncPolicy | null
  busyId: string | null
  syncing: boolean
  onSync: () => Promise<void>
  onSetAvailability: (item: SkillCatalogItem) => Promise<void>
}) {
  const disabledCount = items.filter((item) => item.platform_disabled).length
  return <section className="mb-8 space-y-5">
    <SectionTitle
      title="平台目录治理"
      subtitle="目录只增不删；定时拉取新增与更新，平台停用状态不会被同步覆盖"
      action={<button disabled={syncing} onClick={() => void onSync()} className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-xs disabled:opacity-50"><RefreshCw size={13} className={syncing ? 'animate-spin' : ''} />{syncing ? '同步中…' : '立即同步'}</button>}
    />
    <div className="grid gap-3 sm:grid-cols-4">
      {[
        [policy?.sync_enabled ? '运行中' : '已暂停', '自动同步'],
        [formatDuration(policy?.sync_interval_seconds), '同步周期'],
        [formatDuration(policy?.sync_retry_seconds), '失败重试'],
        [`${disabledCount}/${items.length}`, '暂停使用'],
      ].map(([value, label]) => <div key={label} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3"><p className="text-sm font-semibold">{value}</p><p className="mt-1 text-[10px] text-[var(--text-secondary)]">{label}</p></div>)}
    </div>
    <div className="overflow-hidden rounded-2xl border border-[var(--border)]">
      <div className="grid grid-cols-[minmax(0,1fr)_110px_110px] border-b border-[var(--border)] px-4 py-2 text-[10px] text-[var(--text-secondary)]"><span>Skill</span><span>状态</span><span className="text-right">治理操作</span></div>
      <div className="max-h-[420px] divide-y divide-[var(--border)] overflow-y-auto">
        {items.map((item) => <div key={item.id} className="grid grid-cols-[minmax(0,1fr)_110px_110px] items-center px-4 py-3 text-xs">
          <div className="min-w-0"><p className="truncate font-medium">{item.name}</p><p className="mt-0.5 truncate text-[10px] text-[var(--text-secondary)]">{item.github_owner}/{item.github_repo}{item.platform_note ? ` · ${item.platform_note}` : ''}</p></div>
          <span className={item.platform_disabled ? 'text-amber-500' : 'text-emerald-500'}>{item.platform_disabled ? '暂停使用' : '正常使用'}</span>
          <button disabled={busyId === item.id} onClick={() => void onSetAvailability(item)} className="justify-self-end rounded-lg border border-[var(--border)] px-3 py-1.5 text-[11px] disabled:opacity-50">{busyId === item.id ? '处理中…' : item.platform_disabled ? '恢复使用' : '暂停使用'}</button>
        </div>)}
        {!items.length && <div className="p-8 text-center text-xs text-[var(--text-secondary)]">目录尚未同步</div>}
      </div>
    </div>
  </section>
}

function CompanySkillsSection({ skills, role, activeSessionId, enabledSkills, onDistill, onToggle }: {
  skills: EnterpriseSkillItem[]
  role: string | null
  activeSessionId: string | null
  enabledSkills: string[]
  onDistill: () => void
  onToggle: (skillId: string) => Promise<void>
}) {
  return <section className="mt-20 space-y-6 border-t border-[var(--border)] pt-10">
    <SectionTitle title="公司 Skills" subtitle="由企业资料蒸馏、经过公司发布的工作方法，沉淀组织经验并服务实际业务" action={role === 'admin' ? <button onClick={onDistill} className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--accent)] px-4 py-2 text-xs text-[var(--accent-foreground)]"><UploadCloud size={14} />蒸馏 Skill</button> : undefined} />
    {skills.length ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{skills.map((skill) => {
      const enabled = enabledSkills.includes(skill.runtime_id)
      return <article key={skill.id} className="flex min-h-56 flex-col rounded-2xl border border-emerald-500/20 bg-[var(--surface)] p-5 shadow-sm">
        <div className="flex items-start gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-emerald-500/10 text-emerald-500"><Building2 size={18} /></div><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><h3 className="truncate text-sm font-semibold">{skill.name}</h3><span className="shrink-0 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-600">公司发布</span></div><p className="mt-1 text-[10px] text-[var(--text-secondary)]">{skill.classification === 'public' ? '公开' : skill.classification === 'confidential' ? '机密' : '内部'} · {skill.source_files.length} 个来源文件</p></div></div>
        <p className="mt-4 line-clamp-3 text-xs leading-5 text-[var(--text-secondary)]">{skill.value_summary}</p>
        <div className="mt-auto flex items-center justify-between border-t border-[var(--border)] pt-4"><span className="text-[10px] text-[var(--text-secondary)]">可追溯 · 不执行文件代码</span><button disabled={!activeSessionId} onClick={() => void onToggle(skill.runtime_id)} className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] disabled:opacity-40 ${enabled ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-600' : 'border-[var(--border)]'}`}><Power size={12} />{enabled ? '已启用' : '会话启用'}</button></div>
      </article>
    })}</div> : <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface)] py-14 text-center"><Building2 size={28} className="mx-auto text-[var(--text-secondary)]" /><p className="mt-3 text-sm font-medium">还没有公司发布的 Skill</p><p className="mt-1 text-xs text-[var(--text-secondary)]">管理员可以选择企业文件或文件夹，将高价值工作经验蒸馏为可复用能力。</p></div>}
  </section>
}

function SectionTitle({ title, subtitle, action }: { title: string; subtitle: string; action?: React.ReactNode }) {
  return <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-2xl font-semibold tracking-tight">{title}</h2><p className="mt-1.5 text-xs text-[var(--text-secondary)]">{subtitle}</p></div>{action}</div>
}

function formatDuration(seconds?: number): string {
  if (!seconds) return '—'
  if (seconds % 3600 === 0) return `${seconds / 3600} 小时`
  if (seconds % 60 === 0) return `${seconds / 60} 分钟`
  return `${seconds} 秒`
}

function CatalogGrid({ items, busyId, activeSessionId, enabledSkills, onInstall, onUninstall, onToggle }: {
  items: SkillCatalogItem[]
  busyId: string | null
  activeSessionId: string | null
  enabledSkills: string[]
  onInstall: (item: SkillCatalogItem) => Promise<void>
  onUninstall: (item: SkillCatalogItem) => Promise<void>
  onToggle: (skillId: string) => Promise<void>
}) {
  return <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{items.map((item) => <CatalogCard key={item.id} item={item} busy={busyId === item.id} activeSessionId={activeSessionId} enabled={Boolean(item.installed_skill_id && enabledSkills.includes(item.installed_skill_id))} onInstall={onInstall} onUninstall={onUninstall} onToggle={onToggle} />)}</div>
}

function CatalogCard({ item, busy, activeSessionId, enabled, onInstall, onUninstall, onToggle }: {
  item: SkillCatalogItem
  busy: boolean
  activeSessionId: string | null
  enabled: boolean
  onInstall: (item: SkillCatalogItem) => Promise<void>
  onUninstall: (item: SkillCatalogItem) => Promise<void>
  onToggle: (skillId: string) => Promise<void>
}) {
  const label = catalogCategory(item)
  const platformAvailable = !item.platform_disabled && item.status !== 'disabled'
  const installable = platformAvailable && item.security_status === 'pass'
  return <article className="group flex min-h-[170px] flex-col rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-[var(--accent-border)] hover:shadow-md">
    <div className="flex min-w-0 items-center gap-2"><h3 className="truncate text-sm font-semibold">{item.name}</h3>{item.is_verified && <BadgeCheck size={14} className="shrink-0 text-sky-500" />}<span className="ml-auto shrink-0 rounded-full border border-violet-500/20 bg-violet-500/10 px-2.5 py-0.5 text-[10px] text-violet-500">@global</span></div>
    <p className="mt-3 line-clamp-2 text-xs leading-5 text-[var(--text-secondary)]">{item.description || '该 Skill 暂无详细描述。'}</p>
    <div className="mt-auto flex min-w-0 items-center gap-2 pt-4 text-[10px] text-[var(--text-secondary)]">
      <span className="max-w-[104px] truncate rounded-full bg-[var(--surface-raised)] px-2 py-1">v{item.version || 'latest'}</span>
      <span className="inline-flex items-center gap-1"><Download size={11} />{formatCount(item.download_count)}</span>
      <span className="inline-flex items-center gap-1"><Star size={11} className="text-violet-500" />{formatCount(item.github_stars)}</span>
      <span className={`inline-flex items-center gap-1 ${installable ? 'text-emerald-500' : 'text-amber-500'}`} title={`安全评分 ${item.security_score ?? '待审'}`}><ShieldCheck size={11} />{item.security_score ?? '待审'}</span>
    </div>
    <div className="mt-3 flex items-center gap-2 border-t border-[var(--border)] pt-3">
      <span className="mr-auto rounded-full bg-[var(--surface-raised)] px-2 py-0.5 text-[10px] text-[var(--text-secondary)]">{label}</span>
      <a href={item.source_url} target="_blank" rel="noreferrer" className="grid h-7 w-7 place-items-center rounded-full text-[var(--text-secondary)] hover:bg-[var(--surface-raised)] hover:text-[var(--accent)]" title={`${item.github_owner}/${item.github_repo}`}><ExternalLink size={12} /></a>
      <button disabled={busy || (!item.installed && !installable) || !platformAvailable} onClick={() => void (item.installed ? onUninstall(item) : onInstall(item))} className={`rounded-full px-3 py-1.5 text-[11px] font-medium disabled:cursor-not-allowed disabled:opacity-40 ${item.installed ? 'border border-[var(--border)] text-[var(--text-secondary)]' : 'bg-[var(--accent)] text-[var(--accent-foreground)]'}`}>{busy ? '处理中…' : !platformAvailable ? '平台已暂停' : item.installed ? '卸载' : installable ? '安装' : '审核未通过'}</button>
      {item.installed && item.installed_skill_id && <button disabled={!activeSessionId || !platformAvailable} onClick={() => void onToggle(item.installed_skill_id!)} className={`grid h-7 w-7 place-items-center rounded-full border disabled:opacity-40 ${enabled ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-500' : 'border-[var(--border)]'}`} title={!platformAvailable ? '平台已暂停该 Skill' : activeSessionId ? '切换当前会话权限' : '请先选择会话'}><Power size={12} /></button>}
    </div>
  </article>
}

function EmptyCatalog() {
  return <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface)] py-20 text-center"><Wrench size={30} className="mx-auto text-[var(--text-secondary)]" /><p className="mt-3 text-sm font-medium">Skill 目录尚未同步</p><p className="mt-1 text-xs text-[var(--text-secondary)]">后台 Worker 会定时同步，管理员也可以手动触发。</p></div>
}

function formatCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}K`
  return String(value || 0)
}

export function resolveSkillSessionId(
  requestedSessionId: string | null,
  activeSessionId: string | null,
  sessions: ConversationItem[],
): string | null {
  const available = new Set(sessions.map((session) => session.id))
  if (requestedSessionId && available.has(requestedSessionId)) return requestedSessionId
  if (activeSessionId && available.has(activeSessionId)) return activeSessionId
  return sessions[0]?.id ?? null
}

function catalogCategory(item: SkillCatalogItem): CatalogCategory {
  const text = `${item.name} ${item.description}`.toLowerCase()
  if (/(database|sql|stock|finance|metric|analysis|分析|数据|财报)/.test(text)) return '数据分析'
  if (/(browser|code|debug|api|git|developer|开发|测试|编程)/.test(text)) return '开发工具'
  if (/(search|research|web|搜索|检索|研究)/.test(text)) return '搜索研究'
  if (/(ppt|word|docx|pdf|office|resume|文档|简历|办公)/.test(text)) return '办公效率'
  if (/(write|content|video|audio|image|voice|写作|内容|视频|语音|图片)/.test(text)) return '内容创作'
  if (/(automation|workflow|agent|自动化|工作流)/.test(text)) return '自动化'
  return '办公效率'
}
