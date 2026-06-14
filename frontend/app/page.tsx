"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import {
  AppStep,
  PDFContext,
  GenerateResponse,
  PageExtractionView,
  PlanResponse,
} from "@/types";
import FileUpload from "@/components/FileUpload";
import ContextForm from "@/components/ContextForm";
import DownloadCard from "@/components/DownloadCard";
import PreviewPane from "@/components/PreviewPane";
import AnalyticsModal from "@/components/AnalyticsModal";
import PageReview from "@/components/PageReview";
import PlanReview from "@/components/PlanReview";
import { useToasts, Toaster } from "@/components/Toast";
import {
  startSession,
  buildPlan,
  generateFromSession,
  endSession,
  checkHealth,
  checkSessionAlive,
} from "@/lib/api";
import {
  Compass,
  ChevronRight,
  AlertTriangle,
  Wifi,
  WifiOff,
  Link as LinkIcon,
  ScanSearch,
  Sparkles,
} from "lucide-react";

const DEFAULT_CONTEXT: PDFContext = {
  batch: "",
  purpose: "",
  subject: "",
  class_level: "",
  language: "English",
  annotations: [],
};

const STORAGE_KEY = "deckpilot_session";

interface PersistedState {
  sessionId: string;
  step: AppStep;
  context: PDFContext;
  pages: PageExtractionView[];
  plan: PlanResponse | null;
  result: GenerateResponse | null;
  savedAt: number;
}

function saveToStorage(state: Partial<PersistedState>) {
  try {
    const existing = loadFromStorage();
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ ...existing, ...state, savedAt: Date.now() })
    );
  } catch {
    // localStorage may be blocked (private mode, quota exceeded) — fail silently
  }
}

function loadFromStorage(): PersistedState | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as PersistedState;
  } catch {
    return null;
  }
}

function clearStorage() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

const WIZARD: { step: AppStep; label: string }[] = [
  { step: "upload", label: "Upload" },
  { step: "configure", label: "Configure" },
  { step: "review-pages", label: "Pages" },
  { step: "review-plan", label: "Plan" },
  { step: "done", label: "Download" },
];

