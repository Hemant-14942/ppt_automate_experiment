"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Compass,
  Plus,
  Trash2,
  PencilLine,
  Wand2,
  LayoutGrid,
  Presentation,
  Check,
  GripVertical,
  Sparkles,
  AlertTriangle,
  Images,
  Layers,
} from "lucide-react";

import { PlanResponse, SlideOutlineView, PageExtractionView, FigureView } from "@/types";
import {
  getPlan,
  editSlide,
  rewriteSlide,
  deleteSlide,
  addSlide,
  reorderSlides,
  generateFromSession,
  checkSessionAlive,
  updateFigure,
  getFigureCropURL,
} from "@/lib/api";
import { loadFromStorage, saveToStorage, loadTemplate, saveTemplate } from "@/lib/session-store";
import {
  getSlideType,
  categoryColor,
  CATEGORY_META,
} from "@/lib/slideTypes";
import SlideSchematic from "@/components/SlideSchematic";
import SlideTypeGallery from "@/components/SlideTypeGallery";
import ImageLibrary from "@/components/ImageLibrary";
import ImageStudio from "@/components/ImageStudio";
import SlideInsertControls, {
  SlideInsertMode,
  insertPositionLabel,
  resolveAfterSlideNumber,
} from "@/components/SlideInsertControls";
import { useToasts, Toaster } from "@/components/Toast";

type LoadState = "loading" | "ready" | "no-session" | "expired";

/** Derive a deck-theme accent from the chosen reference template filename. */
function themeAccent(filename: string | null): string {
  const f = (filename || "").toLowerCase();
  if (f.includes("evening")) return "#FFCC31";
  if (f.includes("acchitec") || f.includes("architec")) return "#FFC000";
  return "#f97316";
}

