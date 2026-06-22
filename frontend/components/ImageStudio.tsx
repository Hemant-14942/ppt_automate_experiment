"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  X,
  Wand2,
  Sparkles,
  Trash2,
  Download,
  ChevronLeft,
  Loader2,
  ImagePlus,
  Layers,
  Scissors,
  History,
  Check,
  AlertTriangle,
  Shapes,
  LayoutTemplate,
} from "lucide-react";
import { GalleryImage } from "@/types";
import type { ToastType } from "@/components/Toast";
import {
  getGallery,
  getGalleryImageURL,
  generateGalleryImage,
  editGalleryImage,
  deleteGalleryImage,
  useGalleryImageInDeck,
  updateFigure,
} from "@/lib/api";
import { PageExtractionView } from "@/types";

type GalleryFilter = "all" | "crop" | "generated" | "edited";

interface ImageStudioProps {
  sessionId: string;
  onClose: () => void;
  notify: (message: string, type?: ToastType) => void;
  /** Called with the updated page whenever a gallery image is added to the deck. */
  onPagesChange?: (pages: PageExtractionView[]) => void;
  /** Current pages state — needed to merge the updated page after use-in-deck. */
  pages?: PageExtractionView[];
  /** When set, "Add to deck" pins the image to this slide. */
  attachTarget?: { uid: string; label: string } | null;
}

const SOURCE_META: Record<
  GalleryImage["source"],
  { label: string; color: string; icon: React.ReactNode }
> = {
  crop: {
    label: "PDF Crop",
    color: "text-sky-300 bg-sky-500/10 ring-sky-500/20",
    icon: <Scissors className="h-2.5 w-2.5" />,
  },
  generated: {
    label: "AI Generated",
    color: "text-violet-300 bg-violet-500/10 ring-violet-500/20",
    icon: <Sparkles className="h-2.5 w-2.5" />,
  },
  edited: {
    label: "AI Edited",
    color: "text-amber-300 bg-amber-500/10 ring-amber-500/20",
    icon: <Wand2 className="h-2.5 w-2.5" />,
  },
};

