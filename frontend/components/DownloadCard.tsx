"use client";

import { GenerateResponse } from "@/types";
import { getDownloadURL, getPdfDownloadURL } from "@/lib/api";
import {
  Download,
  FileSliders,
  RotateCcw,
  Sparkles,
  BarChart3,
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

  return (
    <div className="space-y-6 text-center">
      {/* Success Icon */}
      <div className="flex flex-col items-center gap-3">
        <div className="relative inline-flex">
          <div className="flex h-20 w-20 items-center justify-center rounded-3xl bg-gradient-to-br from-violet-600/30 to-emerald-500/20 ring-1 ring-white/10">
            <Sparkles className="h-9 w-9 text-white" />
          </div>
          <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500 text-[10px] font-bold text-white shadow-lg">
            ✓
          </span>
        </div>
        <div>
          <h2 className="text-xl font-semibold text-white">
            Your slides are ready!
          </h2>
          <p className="mt-1 text-sm text-zinc-500">
            PowerPoint presentation generated successfully
          </p>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-2xl border border-white/6 bg-white/[0.03] p-4">
          <p className="text-2xl font-bold text-white">
            {result.total_pages ?? "—"}
          </p>
          <p className="mt-0.5 text-xs text-zinc-500">PDF Pages Read</p>
        </div>
        <div className="rounded-2xl border border-violet-500/20 bg-violet-500/5 p-4">
          <p className="text-2xl font-bold text-violet-300">
            {result.total_slides ?? "—"}
          </p>
          <p className="mt-0.5 text-xs text-zinc-500">Slides Created</p>
        </div>
      </div>

      {/* Filename */}
      {result.filename && (
        <div className="flex items-center gap-3 rounded-xl border border-white/6 bg-white/[0.03] px-4 py-3 text-left">
          <FileSliders className="h-4 w-4 flex-shrink-0 text-zinc-500" />
          <span className="truncate text-xs text-zinc-400">
            {result.filename}
          </span>
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-col gap-3">
        {downloadURL && (
          <a
            href={downloadURL}
            download={result.filename}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-violet-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition-all hover:bg-violet-500 active:scale-[0.98]"
          >
            <Download className="h-4 w-4" />
            Download .pptx
          </a>
        )}
        {pdfDownloadURL && (
          <a
            href={pdfDownloadURL}
            download={result.filename?.replace(/\.pptx$/i, ".pdf")}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-violet-500/30 bg-violet-500/10 px-5 py-3 text-sm font-semibold text-violet-100 transition-all hover:bg-violet-500/15 active:scale-[0.98]"
          >
            <Download className="h-4 w-4" />
            Download .pdf
          </a>
        )}
        {onShowAnalytics && result.analytics && (
          <button
            onClick={onShowAnalytics}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-5 py-3 text-sm font-semibold text-emerald-100 transition-all hover:bg-emerald-500/15 active:scale-[0.98]"
          >
            <BarChart3 className="h-4 w-4" />
            Show Analytics
          </button>
        )}
        <button
          onClick={onReset}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-white/8 bg-white/[0.04] px-5 py-3 text-sm font-medium text-zinc-300 transition-all hover:bg-white/[0.08] active:scale-[0.98]"
        >
          <RotateCcw className="h-4 w-4" />
          Convert another PDF
        </button>
      </div>
    </div>
  );
}
