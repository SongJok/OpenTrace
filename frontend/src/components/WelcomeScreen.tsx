export default function WelcomeScreen() {
  return (
    <div className="relative w-full max-w-[820px] px-4 sm:px-6">
      <div className="pointer-events-none absolute right-4 top-1 hidden h-28 w-40 md:block animate-float-slow">
        <div className="absolute inset-x-6 top-2 h-16 rounded-full bg-[radial-gradient(circle,var(--hero-glow-primary),transparent_70%)] blur-2xl" />
        <div className="absolute right-2 top-4 h-20 w-20 rounded-full bg-[radial-gradient(circle_at_35%_35%,rgba(255,255,255,0.95),rgba(255,255,255,0.2)_25%,transparent_55%),linear-gradient(145deg,#6d7dff,#5a47ff_45%,#a455f7_100%)] shadow-[0_18px_45px_rgba(95,87,255,0.32)]" />
        <div className="absolute bottom-1 left-6 h-16 w-24 rounded-[999px] bg-[linear-gradient(140deg,rgba(255,255,255,0.92),rgba(239,68,68,0.4)_26%,rgba(99,102,241,0.82)_85%)] opacity-70 blur-[1px]" />
      </div>
      <div className="relative">
        <h1 className="text-3xl font-semibold tracking-[-0.03em] text-[var(--text)] sm:text-[44px]">
          👋有什么我能帮你分担的吗？
        </h1>
      </div>
    </div>
  )
}
