"use client";

import { useEffect, useState } from "react";
import { getPreviewURL } from "@/lib/api";
import { Eye, FileWarning, Loader2 } from "lucide-react";

interface PreviewPaneProps {
  filename: string;
  previewAvailable: boolean;
}

type Status = "loading" | "ready" | "error" | "unavailable";

export default function PreviewPane({
  filename,
  previewAvailable,
}: PreviewPaneProps) {
  const [status, setStatus] = useState<Status>(
    previewAvailable ? "loading" : "unavailable"
  );
  const [errorMsg, setErrorMsg] = useState<string>("");

  const previewURL = getPreviewURL(filename);

  // Pre-flight check: HEAD the preview URL so we can show a friendly error
  // instead of a blank iframe if LibreOffice barfs on this specific file.
  useEffect(() => {
    if (!previewAvailable) {
      setStatus("unavailable");
      return;
    }

    let cancelled = false;
    setStatus("loading");

    fetch(previewURL, { method: "GET", cache: "no-store" })
      .then(async (res) => {
        if (cancelled) return;
        if (res.ok) {
          setStatus("ready");
        } else {
          const text = await res.text().catch(() => "");
          setStatus("error");
          setErrorMsg(text.slice(0, 200) || `HTTP ${res.status}`);
        }
      })
      .catch((e) => {
        if (cancelled) return;
        setStatus("error");
        setErrorMsg(String(e));
      });

    return () => {
      cancelled = true;
    };
  }, [previewURL, previewAvailable]);

  return (
    <div className="overflow-hidden rounded-2xl border border-white/8 bg-black/40">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/5 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Eye className="h-3.5 w-3.5 text-violet-400" />
          <span className="text-xs font-medium text-zinc-300">
            Slide preview
          </span>
        </div>
        <span className="text-[10px] uppercase tracking-wider text-zinc-600">
          {status === "ready"
            ? "Live"
            : status === "loading"
            ? "Rendering…"
            : status === "unavailable"
            ? "Disabled"
            : "Failed"}
        </span>
      </div>

      {/* Body */}
      <div className="relative h-[640px] w-full bg-black">
        {status === "loading" && (
          <div className="flex h-full w-full flex-col items-center justify-center gap-3 text-zinc-500">
            <Loader2 className="h-6 w-6 animate-spin text-violet-400" />
            <p className="text-xs">Converting PPTX to preview (5-10s)…</p>
          </div>
        )}

        {status === "ready" && (
          <iframe
            src={previewURL}
            title="Slide preview"
            className="h-full w-full"
            style={{ border: "none" }}
          />
        )}

        {status === "unavailable" && (
          <div className="flex h-full w-full flex-col items-center justify-center gap-3 px-6 text-center text-zinc-400">
            <FileWarning className="h-6 w-6 text-amber-400" />
            <p className="text-sm font-medium text-zinc-300">
              Preview not available on this server
            </p>
            <p className="max-w-md text-xs text-zinc-500">
              Install LibreOffice on the backend to enable in-browser preview:
              <br />
              <code className="mt-1 inline-block rounded bg-white/5 px-2 py-0.5 font-mono text-[11px] text-zinc-400">
                brew install --cask libreoffice
              </code>
            </p>
          </div>
        )}

        {status === "error" && (
          <div className="flex h-full w-full flex-col items-center justify-center gap-3 px-6 text-center text-zinc-400">
            <FileWarning className="h-6 w-6 text-red-400" />
            <p className="text-sm font-medium text-zinc-300">
              Couldn&apos;t render preview
            </p>
            <p className="max-w-md text-xs text-zinc-500">{errorMsg}</p>
          </div>
        )}
      </div>
    </div>
  );
}
