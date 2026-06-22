"use client";

export type SlideInsertMode = "end" | "start" | "between";

/** Map UI choice → backend after_slide_number. */
export function resolveAfterSlideNumber(
  mode: SlideInsertMode,
  betweenAfter: number,
  lastSlideNum: number
): number {
  if (mode === "end") return lastSlideNum;
  if (mode === "start") return 0;
  return Math.max(0, Math.min(betweenAfter, lastSlideNum));
}

export function insertPositionLabel(
  mode: SlideInsertMode,
  betweenAfter: number
): string {
  if (mode === "end") return "at the end";
  if (mode === "start") return "at the start";
  return `between slides ${betweenAfter} and ${betweenAfter + 1}`;
}

interface SlideInsertControlsProps {
  slideCount: number;
  lastSlideNum: number;
  mode: SlideInsertMode;
  betweenAfter: number;
  onModeChange: (mode: SlideInsertMode) => void;
  onBetweenAfterChange: (n: number) => void;
  className?: string;
}

export default function SlideInsertControls({
  slideCount,
  lastSlideNum,
  mode,
  betweenAfter,
  onModeChange,
  onBetweenAfterChange,
  className = "",
}: SlideInsertControlsProps) {
  const maxBetween = Math.max(1, lastSlideNum);

  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      <span className="text-xs text-zinc-500">at</span>
      <select
        value={mode}
        onChange={(e) => onModeChange(e.target.value as SlideInsertMode)}
        title="Where the new slide goes in the deck"
        className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-xs text-white outline-none"
      >
        <option value="end">End of deck</option>
        <option value="start">Start of deck</option>
        <option value="between">Between slides…</option>
      </select>
      {mode === "between" && slideCount > 0 && (
        <>
          <input
            type="number"
            min={1}
            max={maxBetween}
            value={betweenAfter}
            onChange={(e) => {
              const n = Number(e.target.value);
              if (!Number.isFinite(n)) return;
              onBetweenAfterChange(Math.max(1, Math.min(maxBetween, Math.round(n))));
            }}
            title="Insert after this slide number"
            className="w-14 rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1.5 text-center text-xs text-white outline-none"
          />
          <span className="text-[11px] text-zinc-500">
            → between {betweenAfter} &amp; {betweenAfter + 1}
          </span>
        </>
      )}
    </div>
  );
}
