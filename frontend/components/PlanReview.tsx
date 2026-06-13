"use client";

import { useState } from "react";
import { PlanResponse, SlideOutlineView } from "@/types";
import type { ToastType } from "@/components/Toast";
import {
  rewriteSlide,
  editSlide,
  deleteSlide,
  addSlide,
  reorderSlides,
} from "@/lib/api";
import {
  Trash2,
  PencilLine,
  Wand2,
  Plus,
  Check,
  X,
  Presentation,
  ChevronRight,
  Layers,
  AlertCircle,
  GripVertical,
} from "lucide-react";

interface PlanReviewProps {
  sessionId: string;
  plan: PlanResponse;
  onPlanChange: (plan: PlanResponse) => void;
  sourcePages: number[];
  detectedQuestions: number;
  onBack: () => void;
  onGenerate: () => void;
  generating: boolean;
  notify: (message: string, type?: ToastType) => void;
}

const QUESTION_TEMPLATES = new Set([
  "mcq_slide",
  "mcq_grid_slide",
  "question_only",
  "pyq_slide",
  "pyq_grid_slide",
  "pyq_question_only",
]);

const TEMPLATE_LABELS: Record<string, string> = {
  title_slide: "Title",
  recap_slide: "Recap",
  topics_slide: "Topics",
  section_heading: "Section",
  theory_slide: "Theory",
  table_slide: "Table",
  theory_table_slide: "Theory + Table",
  passage_slide: "Passage",
  mcq_slide: "MCQ",
  mcq_grid_slide: "MCQ Grid",
  question_only: "Question",
  pyq_slide: "PYQ",
  pyq_grid_slide: "PYQ Grid",
  pyq_question_only: "PYQ",
  summary: "Summary",
  homework_slide: "Homework",
  thank_you_slide: "Thank You",
};

function templateTone(t: string): string {
  if (t.startsWith("mcq") || t === "question_only") return "text-indigo-300 bg-indigo-500/10 ring-indigo-500/20";
  if (t.startsWith("pyq")) return "text-fuchsia-300 bg-fuchsia-500/10 ring-fuchsia-500/20";
  if (t.includes("table")) return "text-amber-300 bg-amber-500/10 ring-amber-500/20";
  if (t === "theory_slide" || t === "passage_slide") return "text-cyan-300 bg-cyan-500/10 ring-cyan-500/20";
  return "text-zinc-300 bg-white/5 ring-white/10";
}

