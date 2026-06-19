"use client";

import { useEffect } from "react";
import { X, Check } from "lucide-react";
import SlideSchematic from "@/components/SlideSchematic";
import { PICKABLE_BY_CATEGORY } from "@/lib/slideTypes";

interface SlideTypeGalleryProps {
  currentType: string;
  accent?: string;
  onSelect: (typeKey: string) => void;
  onClose: () => void;
}

/**
 * Full catalog of slide types as schematic cards, grouped by category.
 * Picking a card sets the slide's type (the parent decides what to do next,
 * e.g. offer an AI rewrite to refit the content).
 */
export default function SlideTypeGallery({
  currentType,
  accent,
  onSelect,
  onClose,
}: SlideTypeGalleryProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-fade-in">
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-3xl border border-white/10 bg-[#1a0e08] shadow-2xl shadow-black/60 animate-pop">
        {/* header */}
        <div className="flex items-center justify-between border-b border-white/8 px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-white">Choose a slide type</h2>
            <p className="mt-0.5 text-xs text-zinc-500">
              These are layout sketches — pick the shape that fits this slide&apos;s content.
            </p>
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
          {PICKABLE_BY_CATEGORY.map((group) => (
            <section key={group.meta.key} className="mb-7 last:mb-1">
              <div className="mb-3 flex items-center gap-2">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: group.meta.color }}
                />
                <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                  {group.meta.label}
                </h3>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {group.types.map((t) => {
                  const isCurrent = t.key === currentType;
                  return (
                    <button
                      key={t.key}
                      onClick={() => onSelect(t.key)}
                      className={`group relative flex flex-col rounded-2xl border p-2.5 text-left transition-all hover:scale-[1.02] ${
                        isCurrent
                          ? "border-orange-500/60 bg-orange-500/10 ring-1 ring-orange-500/30"
                          : "border-white/8 bg-white/[0.02] hover:border-white/15 hover:bg-white/[0.05]"
                      }`}
                    >
                      {isCurrent && (
                        <div className="absolute right-2 top-2 z-10 flex h-5 w-5 items-center justify-center rounded-full bg-orange-500">
                          <Check className="h-3 w-3 text-white" />
                        </div>
                      )}
                      <SlideSchematic
                        type={t.key}
                        accent={accent}
                        filled={false}
                        className="mb-2.5"
                      />
                      <p className="text-xs font-semibold text-white">{t.label}</p>
                      <p className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-zinc-500">
                        {t.description}
                      </p>
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
