"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import { PageExtractionView, PageIntentMode } from "@/types";
import type { ToastType } from "@/components/Toast";
import {
  getPageImageURL,
  reExtractPage,
  setPageStatus,
  setPageIntent,
} from "@/lib/api";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  SkipForward,
  RotateCcw,
  Sparkles,
  FileText,
  Table2,
  PencilLine,
  CheckCheck,
  Keyboard,
  ZoomIn,
  ZoomOut,
  X,
  ListChecks,
  LayoutList,
  CheckSquare,
  Square,
  MessageSquarePlus,
} from "lucide-react";

interface PageReviewProps {
  sessionId: string;
  pages: PageExtractionView[];
  onPagesChange: (pages: PageExtractionView[]) => void;
  onBack: () => void;
  onContinue: () => void;
  building: boolean;
  notify: (message: string, type?: ToastType) => void;
}

const CONTENT_LABELS: Record<string, string> = {
  text_heavy: "Text",
  diagram: "Diagram",
  mixed: "Mixed",
  table: "Table",
  mostly_blank: "Blank",
};

// Turn a dense extraction blob into readable blocks (questions on their own
// lines, options split out) for the read-only "include everything" view.
function formatExtractionText(text: string): string[] {
  return text
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/([.!?])\s*((?:Q\.?\s*)?\d{1,3}[.)])\s*(?=\S)/g, "$1\n\n$2 ")
    .replace(/(^|\n)\s*((?:Q\.?\s*)?\d{1,3}[.)])\s*(?=\S)/g, "$1$2 ")
    .replace(/(\b[a-dA-D][.)]\s+)/g, "\n$1")
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);
}

