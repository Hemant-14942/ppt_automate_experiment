"use client";

import { useState, useCallback, useEffect } from "react";
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

  return (
    <div className="flex min-h-screen flex-col">
      {/* ── Navbar ───────────────────────────────────── */}
      <header className="flex items-center justify-between border-b border-white/5 px-6 py-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg brand-gradient shadow-lg shadow-indigo-500/30">
            <Compass className="h-4 w-4 text-white" />
          </div>
          <span className="text-sm font-semibold text-white">DeckPilot</span>
          <span className="rounded-full bg-indigo-500/10 px-2 py-0.5 text-[10px] font-medium text-indigo-300 ring-1 ring-indigo-500/20">
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
              return (
                <div key={w.step} className="flex items-center gap-2">
                  <div
                    className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-all ${
                      isActive
                        ? "bg-indigo-500/15 text-indigo-200 ring-1 ring-indigo-500/30"
                        : isDone
                        ? "text-zinc-500"
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
          className={`w-full rounded-3xl border border-white/[0.07] bg-[#0c0d13]/80 shadow-2xl shadow-black/50 backdrop-blur ${
            step === "review-pages"
              ? "max-w-6xl"
              : wide
              ? "max-w-5xl"
              : "max-w-xl"
          }`}
        >
          {(step === "upload" || step === "configure") && (
            <div className="border-b border-white/5 px-6 py-5">
              <h1 className="text-base font-semibold text-white">
                {step === "upload" && "Upload your teaching PDF"}
                {step === "configure" && "Tell DeckPilot about your class"}
              </h1>
              <p className="mt-0.5 text-sm text-zinc-500">
                {step === "upload" &&
                  "Any PDF — MCQs, theory, mixed. You'll review every page next."}
                {step === "configure" &&
                  "This tailors the deck. You stay in control at every step."}
              </p>
            </div>
          )}

          <div className="p-6">
            {error && (
              <div className="mb-5 flex items-start gap-3 rounded-xl border border-red-500/20 bg-red-500/8 p-4 animate-fade-up">
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
                  <div className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/3 px-4 py-3 transition-colors focus-within:border-indigo-500/40">
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
                  className="flex w-full items-center justify-center gap-2 rounded-xl brand-gradient px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-30 active:scale-[0.98]"
                >
                  Continue
                  <ChevronRight className="h-4 w-4" />
                </button>
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
                    className="flex flex-1 items-center justify-center gap-2 rounded-xl brand-gradient px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-30 active:scale-[0.98]"
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
            {step === "generating" && <GeneratingScreen />}

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

        <p className="mt-8 text-xs text-zinc-700">
          DeckPilot · You review every page & slide before it&apos;s built · Powered by Gemini
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

function GeneratingScreen() {
  return (
    <div className="flex flex-col items-center justify-center gap-5 py-12 animate-fade-in">
      <div className="relative flex h-20 w-20 items-center justify-center rounded-3xl brand-gradient shadow-xl shadow-indigo-500/30 animate-pulse-ring">
        <Sparkles className="h-9 w-9 text-white" />
      </div>
      <div className="text-center">
        <h2 className="text-lg font-semibold text-white">Building your PowerPoint</h2>
        <p className="mt-1 text-sm text-zinc-500">
          Writing slides, fitting layouts and styling your deck…
        </p>
      </div>
      <div className="w-full max-w-xs space-y-2">
        {["Writing slide content", "Fitting & paginating", "Generating .pptx"].map(
          (label, i) => (
            <div
              key={label}
              className="flex items-center gap-2 rounded-lg bg-white/3 px-3 py-2 text-xs text-zinc-400 animate-fade-up"
              style={{ animationDelay: `${i * 150}ms` }}
            >
              <div className="dp-spinner h-3.5 w-3.5" />
              {label}
            </div>
          )
        )}
      </div>
    </div>
  );
}
