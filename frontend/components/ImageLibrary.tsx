"use client";

import { useEffect, useMemo, useState } from "react";
import {
  X,
  Image as ImageIcon,
  Type,
  FileImage,
  Pin,
  Eye,
  EyeOff,
  Shapes,
  Info,
} from "lucide-react";
import { FigureView, PageExtractionView } from "@/types";
import type { ToastType } from "@/components/Toast";
import { getFigureCropURL, updateFigure } from "@/lib/api";

interface ImageLibraryProps {
  sessionId: string;
  pages: PageExtractionView[];
  onPagesChange: (pages: PageExtractionView[]) => void;
  onClose: () => void;
  notify: (message: string, type?: ToastType) => void;
  /** When set, the library is in "attach to a specific slide" mode. */
  attachTarget?: { uid: string; label: string } | null;
}

interface FlatFigure {
  page: number;
  questions: string[];
  fig: FigureView;
}

type FigureEdits = Parameters<typeof updateFigure>[3];

/**
 * Session-wide image gallery. Surfaces every diagram/figure the AI detected or
 * the user cropped, across all pages, and lets the user control how each one
 * lands in the final deck: included, image vs text, its own slide vs on the
 * question, plus size and left/right position (multiple "on question" figures
 * tile side-by-side).
 */
export default function ImageLibrary({
  sessionId,
  pages,
  onPagesChange,
  onClose,
  notify,
  attachTarget = null,
}: ImageLibraryProps) {
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const figures: FlatFigure[] = useMemo(() => {
    const out: FlatFigure[] = [];
    for (const p of pages) {
      const questions = (p.items ?? [])
        .filter((it) => it.kind === "question")
        .map((it) => it.label)
        .filter(Boolean);
      for (const f of p.figures ?? [])
        out.push({ page: p.page_number, questions, fig: f });
    }
    return out;
  }, [pages]);

  const includedCount = figures.filter((f) => f.fig.included).length;

  const applyEdit = async (page: number, figId: string, edits: FigureEdits) => {
    setBusyId(figId);
    try {
      const updated = await updateFigure(sessionId, page, figId, edits);
      onPagesChange(
        pages.map((p) => (p.page_number === page ? updated : p))
      );
    } catch (e) {
      notify((e as Error).message || "Could not update image", "error");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-fade-in">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative flex max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-3xl border border-white/10 bg-[#1a0e08] shadow-2xl shadow-black/60 animate-pop">
        {/* header */}
        <div className="flex items-center justify-between border-b border-white/8 px-6 py-4">
          <div className="flex items-center gap-2.5">
            {attachTarget ? (
              <Pin className="h-4 w-4 text-amber-300" />
            ) : (
              <Shapes className="h-4 w-4 text-amber-300" />
            )}
            <div>
              <h2 className="text-base font-semibold text-white">
                {attachTarget ? `Add image to ${attachTarget.label}` : "Image library"}
              </h2>
              <p className="mt-0.5 text-xs text-zinc-500">
                {attachTarget
                  ? "Pick an image to pin onto this exact slide."
                  : `${includedCount} of ${figures.length} images will be placed in your deck`}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/8 bg-white/[0.03] text-zinc-400 transition hover:bg-white/[0.08] hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* body */}
        <div className="overflow-y-auto px-6 py-5">
          {figures.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/5">
                <Shapes className="h-5 w-5 text-zinc-600" />
              </div>
              <p className="text-sm font-medium text-zinc-300">No images detected yet</p>
              <p className="max-w-sm text-xs text-zinc-500">
                Diagrams and formulas the AI finds (or that you crop in the Pages
                step) will collect here for you to place anywhere in the deck.
              </p>
            </div>
          ) : (
            <>
              <div className="mb-4 flex items-start gap-2.5 rounded-xl border border-amber-500/15 bg-amber-500/5 p-3">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
                <p className="text-[11px] leading-relaxed text-amber-200/80">
                  Each image can sit on <span className="font-semibold text-amber-200">its own slide</span>{" "}
                  (great for copy-pasting later) or be pinned{" "}
                  <span className="font-semibold text-amber-200">on the question</span> it belongs to.
                  Set its <span className="font-semibold text-amber-200">size</span> and{" "}
                  <span className="font-semibold text-amber-200">position</span> — multiple images pinned
                  to the same question tile side-by-side automatically.
                </p>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {figures.map(({ page, questions, fig }) => (
                  <ImageCard
                    key={fig.id}
                    sessionId={sessionId}
                    page={page}
                    questions={questions}
                    fig={fig}
                    attachTarget={attachTarget}
                    busy={busyId === fig.id}
                    onEdit={(edits) => applyEdit(page, fig.id, edits)}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function ImageCard({
  sessionId,
  page,
  questions,
  fig,
  attachTarget,
  busy,
  onEdit,
}: {
  sessionId: string;
  page: number;
  questions: string[];
  fig: FigureView;
  attachTarget?: { uid: string; label: string } | null;
  busy: boolean;
  onEdit: (edits: FigureEdits) => void;
}) {
  const cropUrl = fig.has_crop
    ? getFigureCropURL(sessionId, page, fig.id, fig.rev)
    : null;
  const excluded = !fig.included;
  const onSlide = fig.placement === "on_slide";

  const pinnedUid = fig.attached_slide_uid || "";
  const attachedHere = !!attachTarget && pinnedUid === attachTarget.uid;
  const attachedElsewhere = !!attachTarget && !!pinnedUid && !attachedHere;

  const [name, setName] = useState(fig.label || "");
  useEffect(() => setName(fig.label || ""), [fig.label]);

  const commitName = () => {
    const next = name.trim();
    if (next !== (fig.label || "")) onEdit({ label: next });
  };

  return (
    <div
      className={`flex flex-col overflow-hidden rounded-2xl border bg-white/[0.02] transition ${
        attachedHere
          ? "border-emerald-500/50 ring-1 ring-emerald-500/30"
          : excluded
          ? "border-white/8 opacity-55"
          : "border-white/10"
      }`}
    >
      {/* preview */}
      <div className="relative aspect-video w-full overflow-hidden bg-white">
        {cropUrl && fig.use_mode === "image" ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={cropUrl}
            alt={fig.label || "Diagram"}
            className="h-full w-full object-contain"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-[#14110f] px-4 text-center">
            <p className="line-clamp-4 text-[11px] leading-relaxed text-zinc-400">
              {fig.use_mode === "text"
                ? fig.description || fig.label || "Text figure"
                : "No image crop available"}
            </p>
          </div>
        )}
        <span className="absolute left-2 top-2 flex items-center gap-1">
          <span className="rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-semibold text-zinc-200">
            p.{page}
          </span>
          {fig.belongs_to && (
            <span className="rounded bg-amber-500/80 px-1.5 py-0.5 text-[10px] font-semibold text-black">
              {fig.belongs_to}
            </span>
          )}
        </span>
        <button
          onClick={() => onEdit({ included: excluded })}
          disabled={busy}
          title={excluded ? "Add to deck" : "Remove from deck"}
          className="absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-md bg-black/60 text-zinc-200 transition hover:bg-black/80 disabled:opacity-40"
        >
          {excluded ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
        </button>
      </div>

      {/* controls */}
      <div className="flex flex-1 flex-col gap-2.5 p-3">
        {attachTarget && (
          <button
            onClick={() =>
              onEdit(
                attachedHere
                  ? { attached_slide_uid: "" }
                  : {
                      attached_slide_uid: attachTarget.uid,
                      placement: "on_slide",
                      included: true,
                    }
              )
            }
            disabled={busy}
            className={`flex w-full items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition disabled:opacity-40 ${
              attachedHere
                ? "border border-emerald-500/30 bg-emerald-500/15 text-emerald-200 hover:bg-emerald-500/20"
                : "brand-gradient text-white hover:brightness-110"
            }`}
          >
            <Pin className="h-3.5 w-3.5" />
            {attachedHere
              ? "Pinned here — click to remove"
              : attachedElsewhere
              ? "Move to this slide"
              : "Add to this slide"}
          </button>
        )}

        {/* nickname */}
        <div>
          <p className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-zinc-600">
            Name
          </p>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={commitName}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            }}
            placeholder="Name this image…"
            disabled={busy}
            className="w-full rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs font-medium text-white placeholder-zinc-600 outline-none transition focus:border-amber-500/50 disabled:opacity-50"
          />
        </div>

        {/* question reference */}
        <QuestionPicker
          value={fig.belongs_to || ""}
          questions={questions}
          disabled={busy}
          onChange={(v) => onEdit({ belongs_to: v })}
        />

        <Segmented
          label="Show as"
          value={fig.use_mode}
          disabled={busy}
          options={[
            { value: "image", label: "Image", icon: <ImageIcon className="h-3 w-3" />, disabled: !fig.has_crop },
            { value: "text", label: "Text", icon: <Type className="h-3 w-3" /> },
          ]}
          onChange={(v) => onEdit({ use_mode: v as "image" | "text" })}
        />

        <Segmented
          label="Place on"
          value={fig.placement}
          disabled={busy}
          options={[
            { value: "own_slide", label: "Own slide", icon: <FileImage className="h-3 w-3" /> },
            { value: "on_slide", label: "Question", icon: <Pin className="h-3 w-3" /> },
          ]}
          onChange={(v) => onEdit({ placement: v as "own_slide" | "on_slide" })}
        />

        <Segmented
          label="Size"
          value={fig.size}
          disabled={busy}
          options={[
            { value: "small", label: "S" },
            { value: "medium", label: "M" },
            { value: "large", label: "L" },
          ]}
          onChange={(v) => onEdit({ size: v as "small" | "medium" | "large" })}
        />

        {onSlide && (
          <Segmented
            label="Position"
            value={fig.align}
            disabled={busy}
            options={[
              { value: "left", label: "Left" },
              { value: "center", label: "Center" },
              { value: "right", label: "Right" },
            ]}
            onChange={(v) => onEdit({ align: v as "left" | "center" | "right" })}
          />
        )}
      </div>
    </div>
  );
}

const CUSTOM_SENTINEL = "__custom__";

function QuestionPicker({
  value,
  questions,
  onChange,
  disabled,
}: {
  value: string;
  questions: string[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  // "custom" when there's a value that isn't one of the detected questions.
  const valueIsKnown = value !== "" && questions.includes(value);
  const [custom, setCustom] = useState(value !== "" && !valueIsKnown);
  const [draft, setDraft] = useState(valueIsKnown ? "" : value);

  useEffect(() => {
    const known = value !== "" && questions.includes(value);
    setCustom(value !== "" && !known);
    setDraft(known ? "" : value);
  }, [value, questions]);

  const selectValue = custom ? CUSTOM_SENTINEL : value;

  return (
    <div>
      <p className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-zinc-600">
        Belongs to (question / reference)
      </p>
      <select
        value={selectValue}
        disabled={disabled}
        onChange={(e) => {
          const v = e.target.value;
          if (v === CUSTOM_SENTINEL) {
            setCustom(true);
            setDraft("");
          } else {
            setCustom(false);
            onChange(v);
          }
        }}
        className="w-full rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white outline-none transition focus:border-amber-500/50 disabled:opacity-50"
      >
        <option value="">— Not linked —</option>
        {questions.map((q) => (
          <option key={q} value={q}>
            {q}
          </option>
        ))}
        <option value={CUSTOM_SENTINEL}>Custom…</option>
      </select>
      {custom && (
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => onChange(draft.trim())}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
          placeholder="e.g. Q.7 or Hartley oscillator"
          disabled={disabled}
          autoFocus
          className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white placeholder-zinc-600 outline-none transition focus:border-amber-500/50 disabled:opacity-50"
        />
      )}
    </div>
  );
}

function Segmented({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  options: { value: string; label: string; icon?: React.ReactNode; disabled?: boolean }[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <div>
      <p className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-zinc-600">
        {label}
      </p>
      <div className="flex gap-1 rounded-lg bg-black/30 p-0.5">
        {options.map((o) => {
          const active = o.value === value;
          return (
            <button
              key={o.value}
              onClick={() => !o.disabled && onChange(o.value)}
              disabled={disabled || o.disabled}
              title={o.disabled ? "Not available for this image" : undefined}
              className={`flex flex-1 items-center justify-center gap-1 rounded-md px-1.5 py-1 text-[10px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-30 ${
                active
                  ? "bg-amber-500/15 text-amber-200 ring-1 ring-amber-500/30"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {o.icon}
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