export default function PageReview({
  sessionId,
  pages,
  onPagesChange,
  onBack,
  onContinue,
  building,
  notify,
}: PageReviewProps) {
  const [idx, setIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  // Unified instruction box — replaces the old separate "note" + "re-extract" boxes.
  const [showInstBox, setShowInstBox] = useState(false);
  const [instBoxText, setInstBoxText] = useState("");

  // Per-page intent (re-initialised whenever the visible page changes).
  const [mode, setMode] = useState<PageIntentMode>("all");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [instruction, setInstruction] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [trackedPage, setTrackedPage] = useState<number | null>(null);

  const page = pages[idx];
  const items = useMemo(() => page?.items ?? [], [page?.items]);
  const hasItems = items.length > 0;

  // Reset the intent controls when the visible page changes. Adjusting state
  // during render (guarded by a tracked page number) is React's recommended
  // alternative to a setState-in-effect and avoids an extra render pass.
  if (page && trackedPage !== page.page_number) {
    setTrackedPage(page.page_number);
    setMode(page.intent_mode ?? "all");
    setSelectedIds(
      new Set(
        page.selected_item_ids && page.selected_item_ids.length > 0
          ? page.selected_item_ids
          : page.items.map((it) => it.id)
      )
    );
    setInstruction(page.page_instruction ?? "");
    setShowInstBox(Boolean(page.page_instruction));
    setInstBoxText("");
    setExpanded(new Set());
  }

  const approvedCount = useMemo(
    () => pages.filter((p) => p.status === "approved").length,
    [pages]
  );
  const reviewedCount = useMemo(
    () => pages.filter((p) => p.status !== "pending").length,
    [pages]
  );
  const allReviewed = reviewedCount === pages.length;
  const canContinue = allReviewed && approvedCount > 0;

  const extractionBlocks = page?.main_text
    ? formatExtractionText(page.main_text)
    : [];

  const selectedCount = useMemo(
    () => items.filter((it) => selectedIds.has(it.id)).length,
    [items, selectedIds]
  );
  const chooseActive = hasItems && mode === "choose";
  const canKeep = !chooseActive || selectedCount > 0;

  const replacePage = (updated: PageExtractionView) => {
    onPagesChange(
      pages.map((p) => (p.page_number === updated.page_number ? updated : p))
    );
  };

  const goto = (i: number) => {
    setIdx(Math.max(0, Math.min(pages.length - 1, i)));
    setInstBoxText("");
    setShowInstBox(false);
  };

  const toggleItem = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => setSelectedIds(new Set(items.map((it) => it.id)));
  const clearAll = () => setSelectedIds(new Set());

  const handleApprove = async () => {
    if (!page || !canKeep) return;
    setBusy(true);
    try {
      const useChoose = hasItems && mode === "choose";
      // Use whatever is currently typed in the box, or fall back to the
      // previously saved instruction for this page.
      const finalInstruction =
        instBoxText.trim() || instruction.trim() || null;
      await setPageIntent(sessionId, page.page_number, {
        mode: useChoose ? "choose" : "all",
        selected_item_ids: useChoose ? [...selectedIds] : [],
        instruction: finalInstruction,
      });
      const updated = await setPageStatus(sessionId, page.page_number, "approved");
      replacePage(updated);
      if (idx < pages.length - 1) goto(idx + 1);
    } catch (e) {
      notify((e as Error).message || "Could not keep page", "error");
    } finally {
      setBusy(false);
    }
  };

  const handleSkip = async () => {
    if (!page) return;
    setBusy(true);
    try {
      const updated = await setPageStatus(sessionId, page.page_number, "skipped");
      replacePage(updated);
      if (idx < pages.length - 1) goto(idx + 1);
    } catch (e) {
      notify((e as Error).message || "Could not skip page", "error");
    } finally {
      setBusy(false);
    }
  };

  const handleReExtract = async (text: string) => {
    if (!page || !text.trim()) return;
    setBusy(true);
    try {
      const updated = await reExtractPage(sessionId, page.page_number, text.trim());
      replacePage(updated);
      // Keep the instruction visible so user can see what they asked for,
      // but clear the box so they know the request was applied.
      setInstBoxText("");
      notify(`Page ${updated.page_number} re-read by AI`, "success");
    } catch (e) {
      notify((e as Error).message || "Re-extract failed", "error");
    } finally {
      setBusy(false);
    }
  };

  // Keep every remaining page as-is (include everything) — fast path for decks
  // where the AI extraction already looks right.
  const handleKeepAll = async () => {
    const pending = pages.filter((p) => p.status === "pending");
    if (pending.length === 0) return;
    setBusy(true);
    try {
      const updates = await Promise.all(
        pending.map((p) => setPageStatus(sessionId, p.page_number, "approved"))
      );
      const byNum = new Map(updates.map((u) => [u.page_number, u]));
      onPagesChange(pages.map((p) => byNum.get(p.page_number) ?? p));
      notify(`Kept ${updates.length} remaining pages`, "success");
    } catch (e) {
      notify((e as Error).message || "Could not keep all pages", "error");
    } finally {
      setBusy(false);
    }
  };

  // ── keyboard shortcuts: ←/→ navigate, A keep, S skip ──────────────────────
  const onKey = useCallback(
    (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (zoomed) {
        if (e.key === "Escape") setZoomed(false);
        return;
      }
      if (tag === "INPUT" || tag === "TEXTAREA" || showInstBox || busy) return;
      if (e.key === "ArrowLeft") goto(idx - 1);
      else if (e.key === "ArrowRight") goto(idx + 1);
      else if (e.key.toLowerCase() === "a") handleApprove();
      else if (e.key.toLowerCase() === "s") handleSkip();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [idx, busy, page, zoomed, mode, selectedIds, instruction, instBoxText, canKeep]
  );

  useEffect(() => {
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onKey]);

  if (!page) return null;

  const pendingCount = pages.filter((p) => p.status === "pending").length;

  const keepLabel =
    page.status === "approved"
      ? "Kept — next page"
      : chooseActive
      ? `Keep ${selectedCount} selected`
      : "Keep this page";

  return (
    <div className="animate-fade-in">
      {/* Header row */}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3.5">
          {/* Distinctive page counter — large gradient numerator over total */}
          <div className="relative flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl brand-gradient brand-glow-shadow">
            <span className="text-2xl font-extrabold leading-none text-white tabular-nums">
              {page.page_number}
            </span>
            <span className="absolute -bottom-1.5 -right-1.5 flex h-6 min-w-6 items-center justify-center rounded-full bg-[#0d0e18] px-1.5 text-[11px] font-bold text-zinc-400 ring-1 ring-white/10 tabular-nums">
              /{pages.length}
            </span>
          </div>
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-zinc-500">
              Step 1 · Reviewing page
            </p>
            <h2 className="mt-0.5 text-lg font-semibold text-white">
              Page {page.page_number}{" "}
              <span className="text-zinc-600">of {pages.length}</span>
            </h2>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {pendingCount > 0 && (
            <button
              onClick={handleKeepAll}
              disabled={busy}
              className="flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-3 py-1 font-medium text-emerald-300 ring-1 ring-emerald-500/20 transition hover:bg-emerald-500/20 disabled:opacity-40"
            >
              <CheckCheck className="h-3.5 w-3.5" />
              Keep all {pendingCount} remaining
            </button>
          )}
          <span className="rounded-full bg-emerald-500/10 px-3 py-1 font-medium text-emerald-300 ring-1 ring-emerald-500/20">
            {approvedCount} kept
          </span>
          <span className="rounded-full bg-white/5 px-3 py-1 font-medium text-zinc-400 ring-1 ring-white/10">
            {reviewedCount}/{pages.length} reviewed
          </span>
        </div>
      </div>

      {/* Review progress bar — clear sense of how far through the deck */}
      <div className="mb-4">
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/5">
          <div
            className="h-full rounded-full brand-gradient transition-all duration-500 ease-out"
            style={{
              width: `${pages.length ? (reviewedCount / pages.length) * 100 : 0}%`,
            }}
          />
        </div>
      </div>

      {/* Keyboard hint */}
      <div className="mb-4 flex items-center gap-1.5 text-[11px] text-zinc-600">
        <Keyboard className="h-3.5 w-3.5" />
        <span>
          Shortcuts:{" "}
          <kbd className="rounded bg-white/5 px-1 text-zinc-400">←</kbd>{" "}
          <kbd className="rounded bg-white/5 px-1 text-zinc-400">→</kbd> navigate ·{" "}
          <kbd className="rounded bg-white/5 px-1 text-zinc-400">A</kbd> keep ·{" "}
          <kbd className="rounded bg-white/5 px-1 text-zinc-400">S</kbd> skip
        </span>
      </div>

      {/* Thumbnail strip */}
      <div className="mb-5 flex gap-2 overflow-x-auto pb-2">
        {pages.map((p, i) => (
          <button
            key={p.page_number}
            onClick={() => goto(i)}
            className={`relative flex h-9 min-w-9 shrink-0 items-center justify-center rounded-lg px-2 text-xs font-semibold transition-all ${
              i === idx
                ? "bg-violet-500/20 text-violet-200 ring-1 ring-violet-400/50"
                : "bg-white/4 text-zinc-500 ring-1 ring-white/8 hover:bg-white/8"
            }`}
          >
            {p.page_number}
            {p.status === "approved" && (
              <span className="absolute -right-1 -top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-emerald-500 text-[8px] text-white">
                <Check className="h-2.5 w-2.5" />
              </span>
            )}
            {p.status === "skipped" && (
              <span className="absolute -right-1 -top-1 h-3 w-3 rounded-full bg-zinc-600 ring-2 ring-[#08090f]" />
            )}
          </button>
        ))}
      </div>

      {/* Main split — image left (larger), decision panel right */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        {/* Left — page image */}
        <div className="group relative overflow-hidden rounded-2xl border border-white/8 bg-black/40">
          <button
            type="button"
            onClick={() => setZoomed(true)}
            className="block h-full w-full cursor-zoom-in"
            aria-label="Zoom page"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              key={page.page_number}
              src={getPageImageURL(sessionId, page.page_number)}
              alt={`Page ${page.page_number}`}
              className="h-full max-h-[460px] w-full animate-fade-in object-contain sm:max-h-[680px]"
            />
          </button>
          <div className="pointer-events-none absolute left-3 top-3 flex gap-2">
            <span className="rounded-md bg-black/60 px-2 py-1 text-[10px] font-medium text-zinc-300 backdrop-blur">
              {CONTENT_LABELS[page.content_type] ?? page.content_type}
            </span>
            {page.question_count > 0 && (
              <span className="rounded-md bg-violet-500/30 px-2 py-1 text-[10px] font-medium text-violet-100 backdrop-blur">
                {page.question_count} questions
              </span>
            )}
          </div>
          <span className="pointer-events-none absolute bottom-3 right-3 flex items-center gap-1 rounded-md bg-black/60 px-2 py-1 text-[10px] font-medium text-zinc-300 opacity-0 backdrop-blur transition group-hover:opacity-100">
            <ZoomIn className="h-3 w-3" /> Click to zoom
          </span>
        </div>

        {/* Right — decision panel */}
        <div className="flex flex-col rounded-2xl border border-white/8 bg-white/2">
          <div className="flex items-center gap-2 border-b border-white/6 px-4 py-3">
            <Sparkles className="h-4 w-4 text-purple-300" />
            <span className="text-sm font-semibold text-white">
              What goes into the PPT?
            </span>
            {page.should_skip && (
              <span className="ml-auto rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-300 ring-1 ring-amber-500/20">
                AI suggests skipping
              </span>
            )}
          </div>

          {/* Mode segmented control (only when there are pickable items) */}
          {hasItems && (
            <div className="border-b border-white/6 px-4 py-3">
              <div className="flex gap-1 rounded-xl bg-black/30 p-1">
                <button
                  onClick={() => setMode("all")}
                  className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition ${
                    mode === "all"
                      ? "bg-white/10 text-white shadow-sm"
                      : "text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  <LayoutList className="h-3.5 w-3.5" />
                  Include everything
                </button>
                <button
                  onClick={() => setMode("choose")}
                  className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition ${
                    mode === "choose"
                      ? "bg-purple-500/15 text-purple-200 shadow-sm ring-1 ring-purple-500/30"
                      : "text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  <ListChecks className="h-3.5 w-3.5" />
                  Pick questions
                </button>
              </div>
            </div>
          )}

          {/* Body */}
          <div className="relative max-h-[440px] flex-1 overflow-y-auto px-4 py-3">
            {busy && (
              <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-[#0b0c12]/80 backdrop-blur-sm">
                <div className="dp-spinner h-7 w-7" />
                <p className="text-xs text-zinc-400">Working…</p>
              </div>
            )}

            {/* CHOOSE mode — checkbox list of detected items */}
            {chooseActive ? (
              <div className="animate-fade-in">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">
                    {selectedCount} of {items.length} selected
                  </span>
                  <div className="flex gap-2 text-[11px]">
                    <button
                      onClick={selectAll}
                      className="rounded-md px-2 py-0.5 font-medium text-purple-300 transition hover:bg-purple-500/10"
                    >
                      Select all
                    </button>
                    <button
                      onClick={clearAll}
                      className="rounded-md px-2 py-0.5 font-medium text-zinc-500 transition hover:bg-white/5"
                    >
                      Clear
                    </button>
                  </div>
                </div>

                <div className="space-y-2">
                  {items.map((it) => {
                    const checked = selectedIds.has(it.id);
                    const isOpen = expanded.has(it.id);
                    return (
                      <div
                        key={it.id}
                        className={`rounded-xl border transition ${
                          checked
                            ? "border-purple-500/30 bg-purple-500/5"
                            : "border-white/8 bg-black/20"
                        }`}
                      >
                        <div className="flex items-start gap-2.5 px-3 py-2.5">
                          <button
                            onClick={() => toggleItem(it.id)}
                            className="mt-0.5 shrink-0 text-purple-300"
                            aria-label={checked ? "Deselect" : "Select"}
                          >
                            {checked ? (
                              <CheckSquare className="h-4 w-4" />
                            ) : (
                              <Square className="h-4 w-4 text-zinc-600" />
                            )}
                          </button>
                          <button
                            onClick={() => toggleItem(it.id)}
                            className="min-w-0 flex-1 text-left"
                          >
                            <span
                              className={`mr-2 inline-block rounded-md px-1.5 py-0.5 text-[10px] font-bold ${
                                it.kind === "intro"
                                  ? "bg-white/8 text-zinc-300"
                                  : "bg-violet-500/20 text-violet-200"
                              }`}
                            >
                              {it.label}
                            </span>
                            <span className="text-[12.5px] leading-relaxed text-zinc-300">
                              {it.preview}
                            </span>
                          </button>
                          <button
                            onClick={() => toggleExpanded(it.id)}
                            className="mt-0.5 shrink-0 text-zinc-500 transition hover:text-zinc-300"
                            aria-label="Expand"
                          >
                            <ChevronDown
                              className={`h-4 w-4 transition-transform ${
                                isOpen ? "rotate-180" : ""
                              }`}
                            />
                          </button>
                        </div>
                        {isOpen && (
                          <pre className="animate-fade-in whitespace-pre-wrap wrap-break-word border-t border-white/6 px-3 py-2 font-sans text-[12.5px] leading-relaxed text-zinc-400">
                            {it.text}
                          </pre>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : (
              /* ALL mode — read-only formatted extraction */
              <div className="animate-fade-in">
                <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-zinc-500">
                  <FileText className="h-3.5 w-3.5" /> AI read this from the page
                </div>
                {extractionBlocks.length > 0 ? (
                  <div className="space-y-2.5 text-[13px] leading-relaxed text-zinc-300">
                    {extractionBlocks.map((block, blockIdx) => (
                      <p
                        key={`${page.page_number}-${blockIdx}`}
                        className="whitespace-pre-wrap wrap-break-word rounded-lg border border-white/6 bg-black/15 px-3 py-2"
                      >
                        {block}
                      </p>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm italic text-zinc-600">
                    No text extracted from this page.
                  </p>
                )}
              </div>
            )}

            {/* meta chips */}
            <div className="mt-3 flex flex-wrap gap-2">
              {page.has_table && (
                <span className="flex items-center gap-1 rounded-md bg-white/5 px-2 py-1 text-[10px] text-zinc-400">
                  <Table2 className="h-3 w-3" /> Table detected
                </span>
              )}
              {page.detected_language && (
                <span className="flex items-center gap-1 rounded-md bg-white/5 px-2 py-1 text-[10px] text-zinc-400">
                  <FileText className="h-3 w-3" /> {page.detected_language}
                </span>
              )}
            </div>

            {page.last_feedback && (
              <p className="mt-3 rounded-lg border border-purple-500/15 bg-purple-500/5 px-3 py-2 text-[11px] text-purple-200/80">
                Last correction: “{page.last_feedback}”
              </p>
            )}
          </div>

          {/* Bottom action panel */}
          <div className="border-t border-white/6">

            {/* ── Section A: Instruction / Fix ── */}
            <div className="px-4 pt-3 pb-2">
              {/* Collapsed trigger — always visible when box is hidden */}
              {!showInstBox && (
                <button
                  onClick={() => setShowInstBox(true)}
                  className="group flex w-full items-center gap-3 rounded-xl border border-white/8 bg-white/2 px-3 py-2.5 text-left transition hover:border-white/15 hover:bg-white/5"
                >
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white/5 text-zinc-400 transition group-hover:bg-violet-500/15 group-hover:text-violet-300">
                    <PencilLine className="h-3.5 w-3.5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-[12px] font-medium text-zinc-300">
                      {instruction ? "Edit your instruction" : "Give the AI an instruction"}
                    </p>
                    {instruction ? (
                      <p className="truncate text-[11px] text-zinc-500">{instruction}</p>
                    ) : (
                      <p className="text-[11px] text-zinc-600">
                        Fix extraction errors · include only specific questions
                      </p>
                    )}
                  </div>
                  {instruction && (
                    <span className="shrink-0 rounded-full bg-purple-500/15 px-2 py-0.5 text-[10px] font-medium text-purple-300">
                      Saved
                    </span>
                  )}
                </button>
              )}

              {/* Expanded instruction box */}
              {showInstBox && (
                <div className="animate-fade-up rounded-xl border border-white/10 bg-white/2 p-3">
                  {/* Header row */}
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
                      Your instruction to the AI
                    </p>
                    <button
                      onClick={() => { setShowInstBox(false); setInstBoxText(""); }}
                      className="rounded-md p-0.5 text-zinc-600 transition hover:text-zinc-300"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>

                  <textarea
                    autoFocus
                    value={instBoxText}
                    onChange={(e) => setInstBoxText(e.target.value)}
                    placeholder="e.g. include only Q5, Q7 and Q9  ·  Q15 text is wrong  ·  ignore the page header"
                    rows={2}
                    className="min-h-[52px] w-full resize-none rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-[13px] text-white placeholder-zinc-600 outline-none transition focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/25"
                  />

                  {/* Two action rows with clear purpose labels */}
                  <div className="mt-2.5 flex flex-col gap-2">
                    {/* Action 1 — Re-read (AI updates extraction immediately) */}
                    <button
                      onClick={() => handleReExtract(instBoxText)}
                      disabled={!instBoxText.trim() || busy}
                      className="group flex items-center gap-3 rounded-lg border border-purple-500/25 bg-purple-500/8 px-3 py-2.5 text-left transition hover:border-purple-500/40 hover:bg-purple-500/15 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-purple-500/15 text-purple-300">
                        <RotateCcw className="h-3.5 w-3.5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-[12px] font-semibold text-purple-200">
                          Re-read this page with my instruction
                        </p>
                        <p className="text-[10px] text-purple-300/50">
                          AI extracts again → extraction panel updates → you verify
                        </p>
                      </div>
                    </button>

                    {/* Divider with OR */}
                    <div className="flex items-center gap-2">
                      <div className="h-px flex-1 bg-white/6" />
                      <span className="text-[10px] font-medium text-zinc-600">OR</span>
                      <div className="h-px flex-1 bg-white/6" />
                    </div>

                    {/* Action 2 — Just save as a note (no re-read) */}
                    <div className="flex items-start gap-3 rounded-lg border border-white/6 bg-white/2 px-3 py-2.5">
                      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white/5 text-zinc-400">
                        <MessageSquarePlus className="h-3.5 w-3.5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-[12px] font-medium text-zinc-300">
                          Just save as a note
                        </p>
                        <p className="text-[10px] text-zinc-600">
                          Extraction stays as-is. Your note is passed to the AI planner when building slides.
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* ── Section B: Final decision (Skip / Keep) ── */}
            <div className="flex items-center gap-2 border-t border-white/6 px-4 py-3">
              <button
                onClick={handleSkip}
                disabled={busy}
                className={`flex items-center justify-center gap-1.5 rounded-lg border px-3 py-2.5 text-xs font-semibold transition disabled:opacity-40 ${
                  page.status === "skipped"
                    ? "border-zinc-600 bg-zinc-700/40 text-zinc-300"
                    : "border-white/10 text-zinc-400 hover:bg-white/5"
                }`}
              >
                <SkipForward className="h-3.5 w-3.5" />
                Skip
              </button>
              <button
                onClick={handleApprove}
                disabled={busy || !canKeep}
                title={
                  !canKeep ? "Select at least one question, or switch to Include everything" : ""
                }
                className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${
                  page.status === "approved"
                    ? "bg-emerald-500/90 text-[#042016] hover:bg-emerald-400"
                    : "brand-gradient text-white shadow-lg shadow-violet-500/20 hover:brightness-110"
                }`}
              >
                <Check className="h-3.5 w-3.5" />
                {keepLabel}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Nav footer */}
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <button
            onClick={onBack}
            className="rounded-xl border border-white/8 bg-white/3 px-4 py-2.5 text-sm font-medium text-zinc-400 transition hover:bg-white/8"
          >
            Back
          </button>
          <button
            onClick={() => goto(idx - 1)}
            disabled={idx === 0}
            className="flex items-center gap-1 rounded-xl border border-white/8 bg-white/3 px-3 py-2.5 text-sm font-medium text-zinc-400 transition hover:bg-white/8 disabled:opacity-30"
          >
            <ChevronLeft className="h-4 w-4" /> Prev
          </button>
          <button
            onClick={() => goto(idx + 1)}
            disabled={idx === pages.length - 1}
            className="flex items-center gap-1 rounded-xl border border-white/8 bg-white/3 px-3 py-2.5 text-sm font-medium text-zinc-400 transition hover:bg-white/8 disabled:opacity-30"
          >
            Next <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        <button
          onClick={onContinue}
          disabled={!canContinue || building}
          title={
            !canContinue
              ? "Review every page (keep or skip) and keep at least one"
              : ""
          }
          className="flex items-center gap-2 rounded-xl brand-gradient px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/25 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-30"
        >
          {building ? (
            <>
              <div className="dp-spinner h-4 w-4" />
              Planning…
            </>
          ) : (
            <>
              Build slide plan
              <ChevronRight className="h-4 w-4" />
            </>
          )}
        </button>
      </div>

      {/* Zoom lightbox */}
      {zoomed && (
        <div
          onClick={() => setZoomed(false)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4 backdrop-blur-sm animate-fade-in"
        >
          <button
            onClick={() => setZoomed(false)}
            className="absolute right-4 top-4 flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/20"
            aria-label="Close zoom"
          >
            <X className="h-5 w-5" />
          </button>
          <button
            onClick={() => setZoomed(false)}
            className="absolute left-1/2 top-4 flex -translate-x-1/2 items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-sm font-medium text-white transition hover:bg-white/20"
            aria-label="Zoom out"
          >
            <ZoomOut className="h-4 w-4" />
            Zoom out
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={getPageImageURL(sessionId, page.page_number)}
            alt={`Page ${page.page_number} enlarged`}
            onClick={(e) => {
              e.stopPropagation();
              setZoomed(false);
            }}
            className="max-h-[92vh] max-w-full cursor-zoom-out animate-pop rounded-lg object-contain shadow-2xl"
          />
        </div>
      )}
    </div>
  );
}
