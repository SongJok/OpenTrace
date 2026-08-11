import { useCompanyStore } from '../store/company'

export default function WelcomeScreen() {
  const brandName = useCompanyStore((state) => state.brandName)
  return (
    <div className="relative w-full max-w-[820px] px-4 text-center sm:px-6">
      <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--accent)] text-xl text-[var(--accent-foreground)] shadow-[0_8px_24px_var(--accent-dim)]">✦</div>
      <h1 className="text-3xl font-semibold tracking-[-0.03em] text-[var(--text)] sm:text-[40px]">有什么可以帮忙的？</h1>
      <p className="mx-auto mt-3 max-w-xl text-sm text-[var(--text-secondary)]">{brandName} 专注企业知识检索、企业大脑问答和授权数据库问数。</p>
    </div>
  )
}
