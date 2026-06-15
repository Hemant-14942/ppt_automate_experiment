"use client";

import { useState } from "react";
import { FigureView, PageExtractionView } from "@/types";
import type { ToastType } from "@/components/Toast";
import { getFigureCropURL, updateFigure, deleteFigure } from "@/lib/api";
import {
  Image as ImageIcon,
  Type,
  Info,
  Tag,
  Shapes,
  AlertTriangle,
  Ban,
  Undo2,
  Plus,
  Trash2,
  Pin,
  FileImage,
} from "lucide-react";

interface DiagramsPanelProps {
  sessionId: string;
  page: PageExtractionView;
  onPageUpdate: (updated: PageExtractionView) => void;
  notify: (message: string, type?: ToastType) => void;
  highlightId: string | null;
  onHighlight: (id: string | null) => void;
  addMode: boolean;
  onToggleAddMode: () => void;
}

const TYPE_LABELS: Record<string, string> = {
  circuit: "Circuit",
  geometry: "Figure",
  graph: "Graph",
  formula: "Formula",
  flowchart: "Flowchart",
  figure: "Figure",
  other: "Diagram",
};

export default function DiagramsPanel({
  sessionId,
  page,
  onPageUpdate,
  notify,
  highlightId,
  onHighlight,
  addMode,
  onToggleAddMode,
}: DiagramsPanelProps) {
  const figures = page.figures ?? [];
  const keptCount = figures.filter((f) => f.included).length;

  return (
    <div className="flex flex-col rounded-2xl border border-white/8 bg-white/2">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-white/6 px-4 py-3">
        <Shapes className="h-4 w-4 text-amber-300" />
        <span className="text-sm font-semibold text-white">
          Diagrams &amp; formulas
        </span>
        <span className="ml-auto rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-300 ring-1 ring-amber-500/20">
          {keptCount} of {figures.length} kept
        </span>
        <button
          onClick={onToggleAddMode}
          className={`flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold transition ${
            addMode
              ? "bg-emerald-500/90 text-[#042016]"
              : "bg-white/8 text-zinc-300 ring-1 ring-white/10 hover:bg-white/12"
          }`}
        >
          <Plus className="h-3.5 w-3.5" />
          {addMode ? "Drawing…" : "Add"}
        </button>
      </div>

      {/* Body */}
      <div className="max-h-[560px] flex-1 overflow-y-auto px-4 py-3">
        {figures.length === 0 ? (
          <EmptyState />
        ) : (
          <>
            {/* Info banner — sets expectation about what this tab does */}
            <div className="mb-3 flex items-start gap-2.5 rounded-xl border border-amber-500/15 bg-amber-500/5 p-3">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
              <p className="text-[11px] leading-relaxed text-amber-200/80">
                Boxes on the left are the AI&apos;s estimate — <span className="font-semibold text-amber-200">drag</span>{" "}
                to move or pull the corner to <span className="font-semibold text-amber-200">resize</span>{" "}
                for a tighter crop. Missed one? Hit <span className="font-semibold text-amber-200">Add</span>{" "}
                and draw a box. For each figure choose{" "}
                <span className="font-semibold text-amber-200">image vs text</span>, whether it gets{" "}
                <span className="font-semibold text-amber-200">its own slide</span> or sits{" "}
                <span className="font-semibold text-amber-200">on the question</span>, or{" "}
                <span className="font-semibold text-amber-200">remove</span> it entirely.
              </p>
            </div>

            <div className="space-y-3">
              {figures.map((fig) => (
                <FigureCard
                  key={fig.id}
                  sessionId={sessionId}
                  page={page}
                  figure={fig}
                  onPageUpdate={onPageUpdate}
                  notify={notify}
                  highlighted={highlightId === fig.id}
                  onHighlight={onHighlight}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-14 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/5">
        <Shapes className="h-5 w-5 text-zinc-600" />
      </div>
      <div>
        <p className="text-sm font-medium text-zinc-300">
          No diagrams detected on this page
        </p>
        <p className="mx-auto mt-1 max-w-[18rem] text-[11px] leading-relaxed text-zinc-600">
          This page looks like text only. If it actually has a diagram or formula
          the AI missed, hit{" "}
          <span className="font-medium text-amber-300">Add</span> above and draw a
          box around it on the page.
        </p>
      </div>
    </div>
  );
}

interface FigureCardProps {
  sessionId: string;
  page: PageExtractionView;
  figure: FigureView;
  onPageUpdate: (updated: PageExtractionView) => void;
  notify: (message: string, type?: ToastType) => void;
  highlighted: boolean;
  onHighlight: (id: string | null) => void;
}

function FigureCard({
  sessionId,
  page,
  figure,
  onPageUpdate,
  notify,
  highlighted,
  onHighlight,
}: FigureCardProps) {
  const [label, setLabel] = useState(figure.label || "");
  const [belongsTo, setBelongsTo] = useState(figure.belongs_to || "");
  const [saving, setSaving] = useState(false);
  // Cache-bust the crop image with `rev` so adjusting the box refreshes it.
  const cropUrl = figure.has_crop
    ? getFigureCropURL(sessionId, page.page_number, figure.id, figure.rev)
    : null;

  const typeLabel = TYPE_LABELS[(figure.diagram_type || "other").toLowerCase()] ?? "Diagram";

  const persist = async (edits: {
    label?: string;
    belongs_to?: string;
    use_mode?: "image" | "text";
    included?: boolean;
    placement?: "own_slide" | "on_slide";
  }) => {
    setSaving(true);
    try {
      const updated = await updateFigure(
        sessionId,
        page.page_number,
        figure.id,
        edits
      );
      onPageUpdate(updated);
    } catch (e) {
      notify((e as Error).message || "Could not save change", "error");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    setSaving(true);
    try {
      const updated = await deleteFigure(sessionId, page.page_number, figure.id);
      onPageUpdate(updated);
    } catch (e) {
      notify((e as Error).message || "Could not delete figure", "error");
    } finally {
      setSaving(false);
    }
  };

  const chooseMode = (mode: "image" | "text") => {
    if (mode === figure.use_mode) return;
    if (mode === "image" && !figure.has_crop) {
      notify("No image crop available for this figure", "info");
      return;
    }
    persist({ use_mode: mode });
  };

  const excluded = !figure.included;

  return (
    <div
      onMouseEnter={() => onHighlight(figure.id)}
      onMouseLeave={() => onHighlight(null)}
      className={`relative rounded-xl border bg-white/2 p-3 transition ${
        excluded
          ? "border-white/8 opacity-55"
          : highlighted
          ? "border-amber-500/50 ring-1 ring-amber-500/30"
          : "border-white/8"
      }`}
    >
      {/* Top row — type badge + question link + delete */}
      <div className="mb-2.5 flex items-center gap-2">
        <span className="rounded-md bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300">
          {typeLabel}
        </span>
        {figure.source === "manual" && (
          <span className="rounded-md bg-sky-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-sky-300">
            Added
          </span>
        )}
        {excluded && (
          <span className="rounded-md bg-zinc-700/50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-400">
            Removed
          </span>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          <Tag className="h-3 w-3 text-zinc-600" />
          <input
            value={belongsTo}
            onChange={(e) => setBelongsTo(e.target.value)}
            onBlur={() => {
              if ((belongsTo || "") !== (figure.belongs_to || ""))
                persist({ belongs_to: belongsTo });
            }}
            placeholder="Q.?"
            className="w-16 rounded-md border border-white/10 bg-black/20 px-2 py-1 text-[11px] text-zinc-200 placeholder-zinc-600 outline-none transition focus:border-amber-500/50"
          />
          <button
            onClick={remove}
            disabled={saving}
            title="Delete this figure"
            className="rounded-md p-1 text-zinc-600 transition hover:bg-red-500/10 hover:text-red-300 disabled:opacity-40"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Crop preview */}
      <div className="mb-2.5 overflow-hidden rounded-lg border border-white/8 bg-white">
        {cropUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={cropUrl}
            alt={figure.description || "Diagram crop"}
            className="max-h-44 w-full object-contain"
          />
        ) : (
          <div className="flex items-center gap-2 bg-white/3 px-3 py-4 text-[11px] text-zinc-500">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />
            No image region was located — only the text description is available.
          </div>
        )}
      </div>

      {/* Label edit */}
      <input
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        onBlur={() => {
          if ((label || "") !== (figure.label || "")) persist({ label });
        }}
        placeholder="Label this diagram…"
        className="mb-2 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-[12px] font-medium text-white placeholder-zinc-600 outline-none transition focus:border-amber-500/50"
      />

      {/* Description (Option A text) */}
      {figure.description && (
        <p className="mb-2.5 line-clamp-3 text-[11px] leading-relaxed text-zinc-500">
          {figure.description}
        </p>
      )}

      {/* Image vs Text choice */}
      <div>
        <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
          On the slide, use:
        </p>
        <div className="flex gap-1 rounded-xl bg-black/30 p-1">
          <button
            onClick={() => chooseMode("image")}
            disabled={saving || !figure.has_crop}
            title={
              figure.has_crop ? "" : "No image crop available for this figure"
            }
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-[11px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${
              figure.use_mode === "image"
                ? "bg-amber-500/15 text-amber-200 ring-1 ring-amber-500/30"
                : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            <ImageIcon className="h-3.5 w-3.5" />
            Image
          </button>
          <button
            onClick={() => chooseMode("text")}
            disabled={saving}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-[11px] font-semibold transition disabled:opacity-40 ${
              figure.use_mode === "text"
                ? "bg-white/10 text-white ring-1 ring-white/15"
                : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            <Type className="h-3.5 w-3.5" />
            Text
          </button>
        </div>
      </div>

      {/* Placement — own slide vs on the question slide */}
      <div className="mt-2.5">
        <p className="mb-1.5 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
          Place it on:
        </p>
        <div className="flex gap-1 rounded-xl bg-black/30 p-1">
          <button
            onClick={() => persist({ placement: "own_slide" })}
            disabled={saving}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-[11px] font-semibold transition disabled:opacity-40 ${
              figure.placement === "own_slide"
                ? "bg-amber-500/15 text-amber-200 ring-1 ring-amber-500/30"
                : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            <FileImage className="h-3.5 w-3.5" />
            Its own slide
          </button>
          <button
            onClick={() => persist({ placement: "on_slide" })}
            disabled={saving}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-[11px] font-semibold transition disabled:opacity-40 ${
              figure.placement === "on_slide"
                ? "bg-amber-500/15 text-amber-200 ring-1 ring-amber-500/30"
                : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            <Pin className="h-3.5 w-3.5" />
            On the question
          </button>
        </div>
      </div>

      {/* Include / Remove from deck */}
      <button
        onClick={() => persist({ included: excluded })}
        disabled={saving}
        className={`mt-2.5 flex w-full items-center justify-center gap-1.5 rounded-lg border px-2 py-1.5 text-[11px] font-semibold transition disabled:opacity-40 ${
          excluded
            ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
            : "border-white/10 text-zinc-500 hover:border-red-500/30 hover:bg-red-500/10 hover:text-red-300"
        }`}
      >
        {excluded ? (
          <>
            <Undo2 className="h-3.5 w-3.5" />
            Add back to deck
          </>
        ) : (
          <>
            <Ban className="h-3.5 w-3.5" />
            Remove from deck
          </>
        )}
      </button>
    </div>
  );
}