export default function StudioPage() {
  const router = useRouter();
  const { toasts, notify, dismiss } = useToasts();

  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [sourcePages, setSourcePages] = useState<number[]>([]);
  const [detectedQuestions, setDetectedQuestions] = useState(0);

  const [pages, setPages] = useState<PageExtractionView[]>([]);

  const [selectedNum, setSelectedNum] = useState<number | null>(null);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [imagesOpen, setImagesOpen] = useState(false);
  const [studioOpen, setStudioOpen] = useState(false);
  // When set, the Image library opens in "attach to this slide" mode.
  const [attachTarget, setAttachTarget] = useState<{ uid: string; label: string } | null>(null);

  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [flashNum, setFlashNum] = useState<number | null>(null);
  const [refitNum, setRefitNum] = useState<number | null>(null);

  // edit drafts
  const [draftTitle, setDraftTitle] = useState("");
  const [draftPoints, setDraftPoints] = useState("");
  const [feedback, setFeedback] = useState("");

  // add-slide
  const [addPage, setAddPage] = useState(1);
  const [addInsertMode, setAddInsertMode] = useState<SlideInsertMode>("end");
  const [addBetweenAfter, setAddBetweenAfter] = useState(1);

  // drag reorder
  const [dragNum, setDragNum] = useState<number | null>(null);
  const [overNum, setOverNum] = useState<number | null>(null);

  const accent = useMemo(() => themeAccent(selectedTemplate), [selectedTemplate]);

  // ── load session from shared storage ──────────────────────────────────────
  useEffect(() => {
    const saved = loadFromStorage();
    if (!saved?.sessionId) {
      setLoadState("no-session");
      return;
    }
    setSessionId(saved.sessionId);
    // Prefer standalone template key (written immediately when user picks),
    // fall back to session-bundled value for older sessions.
    const tpl = loadTemplate() ?? saved.selectedTemplate ?? null;
    setSelectedTemplate(tpl);

    const savedPages = saved.pages ?? [];
    setPages(savedPages);
    const kept = savedPages.filter((p) => p.status !== "skipped");
    setSourcePages(kept.map((p) => p.page_number));
    setDetectedQuestions(kept.reduce((sum, p) => sum + (p.question_count || 0), 0));
    if (kept.length) setAddPage(kept[0].page_number);

    checkSessionAlive(saved.sessionId).then(async (alive) => {
      if (!alive) {
        setLoadState("expired");
        return;
      }
      try {
        const fresh = saved.plan ?? (await getPlan(saved.sessionId));
        setPlan(fresh);
        setSelectedNum(fresh.slides[0]?.slide_number ?? null);
        setLoadState("ready");
      } catch {
        setLoadState("expired");
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── persist plan back to shared storage so the wizard stays in sync ────────
  useEffect(() => {
    if (plan && sessionId) saveToStorage({ plan });
  }, [plan, sessionId]);

  const handlePagesChange = useCallback(
    (next: PageExtractionView[]) => {
      setPages(next);
      if (sessionId) saveToStorage({ pages: next });
    },
    [sessionId]
  );

  const includedImageCount = useMemo(
    () =>
      pages.reduce(
        (sum, p) => sum + (p.figures ?? []).filter((f) => f.included).length,
        0
      ),
    [pages]
  );

  const selected = useMemo(
    () => plan?.slides.find((s) => s.slide_number === selectedNum) ?? null,
    [plan, selectedNum]
  );

  // Figures the user explicitly pinned to the selected slide (by stable uid).
  const attachedFigures = useMemo(() => {
    const uid = selected?.uid;
    if (!uid) return [] as { page: number; fig: FigureView }[];
    const out: { page: number; fig: FigureView }[] = [];
    for (const p of pages)
      for (const f of p.figures ?? [])
        if (f.attached_slide_uid && f.attached_slide_uid === uid)
          out.push({ page: p.page_number, fig: f });
    return out;
  }, [pages, selected?.uid]);

  const applyFigureEdit = useCallback(
    async (
      page: number,
      figId: string,
      edits: Parameters<typeof updateFigure>[3]
    ) => {
      if (!sessionId) return;
      try {
        const updated = await updateFigure(sessionId, page, figId, edits);
        setPages((prev) => {
          const next = prev.map((p) => (p.page_number === page ? updated : p));
          saveToStorage({ pages: next });
          return next;
        });
      } catch (e) {
        notify((e as Error).message || "Could not update image", "error");
      }
    },
    [sessionId, notify]
  );

  // reset edit drafts whenever the selected slide changes
  useEffect(() => {
    if (selected) {
      setDraftTitle(selected.title);
      setDraftPoints(selected.key_points.join("\n"));
      setFeedback("");
    }
  }, [selected?.slide_number]); // eslint-disable-line react-hooks/exhaustive-deps

  const flash = (n: number) => {
    setFlashNum(n);
    window.setTimeout(() => setFlashNum((c) => (c === n ? null : c)), 1000);
  };

  const replaceSlide = useCallback(
    (s: SlideOutlineView) => {
      setPlan((prev) =>
        prev
          ? {
              ...prev,
              slides: prev.slides.map((x) =>
                x.slide_number === s.slide_number ? s : x
              ),
            }
          : prev
      );
    },
    []
  );

  // ── actions ────────────────────────────────────────────────────────────────
  const changeType = async (typeKey: string) => {
    if (!sessionId || selectedNum == null) return;
    setGalleryOpen(false);
    setBusy(true);
    try {
      const updated = await editSlide(sessionId, selectedNum, { template: typeKey });
      replaceSlide(updated);
      flash(selectedNum);
      setRefitNum(selectedNum);
      notify(`Changed to ${getSlideType(typeKey).label}`, "success");
    } catch (e) {
      notify((e as Error).message || "Could not change type", "error");
    } finally {
      setBusy(false);
    }
  };

  const refitToLayout = async () => {
    if (!sessionId || refitNum == null) return;
    const n = refitNum;
    const label = plan
      ? getSlideType(
          plan.slides.find((s) => s.slide_number === n)?.template ?? ""
        ).label
      : "this";
    setBusy(true);
    try {
      const updated = await rewriteSlide(
        sessionId,
        n,
        `Reformat this slide to fit the "${label}" layout. Keep the same source content but shape it for that layout.`
      );
      replaceSlide(updated);
      flash(n);
      setRefitNum(null);
      notify(`Slide ${n} refitted`, "success");
    } catch (e) {
      notify((e as Error).message || "Rewrite failed", "error");
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = async () => {
    if (!sessionId || selectedNum == null) return;
    setBusy(true);
    try {
      const updated = await editSlide(sessionId, selectedNum, {
        title: draftTitle,
        key_points: draftPoints
          .split("\n")
          .map((x) => x.trim())
          .filter(Boolean),
      });
      replaceSlide(updated);
      flash(selectedNum);
      notify(`Slide ${selectedNum} updated`, "success");
    } catch (e) {
      notify((e as Error).message || "Could not save", "error");
    } finally {
      setBusy(false);
    }
  };

  const saveRewrite = async () => {
    if (!sessionId || selectedNum == null || !feedback.trim()) return;
    setBusy(true);
    try {
      const updated = await rewriteSlide(sessionId, selectedNum, feedback.trim());
      replaceSlide(updated);
      setFeedback("");
      flash(selectedNum);
      notify(`Slide ${selectedNum} rewritten`, "success");
    } catch (e) {
      notify((e as Error).message || "Rewrite failed", "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (n: number) => {
    if (!sessionId) return;
    setBusy(true);
    try {
      const updated = await deleteSlide(sessionId, n);
      setPlan(updated);
      // keep a valid selection
      setSelectedNum((cur) => {
        if (cur !== n) return cur;
        return updated.slides[0]?.slide_number ?? null;
      });
      notify(`Slide ${n} removed`, "info");
    } catch (e) {
      notify((e as Error).message || "Could not remove", "error");
    } finally {
      setBusy(false);
    }
  };

  const handleAdd = async () => {
    if (!sessionId || !plan) return;
    setBusy(true);
    try {
      const lastNum = plan.slides.length
        ? plan.slides[plan.slides.length - 1].slide_number
        : 0;
      const afterNum = resolveAfterSlideNumber(
        addInsertMode,
        addBetweenAfter,
        lastNum
      );
      const updated = await addSlide(sessionId, {
        after_slide_number: afterNum,
        source_page: addPage,
      });
      setPlan(updated);
      const newNum =
        addInsertMode === "end"
          ? updated.slides[updated.slides.length - 1]?.slide_number
          : addInsertMode === "start"
          ? updated.slides[0]?.slide_number
          : updated.slides.find((s) => s.slide_number === afterNum + 1)
              ?.slide_number ?? afterNum + 1;
      setSelectedNum(newNum ?? null);
      notify(
        `Added a slide from page ${addPage} ${insertPositionLabel(addInsertMode, addBetweenAfter)}`,
        "success"
      );
    } catch (e) {
      notify((e as Error).message || "Could not add slide", "error");
    } finally {
      setBusy(false);
    }
  };

  const handleDrop = async (targetNum: number) => {
    const from = dragNum;
    setDragNum(null);
    setOverNum(null);
    if (from == null || from === targetNum || !plan || !sessionId) return;

    const order = plan.slides.map((s) => s.slide_number);
    const fromIdx = order.indexOf(from);
    const toIdx = order.indexOf(targetNum);
    if (fromIdx < 0 || toIdx < 0) return;
    order.splice(toIdx, 0, order.splice(fromIdx, 1)[0]);

    const bySlide = new Map(plan.slides.map((s) => [s.slide_number, s]));
    const reordered = order.map((n, i) => ({
      ...bySlide.get(n)!,
      slide_number: i + 1,
    }));
    // selection follows the dragged slide to its new number
    const newSelected = reordered.find(
      (s) => bySlide.get(from) && s.title === bySlide.get(from)!.title
    );
    setPlan({ ...plan, slides: reordered });
    if (newSelected) setSelectedNum(newSelected.slide_number);

    try {
      const updated = await reorderSlides(sessionId, order);
      setPlan(updated);
    } catch (e) {
      notify((e as Error).message || "Could not reorder", "error");
    }
  };

  const handleGenerate = async () => {
    if (!sessionId) return;
    setGenerating(true);
    try {
      const res = await generateFromSession(sessionId, selectedTemplate);
      saveToStorage({ result: res, step: "done" });
      router.push("/");
    } catch (e) {
      setGenerating(false);
      notify((e as Error).message || "Generation failed", "error");
    }
  };

  // ── non-ready states ───────────────────────────────────────────────────────
  if (loadState !== "ready" || !plan) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        {loadState === "loading" ? (
          <div className="flex items-center gap-3 text-zinc-400">
            <div className="dp-spinner h-5 w-5" /> Loading your deck…
          </div>
        ) : (
          <div className="max-w-sm rounded-3xl border border-white/10 bg-[#1a0e08]/80 p-8 text-center backdrop-blur animate-fade-in">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-500/10 ring-1 ring-amber-500/20">
              <AlertTriangle className="h-5 w-5 text-amber-400" />
            </div>
            <h1 className="text-base font-semibold text-white">
              {loadState === "expired" ? "Your session expired" : "No active deck"}
            </h1>
            <p className="mt-1.5 text-sm text-zinc-500">
              {loadState === "expired"
                ? "The deck you were editing is no longer available. Start again to build a new one."
                : "Open the Slide Studio after you’ve built a slide plan."}
            </p>
            <Link
              href="/"
              className="mt-5 inline-flex items-center gap-2 rounded-xl brand-gradient px-4 py-2.5 text-sm font-semibold text-white brand-glow-shadow transition hover:brightness-110"
            >
              <ArrowLeft className="h-4 w-4" /> Back to start
            </Link>
          </div>
        )}
      </div>
    );
  }

  const selDef = selected ? getSlideType(selected.template) : null;

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* ── top bar ── */}
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-white/8 bg-[#1a0e08]/70 px-5 py-3 backdrop-blur">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex items-center gap-1.5 rounded-lg border border-white/8 bg-white/[0.03] px-3 py-1.5 text-xs font-medium text-zinc-300 transition hover:bg-white/[0.08]"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Plan
          </Link>
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg brand-gradient shadow-lg shadow-orange-500/30">
              <Compass className="h-3.5 w-3.5 text-white" />
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold text-white">Slide Studio</p>
              <p className="text-[11px] text-zinc-500">
                {plan.slides.length} slides · sketch preview
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {/* Template indicator — click to go back to wizard and change */}
          <Link
            href="/?step=choose-template"
            className="hidden sm:flex items-center gap-1.5 rounded-lg border border-white/8 bg-white/[0.03] px-2.5 py-1.5 text-[11px] font-medium text-zinc-400 transition hover:bg-white/[0.06] hover:text-zinc-300"
            title="Click to change template"
          >
            <LayoutGrid className="h-3 w-3 shrink-0" />
            <span className="max-w-[120px] truncate">
              {selectedTemplate
                ? selectedTemplate.replace(".pptx", "").replace(/_/g, " ")
                : "No template"}
            </span>
          </Link>
          <button
            onClick={() => setImagesOpen(true)}
            className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2 text-sm font-medium text-zinc-200 transition hover:bg-white/[0.08]"
          >
            <Images className="h-4 w-4 text-amber-300" />
            Images
            {includedImageCount > 0 && (
              <span className="rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">
                {includedImageCount}
              </span>
            )}
          </button>
          <button
            onClick={() => setStudioOpen(true)}
            className="flex items-center gap-2 rounded-xl border border-violet-500/25 bg-violet-500/8 px-3.5 py-2 text-sm font-medium text-violet-200 transition hover:bg-violet-500/15"
            title="Image Studio — save, generate & AI-edit images"
          >
            <Layers className="h-4 w-4" />
            Image Studio
          </button>
          <button
            onClick={handleGenerate}
            disabled={generating || plan.slides.length === 0}
            title={selectedTemplate ? `Using: ${selectedTemplate}` : "Warning: no template selected"}
            className="flex items-center gap-2 rounded-xl brand-gradient px-4 py-2 text-sm font-semibold text-white brand-glow-shadow transition-all hover:scale-[1.01] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Presentation className="h-4 w-4" /> Generate PowerPoint
          </button>
        </div>
      </header>

      {/* ── body ── */}
      <div className="flex min-h-0 flex-1">
        {/* filmstrip */}
        <aside className="flex w-56 shrink-0 flex-col border-r border-white/8 bg-black/20">
          <div className="flex-1 space-y-2 overflow-y-auto p-3">
            {plan.slides.map((s) => {
              const isSel = s.slide_number === selectedNum;
              const def = getSlideType(s.template);
              return (
                <button
                  key={s.slide_number}
                  draggable
                  onClick={() => setSelectedNum(s.slide_number)}
                  onDragStart={() => setDragNum(s.slide_number)}
                  onDragOver={(e) => {
                    e.preventDefault();
                    if (overNum !== s.slide_number) setOverNum(s.slide_number);
                  }}
                  onDragEnd={() => {
                    setDragNum(null);
                    setOverNum(null);
                  }}
                  onDrop={() => handleDrop(s.slide_number)}
                  className={`group relative w-full rounded-xl border p-2 text-left transition ${
                    isSel
                      ? "border-orange-500/60 bg-orange-500/10 ring-1 ring-orange-500/30"
                      : overNum === s.slide_number && dragNum !== s.slide_number
                      ? "border-orange-400/50"
                      : "border-white/8 bg-white/[0.02] hover:border-white/15 hover:bg-white/[0.05]"
                  } ${dragNum === s.slide_number ? "opacity-50" : ""} ${
                    flashNum === s.slide_number ? "animate-flash" : ""
                  }`}
                >
                  <div className="mb-1.5 flex items-center gap-1.5">
                    <GripVertical className="h-3 w-3 cursor-grab text-zinc-600 group-hover:text-zinc-400" />
                    <span className="text-[10px] font-bold text-zinc-500">
                      {s.slide_number}
                    </span>
                    <span
                      className="rounded px-1.5 py-0.5 text-[9px] font-semibold"
                      style={{
                        color: categoryColor(s.template),
                        background: `${categoryColor(s.template)}1a`,
                      }}
                    >
                      {def.label}
                    </span>
                  </div>
                  <SlideSchematic
                    type={s.template}
                    title={s.title}
                    points={s.key_points}
                    accent={accent}
                    filled
                  />
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(e) => {
                      e.stopPropagation();
                      remove(s.slide_number);
                    }}
                    className="absolute right-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded-md bg-black/50 text-zinc-400 opacity-0 transition hover:text-red-400 group-hover:opacity-100"
                    title="Remove slide"
                  >
                    <Trash2 className="h-3 w-3" />
                  </span>
                </button>
              );
            })}
          </div>

          {/* add slide */}
          <div className="shrink-0 border-t border-white/8 p-3 space-y-2">
            <div className="flex items-center gap-2">
              <select
                value={addPage}
                onChange={(e) => setAddPage(Number(e.target.value))}
                className="min-w-0 flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-xs text-white outline-none"
              >
                {sourcePages.map((p) => (
                  <option key={p} value={p}>
                    Page {p}
                  </option>
                ))}
              </select>
              <button
                onClick={handleAdd}
                disabled={busy}
                className="flex items-center gap-1 rounded-lg bg-white/8 px-2.5 py-1.5 text-xs font-semibold text-zinc-200 transition hover:bg-white/12 disabled:opacity-40"
              >
                <Plus className="h-3.5 w-3.5" /> Add
              </button>
            </div>
            {plan && (
              <SlideInsertControls
                slideCount={plan.slides.length}
                lastSlideNum={
                  plan.slides.length
                    ? plan.slides[plan.slides.length - 1].slide_number
                    : 0
                }
                mode={addInsertMode}
                betweenAfter={addBetweenAfter}
                onModeChange={setAddInsertMode}
                onBetweenAfterChange={setAddBetweenAfter}
              />
            )}
          </div>
        </aside>

        {/* stage */}
        <main className="flex min-w-0 flex-1 flex-col items-center overflow-y-auto p-8">
          {selected ? (
            <div className="w-full max-w-3xl animate-fade-in">
              <div className="mb-3 flex items-center gap-2">
                <span
                  className="rounded-md px-2 py-0.5 text-[11px] font-semibold"
                  style={{
                    color: categoryColor(selected.template),
                    background: `${categoryColor(selected.template)}1a`,
                  }}
                >
                  {selDef?.label}
                </span>
                <span className="text-xs text-zinc-500">
                  Slide {selected.slide_number}
                  {selected.source_pages.length > 0 &&
                    ` · p.${selected.source_pages.join(", ")}`}
                </span>
              </div>

              <SlideSchematic
                type={selected.template}
                title={selected.title}
                points={selected.key_points}
                accent={accent}
                filled
                className="shadow-2xl shadow-black/50"
              />

              <p className="mt-3 text-center text-[11px] text-zinc-600">
                Layout sketch — shows structure &amp; content, not the exact final styling.
              </p>

              {attachedFigures.length > 0 && (
                <div className="mt-5 rounded-2xl border border-white/8 bg-white/[0.02] p-4">
                  <p className="mb-2.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                    <Images className="h-3.5 w-3.5 text-amber-300" />
                    {attachedFigures.length} image
                    {attachedFigures.length > 1 ? "s" : ""} pinned to this slide
                  </p>
                  <div className="flex flex-wrap gap-3">
                    {attachedFigures.map(({ page, fig }) => {
                      const url =
                        fig.has_crop && fig.use_mode === "image"
                          ? getFigureCropURL(sessionId!, page, fig.id, fig.rev)
                          : null;
                      return (
                        <div
                          key={fig.id}
                          className="w-28 overflow-hidden rounded-lg border border-white/10 bg-black/20"
                          title={fig.label}
                        >
                          <div className="flex h-16 w-full items-center justify-center bg-white">
                            {url ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                src={url}
                                alt={fig.label}
                                className="h-full w-full object-contain"
                              />
                            ) : (
                              <span className="px-1 text-center text-[9px] text-zinc-500">
                                {fig.use_mode === "text" ? "Text figure" : "No crop"}
                              </span>
                            )}
                          </div>
                          <p className="truncate px-1.5 py-1 text-[10px] text-zinc-400">
                            {fig.label || "Image"}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              <h1 className="mt-4 text-lg font-semibold text-white">
                {selected.title || "(untitled)"}
              </h1>
              <p className="mt-1 text-sm text-zinc-500">{selDef?.description}</p>
            </div>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-zinc-500">
              Select a slide from the left.
            </div>
          )}
        </main>

        {/* inspector */}
        <aside className="flex w-80 shrink-0 flex-col overflow-y-auto border-l border-white/8 bg-black/20">
          {selected && (
            <div className="space-y-5 p-5">
              {busy && (
                <div className="flex items-center gap-2 text-xs text-orange-300">
                  <div className="dp-spinner h-4 w-4" /> Working…
                </div>
              )}

              {/* slide type */}
              <section>
                <SectionTitle icon={<LayoutGrid className="h-3.5 w-3.5" />}>
                  Slide type
                </SectionTitle>
                <button
                  onClick={() => setGalleryOpen(true)}
                  className="flex w-full items-center justify-between rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-left transition hover:bg-white/[0.07]"
                >
                  <span>
                    <span className="block text-sm font-medium text-white">
                      {selDef?.label}
                    </span>
                    <span className="block text-[11px] text-zinc-500">
                      {CATEGORY_META[selDef!.category].label}
                    </span>
                  </span>
                  <span className="text-xs font-medium text-orange-300">Change</span>
                </button>

                {refitNum === selected.slide_number && (
                  <button
                    onClick={refitToLayout}
                    disabled={busy}
                    className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-orange-500/30 bg-orange-500/10 px-3 py-2 text-xs font-semibold text-orange-200 transition hover:bg-orange-500/15 disabled:opacity-40"
                  >
                    <Wand2 className="h-3.5 w-3.5" /> Rewrite content to fit this layout
                  </button>
                )}
              </section>

              {/* images on this slide */}
              <section>
                <SectionTitle icon={<Images className="h-3.5 w-3.5" />}>
                  Images on this slide
                </SectionTitle>
                {attachedFigures.length === 0 ? (
                  <p className="mb-2 text-[11px] leading-relaxed text-zinc-500">
                    No images pinned here yet. Add one to place it right on this
                    slide.
                  </p>
                ) : (
                  <div className="mb-2 space-y-2">
                    {attachedFigures.map(({ page, fig }) => (
                      <AttachedFigureRow
                        key={fig.id}
                        sessionId={sessionId!}
                        page={page}
                        fig={fig}
                        onEdit={(edits) => applyFigureEdit(page, fig.id, edits)}
                      />
                    ))}
                  </div>
                )}
                <button
                  onClick={() =>
                    selected.uid &&
                    setAttachTarget({
                      uid: selected.uid,
                      label: `Slide ${selected.slide_number}`,
                    })
                  }
                  disabled={!selected.uid}
                  title={
                    selected.uid
                      ? undefined
                      : "Rebuild the plan to enable per-slide image attach"
                  }
                  className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-white/12 bg-white/[0.04] px-3 py-2 text-xs font-semibold text-zinc-200 transition hover:bg-white/[0.08] disabled:opacity-40"
                >
                  <Plus className="h-3.5 w-3.5" /> Add image to this slide
                </button>
              </section>

              {/* edit content */}
              <section>
                <SectionTitle icon={<PencilLine className="h-3.5 w-3.5" />}>
                  Edit content
                </SectionTitle>
                <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                  Title
                </label>
                <input
                  value={draftTitle}
                  onChange={(e) => setDraftTitle(e.target.value)}
                  className="mb-2.5 w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white outline-none focus:border-orange-500/50"
                />
                <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                  Points (one per line)
                </label>
                <textarea
                  value={draftPoints}
                  onChange={(e) => setDraftPoints(e.target.value)}
                  className="min-h-[110px] w-full resize-none rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white outline-none focus:border-orange-500/50"
                />
                <button
                  onClick={saveEdit}
                  disabled={busy}
                  className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg brand-gradient px-3 py-2 text-xs font-semibold text-white transition hover:brightness-110 disabled:opacity-40"
                >
                  <Check className="h-3.5 w-3.5" /> Save changes
                </button>
              </section>

              {/* rewrite */}
              <section>
                <SectionTitle icon={<Wand2 className="h-3.5 w-3.5" />}>
                  Rewrite with AI
                </SectionTitle>
                <textarea
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  placeholder="e.g. Show all four options in full, simplify the language…"
                  className="min-h-[72px] w-full resize-none rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white placeholder-zinc-600 outline-none focus:border-orange-500/50"
                />
                <button
                  onClick={saveRewrite}
                  disabled={busy || !feedback.trim()}
                  className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-white/12 bg-white/[0.04] px-3 py-2 text-xs font-semibold text-zinc-200 transition hover:bg-white/[0.08] disabled:opacity-40"
                >
                  <Wand2 className="h-3.5 w-3.5" /> Rewrite slide
                </button>
              </section>

              {/* danger */}
              <section className="border-t border-white/8 pt-4">
                <button
                  onClick={() => remove(selected.slide_number)}
                  disabled={busy}
                  className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-red-500/20 bg-red-500/[0.06] px-3 py-2 text-xs font-semibold text-red-300 transition hover:bg-red-500/[0.12] disabled:opacity-40"
                >
                  <Trash2 className="h-3.5 w-3.5" /> Delete this slide
                </button>
              </section>
            </div>
          )}
        </aside>
      </div>

      {galleryOpen && selected && (
        <SlideTypeGallery
          currentType={selected.template}
          accent={accent}
          onSelect={changeType}
          onClose={() => setGalleryOpen(false)}
        />
      )}

      {(imagesOpen || attachTarget) && sessionId && (
        <ImageLibrary
          sessionId={sessionId}
          pages={pages}
          onPagesChange={handlePagesChange}
          attachTarget={attachTarget}
          onClose={() => {
            setImagesOpen(false);
            setAttachTarget(null);
          }}
          onOpenStudio={() => {
            setImagesOpen(false);
            setStudioOpen(true);
          }}
          notify={notify}
        />
      )}

      {studioOpen && sessionId && (
        <ImageStudio
          sessionId={sessionId}
          pages={pages}
          onPagesChange={handlePagesChange}
          attachTarget={attachTarget}
          onClose={() => setStudioOpen(false)}
          notify={notify}
        />
      )}

      {generating && (
        <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-5 bg-black/80 backdrop-blur-sm animate-fade-in">
          <div className="relative flex h-20 w-20 items-center justify-center rounded-3xl brand-gradient shadow-xl shadow-orange-500/30 animate-pulse-ring">
            <Sparkles className="h-9 w-9 text-white" />
          </div>
          <div className="text-center">
            <h2 className="text-lg font-semibold text-white">Building your PowerPoint</h2>
            <p className="mt-1.5 text-sm text-orange-300/90">
              Writing slides and assembling the .pptx…
            </p>
          </div>
        </div>
      )}

      <Toaster toasts={toasts} dismiss={dismiss} />
    </div>
  );
}

function SectionTitle({
  children,
  icon,
}: {
  children: React.ReactNode;
  icon: React.ReactNode;
}) {
  return (
    <div className="mb-2.5 flex items-center gap-1.5 text-xs font-semibold text-zinc-300">
      <span className="text-zinc-500">{icon}</span>
      {children}
    </div>
  );
}

function AttachedFigureRow({
  sessionId,
  page,
  fig,
  onEdit,
}: {
  sessionId: string;
  page: number;
  fig: FigureView;
  onEdit: (edits: Parameters<typeof updateFigure>[3]) => void;
}) {
  const url =
    fig.has_crop && fig.use_mode === "image"
      ? getFigureCropURL(sessionId, page, fig.id, fig.rev)
      : null;

  const sizes: FigureView["size"][] = ["small", "medium", "large"];
  const aligns: FigureView["align"][] = ["left", "center", "right"];

  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-2">
      <div className="flex items-center gap-2">
        <div className="flex h-10 w-12 shrink-0 items-center justify-center overflow-hidden rounded-md bg-white">
          {url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={url} alt={fig.label} className="h-full w-full object-contain" />
          ) : (
            <span className="text-[8px] text-zinc-500">
              {fig.use_mode === "text" ? "Text" : "—"}
            </span>
          )}
        </div>
        <p className="min-w-0 flex-1 truncate text-xs font-medium text-white">
          {fig.label || "Image"}
        </p>
        <button
          onClick={() => onEdit({ attached_slide_uid: "" })}
          title="Remove from this slide"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-zinc-400 transition hover:bg-red-500/10 hover:text-red-300"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="mt-2 flex gap-1.5">
        <div className="flex flex-1 gap-0.5 rounded-md bg-black/30 p-0.5">
          {sizes.map((s) => (
            <button
              key={s}
              onClick={() => onEdit({ size: s })}
              className={`flex-1 rounded px-1 py-0.5 text-[9px] font-semibold uppercase transition ${
                fig.size === s
                  ? "bg-amber-500/15 text-amber-200"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {s[0]}
            </button>
          ))}
        </div>
        <div className="flex flex-1 gap-0.5 rounded-md bg-black/30 p-0.5">
          {aligns.map((a) => (
            <button
              key={a}
              onClick={() => onEdit({ align: a })}
              className={`flex-1 rounded px-1 py-0.5 text-[9px] font-semibold capitalize transition ${
                fig.align === a
                  ? "bg-amber-500/15 text-amber-200"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {a[0]}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