export default function Home() {
  const [step, setStep] = useState<AppStep>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [pdfUrl, setPdfUrl] = useState("");
  const [context, setContext] = useState<PDFContext>(DEFAULT_CONTEXT);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [pages, setPages] = useState<PageExtractionView[]>([]);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [result, setResult] = useState<GenerateResponse | null>(null);

  const [starting, setStarting] = useState(false);
  const [building, setBuilding] = useState(false);
  const [generating, setGenerating] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [serverOnline, setServerOnline] = useState<boolean | null>(null);
  const [previewAvailable, setPreviewAvailable] = useState(false);
  const [showAnalytics, setShowAnalytics] = useState(false);
  const { toasts, notify, dismiss } = useToasts();

  // ── Restore session from localStorage on first load ──────────────────────
  useEffect(() => {
    const saved = loadFromStorage();
    if (!saved?.sessionId) return;

    // Verify backend session is still alive before restoring UI state.
    // If the backend restarted or TTL expired, we silently discard the save.
    checkSessionAlive(saved.sessionId).then((alive) => {
      if (!alive) {
        clearStorage();
        return;
      }
      setSessionId(saved.sessionId);
      setContext(saved.context ?? DEFAULT_CONTEXT);
      setPages(saved.pages ?? []);
      setPlan(saved.plan ?? null);
      setResult(saved.result ?? null);
      // Don't restore "generating" step — user should re-trigger or see done
      const safeStep = saved.step === "generating" ? "review-plan" : saved.step;
      setStep(safeStep);
      notify("Session restored — pick up where you left off", "success");
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Persist key state to localStorage whenever it changes ────────────────
  useEffect(() => {
    if (!sessionId) return;
    saveToStorage({ sessionId, step, context, pages, plan, result });
  }, [sessionId, step, context, pages, plan, result]);

  useEffect(() => {
    checkHealth().then((h) => {
      setServerOnline(h.online);
      setPreviewAvailable(h.previewAvailable);
    });
  }, []);

  const isFormValid =
    context.subject && context.batch.trim() && context.purpose;
  const trimmedPdfUrl = pdfUrl.trim();
  const hasPdfSource = Boolean(file || trimmedPdfUrl);

  // ── configure → analyse (start session) ──────────────
  const handleAnalyse = useCallback(async () => {
    setError(null);
    setStarting(true);
    try {
      const res = await startSession(
        file ? { file } : { url: trimmedPdfUrl },
        context
      );
      setSessionId(res.session_id);
      setPages(res.pages);
      setStep("review-pages");
      notify(`Read ${res.total_pages} pages — review each one below`, "success");
    } catch (e) {
      const msg = (e as Error).message || "Failed to analyse the PDF";
      setError(msg);
      notify(msg, "error");
    } finally {
      setStarting(false);
    }
  }, [file, trimmedPdfUrl, context, notify]);

  // ── pages → plan ─────────────────────────────────────
  const handleBuildPlan = useCallback(async () => {
    if (!sessionId) return;
    setError(null);
    setBuilding(true);
    try {
      const res = await buildPlan(sessionId);
      setPlan(res);
      setStep("review-plan");
      notify(`Planned ${res.total_slides} slides — review before generating`, "success");
    } catch (e) {
      const msg = (e as Error).message || "Failed to build the slide plan";
      setError(msg);
      notify(msg, "error");
    } finally {
      setBuilding(false);
    }
  }, [sessionId, notify]);

  // ── plan → generate ──────────────────────────────────
  const handleGenerate = useCallback(async () => {
    if (!sessionId) return;
    setError(null);
    setGenerating(true);
    setStep("generating");
    try {
      const res = await generateFromSession(sessionId);
      setResult(res);
      setStep("done");
      notify("Your deck is ready to download", "success");
    } catch (e) {
      const msg = (e as Error).message || "Generation failed";
      setError(msg);
      setStep("review-plan");
      notify(msg, "error");
    } finally {
      setGenerating(false);
    }
  }, [sessionId, notify]);

  const handleReset = useCallback(() => {
    if (sessionId) endSession(sessionId);
    clearStorage();
    setStep("upload");
    setFile(null);
    setPdfUrl("");
    setContext(DEFAULT_CONTEXT);
    setSessionId(null);
    setPages([]);
    setPlan(null);
    setResult(null);
    setError(null);
    setShowAnalytics(false);
  }, [sessionId]);

  const keptPages = pages.filter((p) => p.status !== "skipped");
  const approvedPageNums = keptPages.map((p) => p.page_number);
  const detectedQuestions = keptPages.reduce(
    (sum, p) => sum + (p.question_count || 0),
    0
  );

  const wide = step === "review-pages" || step === "review-plan" || step === "done";
  const currentIdx = WIZARD.findIndex((w) => w.step === step);

  // Which completed steps can the user jump back to right now?
  // Rules: session must exist to jump to pages/plan, result must exist for done.
  // Jumping never clears state — it just changes which component is rendered.
  const canJumpTo = (target: AppStep): boolean => {
    if (step === "generating") return false; // block navigation mid-generation
    if (target === "upload") return currentIdx > 0;
    if (target === "configure") return currentIdx > 1;
    if (target === "review-pages") return Boolean(sessionId) && currentIdx > 2;
    if (target === "review-plan") return Boolean(plan) && currentIdx > 3;
    if (target === "done") return Boolean(result);
    return false;
  };

  const jumpTo = (target: AppStep) => {
    if (!canJumpTo(target)) return;
    setError(null);
    setStep(target);
  };

  return (
    <div className="flex min-h-screen flex-col">
      {/* ── Navbar ───────────────────────────────────── */}
      <header className="flex items-center justify-between border-b border-white/5 px-6 py-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg brand-gradient shadow-lg shadow-violet-500/30">
            <Compass className="h-4 w-4 text-white" />
          </div>
          <span className="text-sm font-semibold text-white">DeckPilot</span>
          <span className="rounded-full bg-violet-500/10 px-2 py-0.5 text-[10px] font-medium text-violet-300 ring-1 ring-violet-500/20">
            AI
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          {serverOnline === null ? (
            <span className="text-xs text-zinc-600">Checking server…</span>
          ) : serverOnline ? (
            <>
              <Wifi className="h-3.5 w-3.5 text-emerald-500" />
              <span className="text-xs text-zinc-500">Backend connected</span>
            </>
          ) : (
            <>
              <WifiOff className="h-3.5 w-3.5 text-red-500" />
              <span className="text-xs text-red-400">Backend offline</span>
            </>
          )}
        </div>
      </header>

      <main className="flex flex-1 flex-col items-center px-4 py-10">
        {/* Step indicator */}
        {step !== "generating" && (
          <div className="mb-8 flex flex-wrap items-center justify-center gap-2">
            {WIZARD.map((w, i) => {
              const isActive = w.step === step;
              const isDone = i < currentIdx;
              const jumpable = isDone && canJumpTo(w.step);
              return (
                <div key={w.step} className="flex items-center gap-2">
                  <div
                    onClick={() => jumpable && jumpTo(w.step)}
                    title={jumpable ? `Go back to ${w.label}` : undefined}
                    className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-all ${
                      isActive
                        ? "bg-violet-500/15 text-violet-200 ring-1 ring-violet-500/30"
                        : jumpable
                        ? "cursor-pointer text-zinc-400 hover:bg-white/6 hover:text-zinc-200 hover:ring-1 hover:ring-white/15"
                        : isDone
                        ? "text-zinc-600"
                        : "text-zinc-700"
                    }`}
                  >
                    <span
                      className={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold ${
                        isActive
                          ? "brand-gradient text-white"
                          : isDone
                          ? "bg-zinc-700 text-zinc-300"
                          : "bg-zinc-800 text-zinc-600"
                      }`}
                    >
                      {isDone ? "✓" : i + 1}
                    </span>
                    {w.label}
                  </div>
                  {i < WIZARD.length - 1 && (
                    <ChevronRight className="h-3 w-3 text-zinc-700" />
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div
          className={`w-full rounded-3xl border border-white/[0.07] bg-[#0d0e18]/80 shadow-2xl shadow-black/50 backdrop-blur ${
            step === "review-pages"
              ? "max-w-6xl"
              : wide
              ? "max-w-5xl"
              : "max-w-xl"
          }`}
        >
          {(step === "upload" || step === "configure") && (
            <div className="border-b border-white/5 px-7 py-6">
              <h1 className="text-xl font-bold tracking-tight text-white">
                {step === "upload" && (
                  <>
                    Turn any teaching PDF into a{" "}
                    <span className="brand-text">polished deck</span>
                  </>
                )}
                {step === "configure" && "Tell DeckPilot about your class"}
              </h1>
              <p className="mt-1.5 text-sm text-zinc-500">
                {step === "upload" &&
                  "MCQs, theory or mixed — upload it and review every page before a single slide is built."}
                {step === "configure" &&
                  "This tailors the deck. You stay in control at every step."}
              </p>
            </div>
          )}

          <div className="p-6">
            {error && (
              <div className="mb-5 flex items-start gap-3 rounded-xl border border-red-500/20 bg-red-500/8 p-4 animate-slide-down">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
                <div>
                  <p className="text-sm font-medium text-red-300">Something went wrong</p>
                  <p className="mt-0.5 text-xs text-red-400/80">{error}</p>
                </div>
              </div>
            )}

            {/* ── upload ── */}
            {step === "upload" && (
              <div className="space-y-5 animate-fade-in">
                <FileUpload
                  file={file}
                  onFileSelect={(f) => {
                    setFile(f);
                    setPdfUrl("");
                  }}
                  onFileClear={() => setFile(null)}
                />
                <div className="relative">
                  <div className="mb-3 flex items-center gap-3">
                    <div className="h-px flex-1 bg-white/10" />
                    <span className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-600">
                      or
                    </span>
                    <div className="h-px flex-1 bg-white/10" />
                  </div>
                  <label className="mb-2 block text-xs font-medium text-zinc-400">
                    Paste public Google Drive PDF link
                  </label>
                  <div className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/3 px-4 py-3 transition-colors focus-within:border-violet-500/40">
                    <LinkIcon className="h-4 w-4 shrink-0 text-zinc-500" />
                    <input
                      value={pdfUrl}
                      onChange={(e) => {
                        setPdfUrl(e.target.value);
                        if (e.target.value.trim()) setFile(null);
                      }}
                      placeholder="https://drive.google.com/file/d/..."
                      className="min-w-0 flex-1 bg-transparent text-sm text-white placeholder:text-zinc-600 focus:outline-none"
                    />
                  </div>
                </div>
                <button
                  disabled={!hasPdfSource}
                  onClick={() => setStep("configure")}
                  className="flex w-full items-center justify-center gap-2 rounded-xl brand-gradient px-5 py-3 text-sm font-semibold text-white brand-glow-shadow transition-all hover:scale-[1.01] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:scale-100 active:scale-[0.98]"
                >
                  Continue
                  <ChevronRight className="h-4 w-4" />
                </button>

                {/* How it works — sets expectations before the user commits */}
                <div className="grid grid-cols-3 gap-2 pt-1">
                  {[
                    { icon: ScanSearch, label: "Review pages", sub: "AI reads each page" },
                    { icon: Sparkles, label: "Tune the plan", sub: "Edit every slide" },
                    { icon: Compass, label: "Download deck", sub: ".pptx in minutes" },
                  ].map((s, i) => (
                    <div
                      key={s.label}
                      className="animate-fade-up rounded-xl border border-white/6 bg-white/[0.02] p-3 text-center"
                      style={{ animationDelay: `${i * 80}ms` }}
                    >
                      <s.icon className="mx-auto h-4 w-4 text-violet-300" />
                      <p className="mt-1.5 text-[11px] font-semibold text-zinc-200">
                        {s.label}
                      </p>
                      <p className="text-[10px] text-zinc-600">{s.sub}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── configure ── */}
            {step === "configure" && (
              <div className="space-y-5 animate-fade-in">
                <ContextForm context={context} onChange={setContext} />

                {serverOnline === false && (
                  <div className="flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-500/8 px-4 py-3">
                    <WifiOff className="h-4 w-4 shrink-0 text-amber-400" />
                    <p className="text-xs text-amber-300">
                      Backend offline. Start it with{" "}
                      <code className="rounded bg-white/5 px-1 font-mono">
                        uvicorn app:app --reload
                      </code>
                    </p>
                  </div>
                )}

                <div className="flex gap-3">
                  <button
                    onClick={() => setStep("upload")}
                    className="rounded-xl border border-white/8 bg-white/4 px-4 py-3 text-sm font-medium text-zinc-400 transition-all hover:bg-white/8"
                  >
                    Back
                  </button>
                  <button
                    disabled={!isFormValid || serverOnline === false || starting}
                    onClick={handleAnalyse}
                    className="flex flex-1 items-center justify-center gap-2 rounded-xl brand-gradient px-5 py-3 text-sm font-semibold text-white brand-glow-shadow transition-all hover:scale-[1.01] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:scale-100 active:scale-[0.98]"
                  >
                    {starting ? (
                      <>
                        <div className="dp-spinner h-4 w-4" />
                        Reading every page…
                      </>
                    ) : (
                      <>
                        <ScanSearch className="h-4 w-4" />
                        Analyse PDF
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}

            {/* ── review pages ── */}
            {step === "review-pages" && sessionId && (
              <PageReview
                sessionId={sessionId}
                pages={pages}
                onPagesChange={setPages}
                onBack={() => setStep("configure")}
                onContinue={handleBuildPlan}
                building={building}
                notify={notify}
              />
            )}

            {/* ── review plan ── */}
            {step === "review-plan" && sessionId && plan && (
              <PlanReview
                sessionId={sessionId}
                plan={plan}
                onPlanChange={setPlan}
                sourcePages={approvedPageNums}
                detectedQuestions={detectedQuestions}
                onBack={() => setStep("review-pages")}
                onGenerate={handleGenerate}
                generating={generating}
                notify={notify}
              />
            )}

            {/* ── generating ── */}
            {step === "generating" && sessionId && (
              <GeneratingScreen
                sessionId={sessionId}
                onCancel={() => {
                  if (sessionId) endSession(sessionId);
                  setGenerating(false);
                  setStep("review-plan");
                }}
              />
            )}

            {/* ── done ── */}
            {step === "done" && result && (
              <div
                className={
                  previewAvailable && result.filename
                    ? "grid gap-6 md:grid-cols-[1fr_minmax(0,1.4fr)] animate-fade-in"
                    : "mx-auto max-w-md animate-fade-in"
                }
              >
                <DownloadCard
                  result={result}
                  previewAvailable={previewAvailable}
                  onReset={handleReset}
                  onShowAnalytics={() => setShowAnalytics(true)}
                />
                {previewAvailable && result.filename && (
                  <PreviewPane
                    filename={result.filename}
                    previewAvailable={previewAvailable}
                  />
                )}
              </div>
            )}
          </div>
        </div>

        <p className="mt-8 text-xs text-zinc-600">
          DeckPilot · You review every page &amp; slide before it&apos;s built · Powered by Gemini
        </p>
      </main>

      {showAnalytics && result?.analytics && (
        <AnalyticsModal
          analytics={result.analytics}
          onClose={() => setShowAnalytics(false)}
        />
      )}

      <Toaster toasts={toasts} dismiss={dismiss} />
    </div>
  );
}

const SOFT_WARN_MS = 15 * 60 * 1000; // 15 minutes
const HEARTBEAT_MS = 30 * 1000;       // 30 seconds

// Rotating micro-copy — makes the wait feel alive (Devin/Linear pattern: every
// wait state is a trust-building moment).
const GENERATING_TIPS = [
  "Reading your approved pages…",
  "Asking Gemini to write each slide…",
  "Fitting MCQ options into the template…",
  "Keeping every slide faithful to your PDF…",
  "Paginating long theory into clean slides…",
  "Applying your brand styling…",
  "Polishing the final .pptx…",
];

function GeneratingScreen({
  sessionId,
  onCancel,
}: {
  sessionId: string;
  onCancel: () => void;
}) {
  const [elapsedSec, setElapsedSec] = useState(0);
  const [serverUnreachable, setServerUnreachable] = useState(false);
  const [showSoftWarning, setShowSoftWarning] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [tipIndex, setTipIndex] = useState(0);
  const startTime = useRef(Date.now());

  // Rotate the micro-copy every 3.5s
  useEffect(() => {
    const id = setInterval(() => {
      setTipIndex((i) => (i + 1) % GENERATING_TIPS.length);
    }, 3500);
    return () => clearInterval(id);
  }, []);

  // Elapsed timer — ticks every second
  useEffect(() => {
    const id = setInterval(() => {
      const sec = Math.floor((Date.now() - startTime.current) / 1000);
      setElapsedSec(sec);
      if (Date.now() - startTime.current >= SOFT_WARN_MS) {
        setShowSoftWarning(true);
      }
    }, 1000);
    return () => clearInterval(id);
  }, []);

  // Heartbeat — ping session every 30s to detect backend crash
  useEffect(() => {
    let missedBeats = 0;
    const id = setInterval(async () => {
      const alive = await checkSessionAlive(sessionId);
      if (!alive) {
        missedBeats++;
        if (missedBeats >= 2) setServerUnreachable(true);
      } else {
        missedBeats = 0;
        setServerUnreachable(false);
      }
    }, HEARTBEAT_MS);
    return () => clearInterval(id);
  }, [sessionId]);

  const formatTime = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  };

  return (
    <div className="flex flex-col items-center justify-center gap-5 py-12 animate-fade-in">
      <div className="relative flex h-20 w-20 items-center justify-center rounded-3xl brand-gradient shadow-xl shadow-violet-500/30 animate-pulse-ring">
        <Sparkles className="h-9 w-9 text-white" />
      </div>

      <div className="text-center">
        <h2 className="text-lg font-semibold text-white">Building your PowerPoint</h2>
        <p key={tipIndex} className="mt-1.5 h-5 text-sm text-violet-300/90 animate-fade-in">
          {GENERATING_TIPS[tipIndex]}
        </p>
        <p className="mt-2 text-xs text-zinc-600">
          Elapsed: {formatTime(elapsedSec)}
        </p>
      </div>

      <div className="w-full max-w-xs space-y-2">
        {["Extracting & planning", "Writing slide content", "Fitting & paginating", "Generating .pptx"].map(
          (label, i) => (
            <div
              key={label}
              className="flex items-center gap-2 rounded-lg bg-white/3 px-3 py-2 text-xs text-zinc-400 animate-fade-up"
              style={{ animationDelay: `${i * 150}ms` }}
            >
              <div className="dp-spinner h-3.5 w-3.5 shrink-0" />
              {label}
            </div>
          )
        )}
      </div>

      {/* Server unreachable warning */}
      {serverUnreachable && (
        <div className="w-full max-w-xs rounded-xl border border-amber-500/30 bg-amber-500/8 px-4 py-3 animate-fade-up">
          <p className="text-xs font-medium text-amber-300">Server seems unreachable</p>
          <p className="mt-0.5 text-xs text-amber-400/70">
            Your generation may still be running. Check your backend connection.
          </p>
        </div>
      )}

      {/* 15-minute soft warning */}
      {showSoftWarning && !confirmCancel && (
        <div className="w-full max-w-xs rounded-xl border border-orange-500/30 bg-orange-500/8 px-4 py-3 space-y-3 animate-fade-up">
          <p className="text-xs font-medium text-orange-300">Taking longer than usual</p>
          <p className="text-xs text-orange-400/70">
            Generation has been running for {formatTime(elapsedSec)}. Large PDFs with many slides can take 10–15 min. Your deck is likely still being built.
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => setShowSoftWarning(false)}
              className="flex-1 rounded-lg bg-white/8 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-white/12 transition-colors"
            >
              Keep waiting
            </button>
            <button
              onClick={() => setConfirmCancel(true)}
              className="flex-1 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-300 hover:bg-red-500/15 transition-colors"
            >
              Cancel & restart
            </button>
          </div>
        </div>
      )}

      {/* Cancel confirm dialog */}
      {confirmCancel && (
        <div className="w-full max-w-xs rounded-xl border border-red-500/30 bg-red-500/8 px-4 py-3 space-y-3 animate-fade-up">
          <p className="text-xs font-medium text-red-300">Cancel generation?</p>
          <p className="text-xs text-red-400/70">
            This will stop the current run. You&apos;ll go back to the Plan Review step and can try again.
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => setConfirmCancel(false)}
              className="flex-1 rounded-lg bg-white/8 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-white/12 transition-colors"
            >
              Keep waiting
            </button>
            <button
              onClick={onCancel}
              className="flex-1 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-500 transition-colors"
            >
              Yes, cancel
            </button>
          </div>
        </div>
      )}

      {/* Always-visible cancel button */}
      {!confirmCancel && !showSoftWarning && (
        <button
          onClick={() => setConfirmCancel(true)}
          className="mt-2 text-xs text-zinc-600 hover:text-zinc-400 underline underline-offset-2 transition-colors"
        >
          Cancel generation
        </button>
      )}
    </div>
  );
}