export default function ImageStudio({
  sessionId,
  onClose,
  notify,
  onPagesChange,
  pages,
  attachTarget = null,
}: ImageStudioProps) {
  const [images, setImages] = useState<GalleryImage[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<GalleryFilter>("all");

  // Selected card for AI editing
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editPrompt, setEditPrompt] = useState("");
  const [editing, setEditing] = useState(false);

  // Generate new image modal
  const [genOpen, setGenOpen] = useState(false);
  const [genPrompt, setGenPrompt] = useState("");
  const [genLabel, setGenLabel] = useState("");
  const [generating, setGenerating] = useState(false);

  // Delete confirmation
  const [deleteId, setDeleteId] = useState<string | null>(null);

  // Add to deck
  const [addingToDeck, setAddingToDeck] = useState<string | null>(null); // imageId being added
  const [addedToDeck, setAddedToDeck] = useState<Set<string>>(new Set());

  const editInputRef = useRef<HTMLTextAreaElement>(null);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (genOpen) { setGenOpen(false); return; }
        if (selectedId) { setSelectedId(null); return; }
        onClose();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose, genOpen, selectedId]);

  // Load gallery
  useEffect(() => {
    getGallery(sessionId)
      .then(setImages)
      .catch(() => notify("Could not load gallery", "error"))
      .finally(() => setLoading(false));
  }, [sessionId, notify]);

  const filtered = images.filter(
    (img) => filter === "all" || img.source === filter
  );

  const selected = images.find((img) => img.id === selectedId) ?? null;

  // Build edit version history for selected image
  const editChain = selected
    ? buildEditChain(images, selected)
    : [];

  const handleEdit = useCallback(async () => {
    if (!selectedId || !editPrompt.trim()) return;
    setEditing(true);
    try {
      const newImg = await editGalleryImage(sessionId, selectedId, editPrompt.trim());
      setImages((prev) => [...prev, newImg]);
      setSelectedId(newImg.id);
      setEditPrompt("");
      notify("AI edit applied", "success");
    } catch (e) {
      notify((e as Error).message || "Edit failed", "error");
    } finally {
      setEditing(false);
    }
  }, [sessionId, selectedId, editPrompt, notify]);

  const handleGenerate = useCallback(async () => {
    if (!genPrompt.trim()) return;
    setGenerating(true);
    try {
      const newImg = await generateGalleryImage(
        sessionId,
        genPrompt.trim(),
        genLabel.trim() || undefined
      );
      setImages((prev) => [...prev, newImg]);
      setGenOpen(false);
      setGenPrompt("");
      setGenLabel("");
      setSelectedId(newImg.id);
      notify("Image generated and added to gallery", "success");
    } catch (e) {
      notify((e as Error).message || "Generation failed", "error");
    } finally {
      setGenerating(false);
    }
  }, [sessionId, genPrompt, genLabel, notify]);

  const handleDelete = useCallback(async (id: string) => {
    try {
      const updated = await deleteGalleryImage(sessionId, id);
      setImages(updated);
      if (selectedId === id) setSelectedId(null);
      setDeleteId(null);
      notify("Image removed", "success");
    } catch (e) {
      notify((e as Error).message || "Delete failed", "error");
    }
  }, [sessionId, selectedId, notify]);

  const handleAddToDeck = useCallback(async (id: string) => {
    setAddingToDeck(id);
    try {
      const updatedPage = await useGalleryImageInDeck(sessionId, id);
      let merged = pages
        ? pages.map((p) =>
            p.page_number === updatedPage.page_number ? updatedPage : p
          )
        : [];
      if (pages && !pages.find((p) => p.page_number === updatedPage.page_number)) {
        merged.push(updatedPage);
      }

      const fig =
        updatedPage.figures?.find((f) => f.gallery_id === id) ??
        updatedPage.figures?.find(
          (f) => f.source === "gallery" && f.id.endsWith(id.slice(-8))
        );

      if (attachTarget && fig) {
        const finalPage = await updateFigure(
          sessionId,
          updatedPage.page_number,
          fig.id,
          {
            attached_slide_uid: attachTarget.uid,
            placement: "on_slide",
            included: true,
          }
        );
        merged = merged.map((p) =>
          p.page_number === finalPage.page_number ? finalPage : p
        );
        onPagesChange?.(merged);
        notify(`Pinned to ${attachTarget.label}`, "success");
      } else if (onPagesChange && pages) {
        onPagesChange(merged);
        notify(
          attachTarget
            ? "Added but could not pin — try from the Images panel"
            : "Added to deck — gets its own slide at the end",
          attachTarget ? "error" : "success"
        );
      } else {
        notify("Added to slide deck", "success");
      }
      setAddedToDeck((prev) => new Set(prev).add(id));
    } catch (e) {
      notify((e as Error).message || "Could not add to deck", "error");
    } finally {
      setAddingToDeck(null);
    }
  }, [sessionId, pages, onPagesChange, attachTarget, notify]);

  const handleDownload = (img: GalleryImage) => {
    const url = getGalleryImageURL(sessionId, img.id);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${img.label.replace(/\s+/g, "_")}.png`;
    a.click();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-stretch animate-fade-in">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/75 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="relative flex w-full flex-col overflow-hidden bg-[#130c07] animate-pop">
        {/* ── Header ── */}
        <div className="flex shrink-0 items-center justify-between border-b border-white/8 px-5 py-3.5">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl brand-gradient shadow-md shadow-orange-500/25">
              <Layers className="h-4 w-4 text-white" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white">Image Studio</h2>
              <p className="text-[11px] text-zinc-500">
                {images.length} image{images.length !== 1 ? "s" : ""} in gallery
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Generate new image button */}
            <button
              onClick={() => setGenOpen(true)}
              className="flex items-center gap-2 rounded-xl border border-violet-500/30 bg-violet-500/10 px-3.5 py-2 text-sm font-semibold text-violet-200 transition hover:bg-violet-500/20"
            >
              <Sparkles className="h-3.5 w-3.5" />
              Generate New
            </button>
            <button
              onClick={onClose}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-zinc-400 transition hover:bg-white/8 hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* ── Body: sidebar + grid + edit drawer ── */}
        <div className="flex min-h-0 flex-1 overflow-hidden">

          {/* Filter sidebar */}
          <div className="flex w-36 shrink-0 flex-col gap-1 border-r border-white/8 p-3">
            {(["all", "crop", "generated", "edited"] as GalleryFilter[]).map(
              (f) => {
                const count =
                  f === "all"
                    ? images.length
                    : images.filter((i) => i.source === f).length;
                return (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    className={`flex items-center justify-between rounded-lg px-2.5 py-2 text-xs font-medium transition ${
                      filter === f
                        ? "bg-orange-500/15 text-orange-200 ring-1 ring-orange-500/25"
                        : "text-zinc-500 hover:bg-white/5 hover:text-zinc-300"
                    }`}
                  >
                    <span className="capitalize">{f === "all" ? "All" : SOURCE_META[f as GalleryImage["source"]].label}</span>
                    <span className="rounded-full bg-white/8 px-1.5 py-0.5 text-[9px] font-bold text-zinc-400">
                      {count}
                    </span>
                  </button>
                );
              }
            )}
          </div>

          {/* Image grid */}
          <div className="flex-1 overflow-y-auto p-4">
            {loading ? (
              <div className="flex h-full items-center justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-zinc-600" />
              </div>
            ) : filtered.length === 0 ? (
              <EmptyState filter={filter} onGenerate={() => setGenOpen(true)} />
            ) : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
                {filtered.map((img) => (
                  <GalleryCard
                  key={img.id}
                  img={img}
                  sessionId={sessionId}
                  selected={selectedId === img.id}
                  confirmingDelete={deleteId === img.id}
                  addedToDeck={addedToDeck.has(img.id)}
                  addingToDeck={addingToDeck === img.id}
                  onSelect={() => {
                    setSelectedId(img.id === selectedId ? null : img.id);
                    setEditPrompt("");
                  }}
                  onDelete={() => setDeleteId(img.id)}
                  onDeleteConfirm={() => handleDelete(img.id)}
                  onDeleteCancel={() => setDeleteId(null)}
                  onDownload={() => handleDownload(img)}
                  onAddToDeck={() => handleAddToDeck(img.id)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* AI Edit drawer — shown when a card is selected */}
          {selected && (
            <div className="flex w-72 shrink-0 flex-col border-l border-white/8 bg-[#0f0905] animate-slide-in-right">
              {/* Drawer header */}
              <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
                <p className="text-xs font-semibold text-zinc-300">Edit with AI</p>
                <button
                  onClick={() => setSelectedId(null)}
                  className="flex h-6 w-6 items-center justify-center rounded text-zinc-500 hover:text-white"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
              </div>

              {/* Image preview */}
              <div className="mx-4 mt-4 overflow-hidden rounded-xl border border-white/10 bg-white">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={getGalleryImageURL(sessionId, selected.id)}
                  alt={selected.label}
                  className="h-40 w-full object-contain"
                />
              </div>

              {/* Label */}
              <div className="mx-4 mt-2">
                <p className="truncate text-xs font-medium text-zinc-200">{selected.label}</p>
                <SourceBadge source={selected.source} />
                {selected.prompt && (
                  <p className="mt-1 line-clamp-2 text-[10px] italic text-zinc-600">
                    &ldquo;{selected.prompt}&rdquo;
                  </p>
                )}
              </div>

              {/* Edit prompt */}
              <div className="mx-4 mt-4">
                <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                  Describe the change
                </label>
                <textarea
                  ref={editInputRef}
                  value={editPrompt}
                  onChange={(e) => setEditPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleEdit();
                  }}
                  placeholder={
                    "e.g. make it darker\nconvert to grayscale\nadd more contrast\nmake it watercolor style"
                  }
                  rows={4}
                  className="w-full resize-none rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-xs text-white placeholder-zinc-700 outline-none focus:border-amber-500/40"
                />
                <p className="mt-1 text-[9px] text-zinc-700">⌘+Enter to apply</p>
                <button
                  onClick={handleEdit}
                  disabled={editing || !editPrompt.trim()}
                  className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-200 transition hover:bg-amber-500/15 disabled:opacity-40"
                >
                  {editing ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Editing…
                    </>
                  ) : (
                    <>
                      <Wand2 className="h-3.5 w-3.5" />
                      Apply AI Edit
                    </>
                  )}
                </button>
              </div>

              {/* Edit history chain */}
              {editChain.length > 1 && (
                <div className="mx-4 mt-4">
                  <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                    <History className="h-3 w-3" />
                    Version history
                  </div>
                  <div className="space-y-1">
                    {editChain.map((v, i) => (
                      <button
                        key={v.id}
                        onClick={() => setSelectedId(v.id)}
                        className={`flex w-full items-start gap-2 rounded-lg px-2.5 py-1.5 text-left text-[11px] transition ${
                          v.id === selected.id
                            ? "bg-white/8 text-white"
                            : "text-zinc-500 hover:bg-white/5 hover:text-zinc-300"
                        }`}
                      >
                        <span className="mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border border-current text-[8px] font-bold">
                          {i + 1}
                        </span>
                        <span className="truncate">
                          {i === 0 ? "Original" : v.prompt || "Edit"}
                        </span>
                        {v.id === selected.id && (
                          <Check className="ml-auto h-3 w-3 shrink-0 text-emerald-400" />
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Add to deck */}
              <div className="mx-4 mt-4">
                <button
                  onClick={() => handleAddToDeck(selected.id)}
                  disabled={addingToDeck === selected.id}
                  className={`flex w-full items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-xs font-semibold transition ${
                    addedToDeck.has(selected.id)
                      ? "border border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                      : "brand-gradient text-white hover:brightness-110 disabled:opacity-40"
                  }`}
                >
                  {addingToDeck === selected.id ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Adding…
                    </>
                  ) : addedToDeck.has(selected.id) ? (
                    <>
                      <Check className="h-3.5 w-3.5" />
                      Added to Deck
                    </>
                  ) : (
                    <>
                      <LayoutTemplate className="h-3.5 w-3.5" />
                      Add to Slide Deck
                    </>
                  )}
                </button>
                {addedToDeck.has(selected.id) && (
                  <p className="mt-1.5 text-center text-[10px] text-zinc-600">
                    Open the Images panel to pin it to a specific slide
                  </p>
                )}
              </div>

              {/* Download + delete row */}
              <div className="mx-4 mt-3 mb-4 flex gap-2">
                <button
                  onClick={() => handleDownload(selected)}
                  className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs font-medium text-zinc-300 transition hover:bg-white/8"
                >
                  <Download className="h-3.5 w-3.5" />
                  Download
                </button>
                <button
                  onClick={() => setDeleteId(selected.id)}
                  className="flex items-center justify-center gap-1.5 rounded-lg border border-red-500/20 bg-red-500/[0.06] px-3 py-2 text-xs font-medium text-red-300 transition hover:bg-red-500/10"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Generate New Image Modal ── */}
      {genOpen && (
        <div className="absolute inset-0 z-10 flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => !generating && setGenOpen(false)}
          />
          <div className="relative w-full max-w-md rounded-3xl border border-white/10 bg-[#1a0e08] p-6 shadow-2xl animate-pop">
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-violet-500/15 ring-1 ring-violet-500/25">
                <Sparkles className="h-4.5 w-4.5 text-violet-300" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">Generate Image with AI</h3>
                <p className="text-[11px] text-zinc-500">Powered by Imagen 3</p>
              </div>
              <button
                onClick={() => setGenOpen(false)}
                disabled={generating}
                className="ml-auto flex h-7 w-7 items-center justify-center rounded-lg text-zinc-500 hover:text-white disabled:opacity-40"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <label className="mb-1.5 block text-xs font-semibold text-zinc-400">
              Describe the image
            </label>
            <textarea
              autoFocus
              value={genPrompt}
              onChange={(e) => setGenPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleGenerate();
              }}
              placeholder={
                "e.g. a labelled diagram of a parallel circuit with two bulbs\n" +
                "a force diagram showing Newton's third law\n" +
                "a simple flowchart of the water cycle"
              }
              rows={4}
              className="w-full resize-none rounded-xl border border-white/10 bg-black/20 px-3 py-2.5 text-sm text-white placeholder-zinc-700 outline-none focus:border-violet-500/50"
            />

            <label className="mb-1.5 mt-3 block text-xs font-semibold text-zinc-400">
              Label (optional)
            </label>
            <input
              value={genLabel}
              onChange={(e) => setGenLabel(e.target.value)}
              placeholder="Short name for this image…"
              className="w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-white placeholder-zinc-700 outline-none focus:border-violet-500/50"
            />

            <div className="mt-4 flex gap-2">
              <button
                onClick={() => setGenOpen(false)}
                disabled={generating}
                className="flex-1 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2.5 text-sm font-medium text-zinc-400 transition hover:bg-white/8 disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={handleGenerate}
                disabled={generating || !genPrompt.trim()}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {generating ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Generating…
                  </>
                ) : (
                  <>
                    <ImagePlus className="h-4 w-4" />
                    Generate
                  </>
                )}
              </button>
            </div>

            <p className="mt-3 text-center text-[10px] text-zinc-700">
              ⌘+Enter to generate · Images may take 5–15 seconds
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Helper: build edit version chain ─────────────────────────────────────────

function buildEditChain(images: GalleryImage[], current: GalleryImage): GalleryImage[] {
  // Walk up the parent_id chain to find the root, then collect forward.
  const byId = new Map(images.map((img) => [img.id, img]));

  // Find root
  let root = current;
  const visited = new Set<string>();
  while (root.parent_id && byId.has(root.parent_id) && !visited.has(root.id)) {
    visited.add(root.id);
    root = byId.get(root.parent_id)!;
  }

  // Collect the chain starting from root through descendants (BFS order)
  const chain: GalleryImage[] = [root];
  const queue = [root.id];
  while (queue.length) {
    const parentId = queue.shift()!;
    const children = images
      .filter((img) => img.parent_id === parentId)
      .sort((a, b) => a.created_at - b.created_at);
    for (const child of children) {
      chain.push(child);
      queue.push(child.id);
    }
  }
  return chain;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SourceBadge({ source }: { source: GalleryImage["source"] }) {
  const meta = SOURCE_META[source];
  return (
    <span
      className={`mt-1 inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-semibold ring-1 ${meta.color}`}
    >
      {meta.icon}
      {meta.label}
    </span>
  );
}

function GalleryCard({
  img,
  sessionId,
  selected,
  confirmingDelete,
  addedToDeck,
  addingToDeck,
  onSelect,
  onDelete,
  onDeleteConfirm,
  onDeleteCancel,
  onDownload,
  onAddToDeck,
}: {
  img: GalleryImage;
  sessionId: string;
  selected: boolean;
  confirmingDelete: boolean;
  addedToDeck: boolean;
  addingToDeck: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onDeleteConfirm: () => void;
  onDeleteCancel: () => void;
  onDownload: () => void;
  onAddToDeck: () => void;
}) {
  return (
    <div
      className={`group relative flex flex-col overflow-hidden rounded-2xl border transition ${
        selected
          ? "border-amber-500/50 ring-1 ring-amber-500/25"
          : "border-white/8 hover:border-white/16"
      } bg-white/[0.02]`}
    >
      {/* Delete confirm overlay */}
      {confirmingDelete && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 rounded-2xl bg-black/80 p-3">
          <AlertTriangle className="h-5 w-5 text-red-400" />
          <p className="text-center text-[11px] font-semibold text-white">Remove image?</p>
          <div className="flex gap-1.5">
            <button
              onClick={onDeleteCancel}
              className="rounded-lg border border-white/15 px-2.5 py-1 text-[10px] font-medium text-zinc-300 hover:bg-white/8"
            >
              Cancel
            </button>
            <button
              onClick={onDeleteConfirm}
              className="rounded-lg bg-red-600 px-2.5 py-1 text-[10px] font-semibold text-white hover:bg-red-500"
            >
              Remove
            </button>
          </div>
        </div>
      )}

      {/* Thumbnail */}
      <button
        onClick={onSelect}
        className="aspect-video w-full overflow-hidden bg-white focus:outline-none"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={getGalleryImageURL(sessionId, img.id)}
          alt={img.label}
          className="h-full w-full object-contain"
          loading="lazy"
        />
      </button>

      {/* Card body */}
      <div className="flex flex-col gap-1 p-2">
        <p className="truncate text-[11px] font-medium text-zinc-200">{img.label}</p>
        <SourceBadge source={img.source} />
      </div>

      {/* Hover action strip */}
      <div className="absolute right-1.5 top-1.5 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        <button
          onClick={(e) => { e.stopPropagation(); onAddToDeck(); }}
          title={addedToDeck ? "Already added to deck" : "Add to slide deck"}
          disabled={addingToDeck}
          className={`flex h-6 w-6 items-center justify-center rounded-md ${
            addedToDeck
              ? "bg-emerald-600 text-white"
              : "bg-black/60 text-violet-200 hover:bg-violet-600"
          }`}
        >
          {addingToDeck
            ? <Loader2 className="h-3 w-3 animate-spin" />
            : addedToDeck
            ? <Check className="h-3 w-3" />
            : <LayoutTemplate className="h-3 w-3" />
          }
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); onDownload(); }}
          title="Download"
          className="flex h-6 w-6 items-center justify-center rounded-md bg-black/60 text-zinc-200 hover:bg-black/80"
        >
          <Download className="h-3 w-3" />
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          title="Delete"
          className="flex h-6 w-6 items-center justify-center rounded-md bg-black/60 text-red-300 hover:bg-red-600"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>

      {/* Selected indicator */}
      {selected && (
        <div className="absolute left-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-amber-500">
          <Wand2 className="h-2.5 w-2.5 text-white" />
        </div>
      )}
    </div>
  );
}

function EmptyState({
  filter,
  onGenerate,
}: {
  filter: GalleryFilter;
  onGenerate: () => void;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 py-20 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white/5">
        <Shapes className="h-6 w-6 text-zinc-700" />
      </div>
      <div>
        <p className="text-sm font-semibold text-zinc-300">
          {filter === "all" ? "No images yet" : `No ${SOURCE_META[filter as GalleryImage["source"]]?.label ?? filter} images`}
        </p>
        <p className="mt-1 max-w-xs text-xs text-zinc-600">
          {filter === "all"
            ? "Save figures from the Diagrams panel, or generate brand-new images with AI."
            : filter === "crop"
            ? "Open a page\u2019s Diagrams tab and click \u201cSave to Gallery\u201d on any figure."
            : "Use the Generate New button to create images from a prompt."}
        </p>
      </div>
      {filter !== "crop" && (
        <button
          onClick={onGenerate}
          className="flex items-center gap-2 rounded-xl bg-violet-600/80 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-violet-500"
        >
          <Sparkles className="h-4 w-4" />
          Generate an image
        </button>
      )}
    </div>
  );
}