export default function PlanReview({
  sessionId,
  plan,
  onPlanChange,
  sourcePages,
  detectedQuestions,
  onBack,
  onGenerate,
  generating,
  notify,
}: PlanReviewProps) {
  const [openId, setOpenId] = useState<number | null>(null);
  const [mode, setMode] = useState<"edit" | "rewrite" | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftPoints, setDraftPoints] = useState("");
  const [feedback, setFeedback] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [addPage, setAddPage] = useState<number>(sourcePages[0] ?? 1);
  const [addNote, setAddNote] = useState("");
  const [dragNum, setDragNum] = useState<number | null>(null);
  const [overNum, setOverNum] = useState<number | null>(null);

  const replaceSlide = (s: SlideOutlineView) => {
    onPlanChange({
      ...plan,
      slides: plan.slides.map((x) => (x.slide_number === s.slide_number ? s : x)),
    });
  };

  const openEdit = (s: SlideOutlineView) => {
    setOpenId(s.slide_number);
    setMode("edit");
    setDraftTitle(s.title);
    setDraftPoints(s.key_points.join("\n"));
  };
  const openRewrite = (s: SlideOutlineView) => {
    setOpenId(s.slide_number);
    setMode("rewrite");
    setFeedback("");
  };
  const closePanel = () => {
    setOpenId(null);
    setMode(null);
  };

  const saveEdit = async (n: number) => {
    setBusyId(n);
    try {
      const updated = await editSlide(sessionId, n, {
        title: draftTitle,
        key_points: draftPoints
          .split("\n")
          .map((x) => x.trim())
          .filter(Boolean),
      });
      replaceSlide(updated);
      closePanel();
      notify(`Slide ${n} updated`, "success");
    } catch (e) {
      notify((e as Error).message || "Could not save slide", "error");
    } finally {
      setBusyId(null);
    }
  };

  const saveRewrite = async (n: number) => {
    if (!feedback.trim()) return;
    setBusyId(n);
    try {
      const updated = await rewriteSlide(sessionId, n, feedback.trim());
      replaceSlide(updated);
      closePanel();
      notify(`Slide ${n} rewritten`, "success");
    } catch (e) {
      notify((e as Error).message || "Rewrite failed", "error");
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (n: number) => {
    setBusyId(n);
    try {
      const updated = await deleteSlide(sessionId, n);
      onPlanChange(updated);
      closePanel();
      notify(`Slide ${n} removed`, "info");
    } catch (e) {
      notify((e as Error).message || "Could not remove slide", "error");
    } finally {
      setBusyId(null);
    }
  };

  const handleAdd = async () => {
    setAdding(true);
    try {
      const lastNum = plan.slides.length
        ? plan.slides[plan.slides.length - 1].slide_number
        : 0;
      const updated = await addSlide(sessionId, {
        after_slide_number: lastNum,
        source_page: addPage,
        feedback: addNote.trim() || undefined,
      });
      onPlanChange(updated);
      setAddNote("");
      notify(`Added a slide from page ${addPage}`, "success");
    } catch (e) {
      notify((e as Error).message || "Could not add slide", "error");
    } finally {
      setAdding(false);
    }
  };

  // ── drag to reorder ───────────────────────────────────────────────────────
  const handleDrop = async (targetNum: number) => {
    const from = dragNum;
    setDragNum(null);
    setOverNum(null);
    if (from == null || from === targetNum) return;

    const order = plan.slides.map((s) => s.slide_number);
    const fromIdx = order.indexOf(from);
    const toIdx = order.indexOf(targetNum);
    if (fromIdx < 0 || toIdx < 0) return;
    order.splice(toIdx, 0, order.splice(fromIdx, 1)[0]);

    // Optimistic UI: reorder locally first, then persist.
    const bySlide = new Map(plan.slides.map((s) => [s.slide_number, s]));
    const reordered = order.map((n, i) => ({
      ...bySlide.get(n)!,
      slide_number: i + 1,
    }));
    onPlanChange({ ...plan, slides: reordered });

    try {
      const updated = await reorderSlides(sessionId, order);
      onPlanChange(updated);
    } catch (e) {
      notify((e as Error).message || "Could not reorder", "error");
    }
  };

  return (
    <div className="animate-fade-in">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-500">
            Step 2 · Review the slide plan
          </p>
          <h2 className="mt-1 text-lg font-semibold text-white">
            <span className="brand-text">{plan.total_slides} slides</span> planned
          </h2>
        </div>
        <span className="flex items-center gap-1.5 rounded-full bg-white/5 px-3 py-1 text-xs text-zinc-400 ring-1 ring-white/10">
          <Layers className="h-3.5 w-3.5" /> Drag to reorder · edit · rewrite · remove
        </span>
      </div>

      {/* Coverage hint — compares detected questions vs question slides planned */}
      {(() => {
        const qSlides = plan.slides.filter((s) =>
          QUESTION_TEMPLATES.has(s.template)
        ).length;
        if (detectedQuestions === 0) return null;
        const short = detectedQuestions - qSlides;
        if (short > 0) {
          return (
            <div className="mb-4 flex items-start gap-2.5 rounded-xl border border-amber-500/20 bg-amber-500/8 px-4 py-3 animate-fade-up">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
              <p className="text-xs text-amber-200/90">
                Detected <strong>{detectedQuestions}</strong> questions in your
                kept pages but only <strong>{qSlides}</strong> question slides are
                planned. If any are missing, use{" "}
                <strong>“Add a slide from page”</strong> below to include them.
              </p>
            </div>
          );
        }
        return (
          <div className="mb-4 flex items-center gap-2.5 rounded-xl border border-emerald-500/20 bg-emerald-500/8 px-4 py-3 animate-fade-up">
            <Check className="h-4 w-4 shrink-0 text-emerald-400" />
            <p className="text-xs text-emerald-200/90">
              All <strong>{detectedQuestions}</strong> detected questions are
              covered by <strong>{qSlides}</strong> question slides.
            </p>
          </div>
        );
      })()}

      {/* Slide list */}
      <div className="max-h-[440px] space-y-2 overflow-y-auto pr-1">
        {plan.slides.map((s, i) => {
          const isOpen = openId === s.slide_number;
          return (
            <div
              key={`${s.slide_number}-${i}`}
              draggable
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
              className={`animate-fade-up rounded-xl border bg-white/[0.02] transition ${
                overNum === s.slide_number && dragNum !== s.slide_number
                  ? "border-indigo-400/60 ring-1 ring-indigo-400/40"
                  : "border-white/8 hover:border-white/12"
              } ${dragNum === s.slide_number ? "opacity-50" : ""}`}
              style={{ animationDelay: `${Math.min(i * 25, 300)}ms` }}
            >
              <div className="flex items-start gap-2 p-3">
                <span
                  className="mt-1 cursor-grab text-zinc-600 transition hover:text-zinc-400 active:cursor-grabbing"
                  title="Drag to reorder"
                >
                  <GripVertical className="h-4 w-4" />
                </span>
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white/5 text-[11px] font-bold text-zinc-400">
                  {s.slide_number}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold ring-1 ${templateTone(
                        s.template
                      )}`}
                    >
                      {TEMPLATE_LABELS[s.template] ?? s.template}
                    </span>
                    {s.source_pages.length > 0 && (
                      <span className="text-[10px] text-zinc-600">
                        p.{s.source_pages.join(", ")}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 truncate text-sm font-medium text-zinc-200">
                    {s.title || "(untitled)"}
                  </p>
                  {s.key_points.length > 0 && (
                    <p className="mt-0.5 truncate text-xs text-zinc-500">
                      {s.key_points.join(" · ")}
                    </p>
                  )}
                </div>

                <div className="flex shrink-0 items-center gap-1">
                  <IconBtn title="Edit" onClick={() => openEdit(s)}>
                    <PencilLine className="h-3.5 w-3.5" />
                  </IconBtn>
                  <IconBtn title="Rewrite with AI" onClick={() => openRewrite(s)}>
                    <Wand2 className="h-3.5 w-3.5" />
                  </IconBtn>
                  <IconBtn
                    title="Remove"
                    onClick={() => remove(s.slide_number)}
                    danger
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </IconBtn>
                </div>
              </div>

              {/* Inline edit / rewrite panel */}
              {isOpen && (
                <div className="animate-fade-up border-t border-white/6 p-3">
                  {busyId === s.slide_number && (
                    <div className="mb-3 flex items-center gap-2 text-xs text-cyan-300">
                      <div className="dp-spinner h-4 w-4" /> Working…
                    </div>
                  )}
                  {mode === "edit" && (
                    <div className="space-y-2">
                      <label className="block text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                        Title
                      </label>
                      <input
                        value={draftTitle}
                        onChange={(e) => setDraftTitle(e.target.value)}
                        className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white outline-none focus:border-indigo-500/50"
                      />
                      <label className="block text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                        Points (one per line)
                      </label>
                      <textarea
                        value={draftPoints}
                        onChange={(e) => setDraftPoints(e.target.value)}
                        className="min-h-[80px] w-full resize-none rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white outline-none focus:border-indigo-500/50"
                      />
                      <PanelActions
                        onSave={() => saveEdit(s.slide_number)}
                        onCancel={closePanel}
                        saveLabel="Save"
                        disabled={busyId === s.slide_number}
                      />
                    </div>
                  )}
                  {mode === "rewrite" && (
                    <div className="space-y-2">
                      <label className="block text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                        Tell the AI how to change this slide
                      </label>
                      <textarea
                        autoFocus
                        value={feedback}
                        onChange={(e) => setFeedback(e.target.value)}
                        placeholder="e.g. Show all four options in full, make this a theory slide…"
                        className="min-h-[72px] w-full resize-none rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-white placeholder-zinc-600 outline-none focus:border-cyan-500/50"
                      />
                      <PanelActions
                        onSave={() => saveRewrite(s.slide_number)}
                        onCancel={closePanel}
                        saveLabel="Rewrite"
                        disabled={!feedback.trim() || busyId === s.slide_number}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Add slide */}
      <div className="mt-3 rounded-xl border border-dashed border-white/12 bg-white/[0.01] p-3">
        {adding ? (
          <div className="flex items-center gap-2 text-xs text-cyan-300">
            <div className="dp-spinner h-4 w-4" /> Adding slide…
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex items-center gap-1.5 text-xs font-medium text-zinc-400">
              <Plus className="h-3.5 w-3.5" /> Add a slide from page
            </span>
            <select
              value={addPage}
              onChange={(e) => setAddPage(Number(e.target.value))}
              className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-xs text-white outline-none"
            >
              {sourcePages.map((p) => (
                <option key={p} value={p}>
                  Page {p}
                </option>
              ))}
            </select>
            <input
              value={addNote}
              onChange={(e) => setAddNote(e.target.value)}
              placeholder="What should it contain? (optional)"
              className="min-w-[180px] flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-white placeholder-zinc-600 outline-none focus:border-indigo-500/50"
            />
            <button
              onClick={handleAdd}
              className="rounded-lg bg-white/8 px-3 py-1.5 text-xs font-semibold text-zinc-200 transition hover:bg-white/12"
            >
              Add
            </button>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="mt-6 flex items-center justify-between">
        <button
          onClick={onBack}
          className="rounded-xl border border-white/8 bg-white/[0.03] px-4 py-2.5 text-sm font-medium text-zinc-400 transition hover:bg-white/[0.07]"
        >
          Back to pages
        </button>
        <button
          onClick={onGenerate}
          disabled={generating || plan.slides.length === 0}
          className="flex items-center gap-2 rounded-xl brand-gradient px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-500/25 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-30"
        >
          {generating ? (
            <>
              <div className="dp-spinner h-4 w-4" /> Generating…
            </>
          ) : (
            <>
              <Presentation className="h-4 w-4" /> Generate PowerPoint
              <ChevronRight className="h-4 w-4" />
            </>
          )}
        </button>
      </div>
    </div>
  );
}

function IconBtn({
  children,
  onClick,
  title,
  danger,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title: string;
  danger?: boolean;
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      className={`flex h-7 w-7 items-center justify-center rounded-lg border border-white/8 bg-white/[0.03] transition hover:bg-white/[0.08] ${
        danger ? "text-zinc-500 hover:text-red-400" : "text-zinc-400 hover:text-white"
      }`}
    >
      {children}
    </button>
  );
}

function PanelActions({
  onSave,
  onCancel,
  saveLabel,
  disabled,
}: {
  onSave: () => void;
  onCancel: () => void;
  saveLabel: string;
  disabled?: boolean;
}) {
  return (
    <div className="flex gap-2 pt-1">
      <button
        onClick={onSave}
        disabled={disabled}
        className="flex items-center gap-1.5 rounded-lg brand-gradient px-3 py-1.5 text-xs font-semibold text-white transition hover:brightness-110 disabled:opacity-40"
      >
        <Check className="h-3.5 w-3.5" />
        {saveLabel}
      </button>
      <button
        onClick={onCancel}
        className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-medium text-zinc-400 transition hover:bg-white/5"
      >
        <X className="h-3.5 w-3.5" />
        Cancel
      </button>
    </div>
  );
}
