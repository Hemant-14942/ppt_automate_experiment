"use client";

import { GenerateResponse } from "@/types";
import { getDownloadURL, getPdfDownloadURL } from "@/lib/api";
import {
  Download,
  RotateCcw,
  Sparkles,
  BarChart3,
  FileText,
  Check,
} from "lucide-react";

interface DownloadCardProps {
  result: GenerateResponse;
  previewAvailable: boolean;
  onReset: () => void;
  onShowAnalytics?: () => void;
}

export default function DownloadCard({
  result,
  previewAvailable,
  onReset,
  onShowAnalytics,
}: DownloadCardProps) {
  const downloadURL =
    result.download_url ??
    (result.filename ? getDownloadURL(result.filename) : null);
  const pdfDownloadURL =
    previewAvailable && result.filename
      ? getPdfDownloadURL(result.filename)
      : null;

  const slides = result.total_slides ?? 0;
  // Rough read-time estimate: ~30s of speaking per slide.
  const readMin = slides > 0 ? Math.max(1, Math.round((slides * 0.5))) : null;
  const genSec = result.analytics?.elapsed_seconds
    ? Math.round(result.analytics.elapsed_seconds)
    : null;

  const stats = [
    { value: result.total_pages ?? "—", label: "Pages read", tint: "text-white" },
    { value: slides || "—", label: "Slides created", tint: "text-violet-300" },
    { value: readMin ? `~${readMin}m` : "—", label: "Read time", tint: "text-white" },
    {
      value: genSec ? `${genSec}s` : "—",
      label: "Built in",
      tint: "text-white",
    },
  ];

  return (
    <div className="space-y-6 text-center">
      {/* Celebration */}
      <div className="flex flex-col items-center gap-3 pt-2">
        <div className="relative inline-flex animate-pop">
          <div className="flex h-20 w-20 items-center justify-center rounded-3xl brand-gradient brand-glow-shadow animate-pulse-ring">
            <Sparkles className="h-9 w-9 text-white" />
          </div>
          <span className="absolute -right-1 -top-1 flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500 text-white shadow-lg ring-2 ring-[#0d0e18]">
            <Check className="h-3.5 w-3.5" />
          </span>
        </div>
        <div>
          <h2 className="text-xl font-bold tracking-tight text-white">
            Your deck is ready
          </h2>
          <p className="mt-1 text-sm text-zinc-500">
            Reviewed, written and styled — exactly how you planned it.
          </p>
        </div>
      </div>

      {/* Stat grid */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {stats.map((s) => (
          <div
            key={s.label}
            className="rounded-2xl border border-white/6 bg-white/[0.03] p-3.5"
          >
            <p className={`text-xl font-bold ${s.tint}`}>{s.value}</p>
            <p className="mt-0.5 text-[11px] text-zinc-500">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Filename */}
      {result.filename && (
        <div className="flex items-center gap-3 rounded-xl border border-white/6 bg-white/[0.03] px-4 py-3 text-left">
          <FileText className="h-4 w-4 flex-shrink-0 text-zinc-500" />
          <span className="truncate text-xs text-zinc-400">{result.filename}</span>
        </div>
      )}

      {/* Primary action — the one CTA that gets the brand gradient + glow */}
      <div className="space-y-3">
        {downloadURL && (
          <a
            href={downloadURL}
            download={result.filename}
            className="flex w-full items-center justify-center gap-2 rounded-xl brand-gradient px-5 py-3.5 text-sm font-semibold text-white brand-glow-shadow transition-all hover:scale-[1.01] hover:brightness-110 active:scale-[0.98]"
          >
            <Download className="h-4 w-4" />
            Download PowerPoint (.pptx)
          </a>
        )}

        <div className="flex flex-col gap-2 sm:flex-row">
          {pdfDownloadURL && (
            <a
              href={pdfDownloadURL}
              download={result.filename?.replace(/\.pptx$/i, ".pdf")}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm font-medium text-zinc-300 transition-all hover:bg-white/[0.07] active:scale-[0.98]"
            >
              <Download className="h-4 w-4" />
              .pdf
            </a>
          )}
          {onShowAnalytics && result.analytics && (
            <button
              onClick={onShowAnalytics}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm font-medium text-zinc-300 transition-all hover:bg-white/[0.07] active:scale-[0.98]"
            >
              <BarChart3 className="h-4 w-4" />
              Analytics
            </button>
          )}
        </div>

        <button
          onClick={onReset}
          className="flex w-full items-center justify-center gap-2 py-2 text-xs font-medium text-zinc-500 transition-colors hover:text-zinc-300"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Convert another PDF
        </button>
      </div>
    </div>
  );
}
