"use client";

import { useCallback, useState } from "react";
import { CheckCircle2, AlertTriangle, Info, X } from "lucide-react";

export type ToastType = "success" | "error" | "info";

export interface ToastItem {
  id: number;
  message: string;
  type: ToastType;
}

let _id = 0;

/**
 * Lightweight toast manager (no external deps). Returns a `notify` callback to
 * raise toasts and the `<Toaster/>` element to render them.
 */
export function useToasts() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  const notify = useCallback(
    (message: string, type: ToastType = "info") => {
      const id = ++_id;
      setToasts((t) => [...t, { id, message, type }]);
      window.setTimeout(() => dismiss(id), type === "error" ? 5000 : 3000);
    },
    [dismiss]
  );

  return { toasts, notify, dismiss };
}

const TONE: Record<ToastType, { ring: string; icon: React.ReactNode }> = {
  success: {
    ring: "ring-emerald-500/30 bg-emerald-500/10",
    icon: <CheckCircle2 className="h-4 w-4 text-emerald-400" />,
  },
  error: {
    ring: "ring-red-500/30 bg-red-500/10",
    icon: <AlertTriangle className="h-4 w-4 text-red-400" />,
  },
  info: {
    ring: "ring-indigo-500/30 bg-indigo-500/10",
    icon: <Info className="h-4 w-4 text-indigo-300" />,
  },
};

export function Toaster({
  toasts,
  dismiss,
}: {
  toasts: ToastItem[];
  dismiss: (id: number) => void;
}) {
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(92vw,360px)] flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`animate-fade-up pointer-events-auto flex items-start gap-2.5 rounded-xl border border-white/10 px-3.5 py-3 text-sm text-zinc-100 shadow-xl shadow-black/40 ring-1 backdrop-blur ${TONE[t.type].ring}`}
        >
          <span className="mt-0.5 shrink-0">{TONE[t.type].icon}</span>
          <p className="flex-1 leading-snug">{t.message}</p>
          <button
            onClick={() => dismiss(t.id)}
            className="mt-0.5 shrink-0 text-zinc-500 transition hover:text-zinc-200"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
