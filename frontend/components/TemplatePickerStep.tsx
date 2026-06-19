"use client";

import { useEffect, useState } from "react";
import { TemplateOption } from "@/types";
import { fetchTemplates } from "@/lib/api";
import { LayoutTemplate, ChevronRight, Check, Loader2 } from "lucide-react";

// Visual preview icons per template — a simple decorative "slide shape" shows
// the colour accent for each template so the user can distinguish them at a glance.
const TEMPLATE_ACCENTS: Record<string, { bg: string; accent: string; label: string }> = {
  common_template:           { bg: "#1a0e08",  accent: "#f97316", label: "Orange" },
  clat_common_template_1:    { bg: "#0f1a1f",  accent: "#FFCC31", label: "Gold" },
  acchitecture_format:       { bg: "#0d1a0f",  accent: "#FFC000", label: "Amber" },
};

function TemplateMiniPreview({ id }: { id: string }) {
  const style = TEMPLATE_ACCENTS[id] ?? { bg: "#18181b", accent: "#a1a1aa", label: "" };
  return (
    <div
      className="relative mx-auto mb-3 h-20 w-36 overflow-hidden rounded-lg shadow-md"
      style={{ backgroundColor: style.bg }}
    >
      {/* Fake slide heading bar */}
      <div
        className="absolute left-3 top-3 h-2.5 rounded-sm"
        style={{ width: "52%", backgroundColor: style.accent, opacity: 0.9 }}
      />
      {/* Fake content lines */}
      {[28, 38, 48, 58].map((top) => (
        <div
          key={top}
          className="absolute left-3 h-1.5 rounded-sm bg-white/20"
          style={{ top, width: `${top % 2 === 0 ? 72 : 55}%` }}
        />
      ))}
      {/* Accent dot top-right */}
      <div
        className="absolute right-2 top-2 h-3 w-3 rounded-full"
        style={{ backgroundColor: style.accent, opacity: 0.8 }}
      />
    </div>
  );
}

interface TemplatePickerStepProps {
  sessionId: string | null;
  selectedFilename: string | null;
  onSelect: (filename: string) => void;
  onBack: () => void;
  onContinue: () => void;
  saving: boolean;
}

export default function TemplatePickerStep({
  sessionId,
  selectedFilename,
  onSelect,
  onBack,
  onContinue,
  saving,
}: TemplatePickerStepProps) {
  const [templates, setTemplates] = useState<TemplateOption[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchTemplates().then((list) => {
      setTemplates(list);
      setLoading(false);
    });
  }, []);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <LayoutTemplate className="h-4 w-4 text-orange-400" />
          <h2 className="text-sm font-semibold text-white">Choose a slide template</h2>
        </div>
        <p className="text-xs text-zinc-500">
          Pick the visual style for your deck. Colors, fonts and layout come from
          the template — your content fills it in.
        </p>
      </div>

      {/* Template cards */}
      {loading ? (
        <div className="flex items-center justify-center py-8 gap-2 text-zinc-500 text-xs">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading templates…
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-3">
          {templates.map((t) => {
            const isSelected = selectedFilename === t.filename;
            const accent = TEMPLATE_ACCENTS[t.id] ?? { accent: "#a1a1aa" };
            return (
              <button
                key={t.id}
                onClick={() => onSelect(t.filename)}
                className={`relative flex flex-col items-center rounded-2xl border p-3 text-center transition-all hover:scale-[1.02] ${
                  isSelected
                    ? "border-orange-500/60 bg-orange-500/10 ring-1 ring-orange-500/30"
                    : "border-white/8 bg-white/3 hover:border-white/15 hover:bg-white/6"
                }`}
              >
                {/* Selected check */}
                {isSelected && (
                  <div className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-orange-500">
                    <Check className="h-3 w-3 text-white" />
                  </div>
                )}

                <TemplateMiniPreview id={t.id} />

                <p className="text-xs font-semibold text-white">{t.name}</p>
                <p
                  className="mt-0.5 text-[10px] font-medium"
                  style={{ color: accent.accent }}
                >
                  {TEMPLATE_ACCENTS[t.id]?.label ?? "Custom"} accent
                </p>
              </button>
            );
          })}
        </div>
      )}

      {/* Nav buttons */}
      <div className="flex gap-3">
        <button
          onClick={onBack}
          className="rounded-xl border border-white/8 bg-white/4 px-4 py-3 text-sm font-medium text-zinc-400 transition-all hover:bg-white/8"
        >
          Back
        </button>
        <button
          disabled={!selectedFilename || saving}
          onClick={onContinue}
          className="flex flex-1 items-center justify-center gap-2 rounded-xl brand-gradient px-5 py-3 text-sm font-semibold text-white brand-glow-shadow transition-all hover:scale-[1.01] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:scale-100 active:scale-[0.98]"
        >
          {saving ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Saving…
            </>
          ) : (
            <>
              Continue
              <ChevronRight className="h-4 w-4" />
            </>
          )}
        </button>
      </div>
    </div>
  );
}
