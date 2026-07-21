export default function WelcomeScreen() {
  return (
    <div className="relative w-full max-w-[820px] px-4 text-center sm:px-6">
      <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--accent)] text-xl text-[var(--accent-foreground)] shadow-[0_8px_24px_var(--accent-dim)]">✦</div>
      <h1 className="text-3xl font-semibold tracking-[-0.03em] text-[var(--text)] sm:text-[40px]">有什么可以帮忙的？</h1>
      <p className="mx-auto mt-3 max-w-xl text-sm text-[var(--text-secondary)]">提问、分析文件或使用工作区工具，OpenTrace 会在需要时自动选择合适的能力。</p>
    </div>
  )
}
