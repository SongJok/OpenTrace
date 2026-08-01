import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BrainCircuit,
  Building2,
  ChevronLeft,
  FileText,
  Folder,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  Rocket,
  Save,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import {
  apiBindCompany,
  apiCreateCompanyBrainManualSource,
  apiDeactivateCompanyBrainSource,
  apiGetCompanyBrain,
  apiListCompanyBrainSources,
  apiPublishCompanyBrainDraft,
  apiSaveCompanyBrainDraft,
  apiUploadCompanyBrainSource,
  type CompanyBrainFolder,
  type CompanyBrainSnapshot,
  type CompanyBrainSourceItem,
  type CompanyBrainTier,
} from "../api/client";
import { useAuthStore } from "../store/auth";
import { useCompanyStore } from "../store/company";

const tierLabel: Record<CompanyBrainTier, string> = {
  long: "长期记忆",
  medium: "中期记忆",
  short: "短期记忆",
};

const statusLabel: Record<string, string> = {
  pending: "等待处理",
  processing: "LLM 处理中",
  retry: "等待重试",
  ready: "已生效",
  error: "处理失败",
};

function formatTime(value?: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

export default function CompanyBrainPage({ onBack }: { onBack: () => void }) {
  const token = useAuthStore((state) => state.token)!;
  const role = useAuthStore((state) => state.role);
  const setCompanyProfile = useCompanyStore((state) => state.setProfile);
  const [brain, setBrain] = useState<CompanyBrainSnapshot | null>(null);
  const [sources, setSources] = useState<CompanyBrainSourceItem[]>([]);
  const [selectedFolder, setSelectedFolder] =
    useState<CompanyBrainFolder>("文化");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [legalName, setLegalName] = useState("");
  const [shortName, setShortName] = useState("");
  const [description, setDescription] = useState("");
  const [sourceTitle, setSourceTitle] = useState("");
  const [sourceContent, setSourceContent] = useState("");
  const [sourceTier, setSourceTier] = useState<"auto" | CompanyBrainTier>(
    "auto",
  );
  const [editorContent, setEditorContent] = useState("");
  const [changeSummary, setChangeSummary] =
    useState("管理员在线编辑 COMPANY.md");
  const fileInput = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const nextBrain = await apiGetCompanyBrain(token);
      setBrain(nextBrain);
      setCompanyProfile(nextBrain.profile);
      if (nextBrain.profile.bound && role === "admin") {
        setSources(await apiListCompanyBrainSources(token, selectedFolder));
      } else {
        setSources([]);
      }
      setEditorContent(
        (current) =>
          current ||
          nextBrain.draft?.content ||
          nextBrain.published?.content ||
          "",
      );
      setLegalName(nextBrain.profile.legal_name);
      setShortName(
        nextBrain.profile.short_name === "OpenTrace" && !nextBrain.profile.bound
          ? ""
          : nextBrain.profile.short_name,
      );
      setDescription(nextBrain.profile.description);
    } catch (nextError) {
      setError(
        nextError instanceof Error ? nextError.message : "企业大脑加载失败",
      );
    } finally {
      setLoading(false);
    }
  }, [role, selectedFolder, setCompanyProfile, token]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (
      !sources.some((source) =>
        ["pending", "processing", "retry"].includes(source.status),
      )
    )
      return;
    const timer = window.setInterval(() => void load(), 8_000);
    return () => window.clearInterval(timer);
  }, [load, sources]);

  const selectedFolderInfo = brain?.folders.find(
    (folder) => folder.name === selectedFolder,
  );
  const charUsage = brain?.published?.char_count ?? 0;
  const usagePercent = Math.min(100, (charUsage / 200_000) * 100);
  const sourceStats = useMemo(
    () => ({
      ready: sources.filter((source) => source.status === "ready").length,
      pending: sources.filter(
        (source) => source.status !== "ready" && source.status !== "error",
      ).length,
    }),
    [sources],
  );

  async function bindCompany() {
    if (!legalName.trim() || !shortName.trim()) return;
    setWorking(true);
    setError("");
    try {
      const profile = await apiBindCompany(token, {
        legal_name: legalName.trim(),
        short_name: shortName.trim(),
        description: description.trim(),
      });
      setCompanyProfile(profile);
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "绑定公司失败");
    } finally {
      setWorking(false);
    }
  }

  async function submitManualSource() {
    if (!sourceTitle.trim() || !sourceContent.trim()) return;
    setWorking(true);
    setError("");
    try {
      await apiCreateCompanyBrainManualSource(token, {
        folder: selectedFolder,
        title: sourceTitle.trim(),
        content: sourceContent.trim(),
        memory_tier: sourceTier,
      });
      setSourceTitle("");
      setSourceContent("");
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "录入失败");
    } finally {
      setWorking(false);
    }
  }

  async function uploadFile(file?: File) {
    if (!file) return;
    setWorking(true);
    setError("");
    try {
      await apiUploadCompanyBrainSource(token, {
        folder: selectedFolder,
        memory_tier: sourceTier,
        file,
      });
      if (fileInput.current) fileInput.current.value = "";
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "上传失败");
    } finally {
      setWorking(false);
    }
  }

  async function removeSource(source: CompanyBrainSourceItem) {
    if (
      !window.confirm(
        `确认停用“${source.title}”吗？下次整理后将不再进入 COMPANY.md。`,
      )
    )
      return;
    setWorking(true);
    try {
      await apiDeactivateCompanyBrainSource(token, source.id);
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "停用失败");
    } finally {
      setWorking(false);
    }
  }

  async function saveDraft() {
    if (!editorContent.trim()) return;
    setWorking(true);
    setError("");
    try {
      const draft = await apiSaveCompanyBrainDraft(
        token,
        editorContent,
        changeSummary,
      );
      setBrain((current) => (current ? { ...current, draft } : current));
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "保存草稿失败");
    } finally {
      setWorking(false);
    }
  }

  async function publishDraft() {
    if (!brain?.draft) return;
    setWorking(true);
    setError("");
    try {
      await apiPublishCompanyBrainDraft(token, brain.draft.id);
      setEditorContent("");
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "发布失败");
    } finally {
      setWorking(false);
    }
  }

  if (loading && !brain)
    return (
      <div className="grid min-h-screen place-items-center bg-[var(--bg)] text-sm text-[var(--text-secondary)]">
        <LoaderCircle size={18} className="mr-2 animate-spin" />
        正在加载企业大脑…
      </div>
    );

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--bg)]/95 px-4 py-3 backdrop-blur sm:px-6">
        <div className="mx-auto flex max-w-7xl items-center gap-3">
          <button
            onClick={onBack}
            className="grid h-9 w-9 place-items-center rounded-xl border border-[var(--border)] bg-[var(--surface)]"
          >
            <ChevronLeft size={16} />
          </button>
          <div className="grid h-10 w-10 place-items-center rounded-2xl bg-[var(--accent-dim)] text-[var(--accent)]">
            <BrainCircuit size={20} />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="font-semibold">企业大脑</h1>
            <p className="truncate text-xs text-[var(--text-secondary)]">
              八目录资料 → 内部 LLM 处理 → COMPANY.md → Responses 相关检索注入
            </p>
          </div>
          <button
            onClick={() => void load()}
            className="grid h-9 w-9 place-items-center rounded-xl border border-[var(--border)]"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
        {error && (
          <div
            role="alert"
            className="rounded-2xl border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-500"
          >
            {error}
          </div>
        )}
        {!brain?.profile.bound ? (
          <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6">
            <div className="flex items-start gap-4">
              <div className="grid h-12 w-12 place-items-center rounded-2xl bg-[var(--accent-dim)] text-[var(--accent)]">
                <Building2 size={22} />
              </div>
              <div>
                <h2 className="text-xl font-semibold">绑定当前项目唯一公司</h2>
                <p className="mt-1 text-sm text-[var(--text-secondary)]">
                  绑定后不可改绑；所有界面中的 OpenTrace 品牌会替换为公司简称。
                </p>
              </div>
            </div>
            {role === "admin" ? (
              <div className="mt-6 grid gap-3 md:grid-cols-2">
                <input
                  value={legalName}
                  onChange={(event) => setLegalName(event.target.value)}
                  placeholder="公司全称"
                  className="rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm"
                />
                <input
                  value={shortName}
                  onChange={(event) => setShortName(event.target.value)}
                  placeholder="公司简称（界面品牌）"
                  maxLength={32}
                  className="rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm"
                />
                <textarea
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="公司简介（可选）"
                  rows={3}
                  className="rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm md:col-span-2"
                />
                <button
                  disabled={working || !legalName.trim() || !shortName.trim()}
                  onClick={() => void bindCompany()}
                  className="rounded-xl bg-[var(--accent)] px-4 py-2.5 text-sm text-[var(--accent-foreground)] disabled:opacity-40 md:col-span-2"
                >
                  确认绑定唯一公司
                </button>
              </div>
            ) : (
              <p className="mt-6 text-sm text-[var(--text-secondary)]">
                请联系管理员完成公司绑定。
              </p>
            )}
          </section>
        ) : (
          <>
            <section className="grid gap-4 rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 lg:grid-cols-[1fr_360px]">
              <div>
                <div className="flex items-center gap-2 text-xs font-medium text-[var(--accent)]">
                  <LockKeyhole size={14} />
                  仅项目内部可用
                </div>
                <h2 className="mt-2 text-2xl font-semibold">
                  {brain.profile.short_name} 企业大脑
                </h2>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--text-secondary)]">
                  {brain.profile.description || brain.profile.legal_name}
                  。外部工具不得蒸馏、收集、训练或导出企业大脑和个人记忆；问答只注入当前问题相关片段。
                </p>
                <div className="mt-4 flex flex-wrap gap-2 text-xs">
                  <span className="rounded-full bg-[var(--accent-dim)] px-3 py-1 text-[var(--accent)]">
                    每天 05:00 自主学习
                  </span>
                  <span className="rounded-full bg-[var(--surface-raised)] px-3 py-1">
                    17 万字自动压缩
                  </span>
                  <span className="rounded-full bg-[var(--surface-raised)] px-3 py-1">
                    长期记忆不可压缩
                  </span>
                </div>
              </div>
              <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg)] p-4">
                <div className="flex justify-between text-xs">
                  <span>COMPANY.md 容量</span>
                  <span>{charUsage.toLocaleString()} / 200,000 字</span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-[var(--surface-raised)]">
                  <div
                    className={`h-full rounded-full ${charUsage >= 170_000 ? "bg-amber-500" : "bg-[var(--accent)]"}`}
                    style={{ width: `${usagePercent}%` }}
                  />
                </div>
                <div className="mt-4 grid grid-cols-3 gap-2 text-center text-xs">
                  <div>
                    <strong className="block text-base">
                      {brain.published?.long_term_chars.toLocaleString() ?? 0}
                    </strong>
                    长期 5%
                  </div>
                  <div>
                    <strong className="block text-base">
                      {brain.published?.medium_term_chars.toLocaleString() ?? 0}
                    </strong>
                    中期 35%
                  </div>
                  <div>
                    <strong className="block text-base">
                      {brain.published?.short_term_chars.toLocaleString() ?? 0}
                    </strong>
                    短期 60%
                  </div>
                </div>
                <p className="mt-3 text-[10px] text-[var(--text-secondary)]">
                  当前发布 v{brain.published?.version ?? 0} ·{" "}
                  {formatTime(brain.published?.published_at)}
                </p>
              </div>
            </section>
            <section>
              <div className="mb-3">
                <h2 className="font-medium">八个企业目录</h2>
                <p className="text-xs text-[var(--text-secondary)]">
                  文化、行政默认进入不可压缩的长期记忆；其余目录进入中期记忆，管理员可明确记为短期。
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
                {brain.folders.map((folder) => (
                  <button
                    key={folder.name}
                    onClick={() => setSelectedFolder(folder.name)}
                    className={`rounded-2xl border p-3 text-left ${selectedFolder === folder.name ? "border-[var(--accent)] bg-[var(--accent-dim)]" : "border-[var(--border)] bg-[var(--surface)]"}`}
                  >
                    <Folder size={17} className="text-[var(--accent)]" />
                    <div className="mt-3 text-sm font-medium">
                      {folder.name}
                    </div>
                    <div className="mt-1 text-[10px] text-[var(--text-secondary)]">
                      {folder.ready_count}/{folder.source_count} 已处理
                    </div>
                  </button>
                ))}
              </div>
            </section>
            {role === "admin" && (
              <section className="grid gap-6 xl:grid-cols-[380px_1fr]">
                <div className="space-y-5">
                  <div className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
                    <h3 className="font-medium">录入 {selectedFolder} 信息</h3>
                    <p className="mt-1 text-xs text-[var(--text-secondary)]">
                      内容先排队，由 Worker 内部 LLM 处理并自动发布。
                    </p>
                    <div className="mt-4 space-y-3">
                      <select
                        value={sourceTier}
                        onChange={(event) =>
                          setSourceTier(event.target.value as typeof sourceTier)
                        }
                        className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm"
                      >
                        <option value="auto">
                          按目录自动分层（
                          {selectedFolderInfo?.default_tier === "long"
                            ? "长期"
                            : "中期"}
                          ）
                        </option>
                        <option value="short">管理员要求记为短期</option>
                      </select>
                      <input
                        value={sourceTitle}
                        onChange={(event) => setSourceTitle(event.target.value)}
                        placeholder="信息标题"
                        className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm"
                      />
                      <textarea
                        value={sourceContent}
                        onChange={(event) =>
                          setSourceContent(event.target.value)
                        }
                        rows={7}
                        placeholder="手动录入公司事实、制度、术语、约定或决策…"
                        className="w-full resize-y rounded-xl border border-[var(--border)] bg-transparent px-3 py-2.5 text-sm leading-6"
                      />
                      <button
                        disabled={
                          working ||
                          !sourceTitle.trim() ||
                          !sourceContent.trim()
                        }
                        onClick={() => void submitManualSource()}
                        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2.5 text-sm text-[var(--accent-foreground)] disabled:opacity-40"
                      >
                        <Sparkles size={15} />
                        提交内部 LLM 处理
                      </button>
                      <div className="relative">
                        <input
                          ref={fileInput}
                          type="file"
                          accept=".pdf,.docx,.md,.txt,.csv,.json,.log,.xml,.yaml,.yml"
                          onChange={(event) =>
                            void uploadFile(event.target.files?.[0])
                          }
                          className="absolute inset-0 cursor-pointer opacity-0"
                        />
                        <button className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-[var(--border)] px-4 py-2.5 text-sm">
                          <Upload size={15} />
                          上传文档到 {selectedFolder}
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
                <div>
                  <div className="mb-3 flex items-end justify-between">
                    <div>
                      <h3 className="font-medium">{selectedFolder} 来源</h3>
                      <p className="text-xs text-[var(--text-secondary)]">
                        已生效 {sourceStats.ready} · 处理中{" "}
                        {sourceStats.pending}
                      </p>
                    </div>
                  </div>
                  <div className="space-y-3">
                    {sources.map((source) => (
                      <article
                        key={source.id}
                        className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4"
                      >
                        <div className="flex items-start gap-3">
                          <div className="grid h-9 w-9 place-items-center rounded-xl bg-[var(--accent-dim)] text-[var(--accent)]">
                            <FileText size={16} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <h4 className="truncate text-sm font-medium">
                                {source.title}
                              </h4>
                              <span className="rounded-full bg-[var(--surface-raised)] px-2 py-0.5 text-[10px]">
                                {tierLabel[source.memory_tier]}
                              </span>
                              <span
                                className={`rounded-full px-2 py-0.5 text-[10px] ${source.status === "ready" ? "bg-emerald-500/10 text-emerald-500" : source.status === "error" ? "bg-red-500/10 text-red-500" : "bg-amber-500/10 text-amber-500"}`}
                              >
                                {statusLabel[source.status]}
                              </span>
                            </div>
                            <p className="mt-2 line-clamp-3 text-xs leading-5 text-[var(--text-secondary)]">
                              {source.processed_content ||
                    source.source_preview ||
                                "等待内部处理"}
                            </p>
                            {source.error_message && (
                              <p className="mt-2 text-xs text-red-500">
                                {source.error_message}
                              </p>
                            )}
                          </div>
                          <button
                            disabled={working}
                            onClick={() => void removeSource(source)}
                            className="grid h-8 w-8 place-items-center rounded-lg text-[var(--text-secondary)] hover:bg-red-500/10 hover:text-red-500"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </article>
                    ))}
                    {sources.length === 0 && (
                      <div className="rounded-2xl border border-dashed border-[var(--border)] p-10 text-center text-sm text-[var(--text-secondary)]">
                        该目录还没有资料
                      </div>
                    )}
                  </div>
                </div>
              </section>
            )}
            <section className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-medium">
                    COMPANY.md{" "}
                    {role === "admin" ? "在线编辑与发布" : "当前发布版本"}
                  </h2>
                  <p className="mt-1 text-xs text-[var(--text-secondary)]">
                    实际发布镜像位于项目一级目录
                    memory/COMPANY.md，并已禁止提交到 Git。
                  </p>
                </div>
                {role === "admin" && (
                  <div className="flex gap-2">
                    <button
                      disabled={working}
                      onClick={() => void saveDraft()}
                      className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] px-4 py-2 text-sm"
                    >
                      <Save size={14} />
                      保存草稿
                    </button>
                    <button
                      disabled={working || !brain.draft}
                      onClick={() => void publishDraft()}
                      className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-40"
                    >
                      <Rocket size={14} />
                      发布生效
                    </button>
                  </div>
                )}
              </div>
              {role === "admin" && (
                <input
                  value={changeSummary}
                  onChange={(event) => setChangeSummary(event.target.value)}
                  placeholder="本次修改说明"
                  className="mt-4 w-full rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-xs"
                />
              )}
              <textarea
                readOnly={role !== "admin"}
                value={
                  role === "admin"
                    ? editorContent
                    : brain.published?.content || ""
                }
                onChange={(event) => setEditorContent(event.target.value)}
                rows={28}
                spellCheck={false}
                className="mt-3 w-full resize-y rounded-2xl border border-[var(--border)] bg-[var(--bg)] p-4 font-mono text-xs leading-6 outline-none focus:border-[var(--accent)]"
              />
            </section>
          </>
        )}
      </main>
    </div>
  );
}
