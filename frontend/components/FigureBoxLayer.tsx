"use client";

import { useRef, useState } from "react";
import { FigureView } from "@/types";

interface ImgRect {
  ox: number;
  oy: number;
  w: number;
  h: number;
}
interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface Props {
  imgRect: ImgRect;
  figures: FigureView[];
  addMode: boolean;
  highlightId: string | null;
  onHighlight: (id: string | null) => void;
  onSelect?: (id: string) => void;
  onUpdateBbox: (id: string, box: Box) => void;
  onAddFigure: (box: Box) => void;
  onExitAddMode: () => void;
}

const clamp = (v: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(hi, v));

type DragKind = "move" | "resize" | "draw";

export default function FigureBoxLayer({
  imgRect,
  figures,
  addMode,
  highlightId,
  onHighlight,
  onSelect,
  onUpdateBbox,
  onAddFigure,
  onExitAddMode,
}: Props) {
  const layerRef = useRef<HTMLDivElement | null>(null);
  const drag = useRef<{
    kind: DragKind;
    id: string | null;
    start: { x: number; y: number };
    orig: Box;
    cur: Box;
  } | null>(null);
  const [live, setLive] = useState<{ id: string | null; box: Box } | null>(null);

  const toPct = (clientX: number, clientY: number) => {
    const rect = layerRef.current!.getBoundingClientRect();
    const px = clientX - rect.left - imgRect.ox;
    const py = clientY - rect.top - imgRect.oy;
    return {
      x: clamp((px / imgRect.w) * 100, 0, 100),
      y: clamp((py / imgRect.h) * 100, 0, 100),
    };
  };

  const onPointerDown = (e: React.PointerEvent) => {
    const target = e.target as HTMLElement;
    const handleId = target.dataset.handle;
    const boxId = target.dataset.box;
    const p = toPct(e.clientX, e.clientY);

    let kind: DragKind;
    let id: string | null = null;
    let orig: Box;

    if (handleId) {
      const f = figures.find((x) => x.id === handleId);
      if (!f?.bbox) return;
      kind = "resize";
      id = handleId;
      orig = { ...f.bbox };
    } else if (boxId) {
      const f = figures.find((x) => x.id === boxId);
      if (!f?.bbox) return;
      kind = "move";
      id = boxId;
      orig = { ...f.bbox };
    } else if (addMode) {
      kind = "draw";
      orig = { x: p.x, y: p.y, w: 0, h: 0 };
    } else {
      return;
    }

    drag.current = { kind, id, start: p, orig, cur: orig };
    setLive({ id, box: orig });
    layerRef.current?.setPointerCapture(e.pointerId);
    e.preventDefault();
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const p = toPct(e.clientX, e.clientY);
    let box: Box;
    if (d.kind === "move") {
      box = {
        ...d.orig,
        x: clamp(d.orig.x + (p.x - d.start.x), 0, 100 - d.orig.w),
        y: clamp(d.orig.y + (p.y - d.start.y), 0, 100 - d.orig.h),
      };
    } else if (d.kind === "resize") {
      box = {
        x: d.orig.x,
        y: d.orig.y,
        w: clamp(p.x - d.orig.x, 1, 100 - d.orig.x),
        h: clamp(p.y - d.orig.y, 1, 100 - d.orig.y),
      };
    } else {
      box = {
        x: Math.min(p.x, d.start.x),
        y: Math.min(p.y, d.start.y),
        w: Math.abs(p.x - d.start.x),
        h: Math.abs(p.y - d.start.y),
      };
    }
    d.cur = box;
    setLive({ id: d.id, box });
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const d = drag.current;
    layerRef.current?.releasePointerCapture(e.pointerId);
    drag.current = null;
    if (d) {
      const box = d.cur;
      if (d.kind === "draw") {
        if (box.w >= 2 && box.h >= 2) onAddFigure(box);
        onExitAddMode();
      } else if (d.id) {
        // Only persist if it actually moved/resized.
        const moved =
          Math.abs(box.x - d.orig.x) > 0.2 ||
          Math.abs(box.y - d.orig.y) > 0.2 ||
          Math.abs(box.w - d.orig.w) > 0.2 ||
          Math.abs(box.h - d.orig.h) > 0.2;
        if (moved) onUpdateBbox(d.id, box);
        // A click without a drag = "take me to this figure's card".
        else if (d.kind === "move") onSelect?.(d.id);
      }
    }
    setLive(null);
  };

  const px = (b: Box) => ({
    left: imgRect.ox + (b.x / 100) * imgRect.w,
    top: imgRect.oy + (b.y / 100) * imgRect.h,
    width: (b.w / 100) * imgRect.w,
    height: (b.h / 100) * imgRect.h,
  });

  const drawDraft =
    live && live.id === null ? live.box : null;

  return (
    <div
      ref={layerRef}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      className="absolute inset-0 z-10"
      style={{ cursor: addMode ? "crosshair" : "default", touchAction: "none" }}
    >
      {figures.map((f) => {
        if (!f.bbox) return null;
        const box = live && live.id === f.id ? live.box : f.bbox;
        const isHi = highlightId === f.id;
        const excluded = !f.included;
        const style = px(box);
        return (
          <div
            key={f.id}
            data-box={f.id}
            onMouseEnter={() => onHighlight(f.id)}
            onMouseLeave={() => onHighlight(null)}
            className={`absolute rounded-md border-2 transition-all ${
              excluded
                ? "cursor-move border-dashed border-zinc-500/60 bg-transparent opacity-60"
                : isHi
                ? "cursor-pointer border-fuchsia-400 bg-fuchsia-400/25 shadow-[0_0_16px_3px_rgba(232,121,249,0.7)]"
                : "cursor-pointer border-amber-400/80 bg-amber-400/10"
            }`}
            style={style}
          >
            <span
              data-box={f.id}
              className={`pointer-events-none absolute -top-3 left-0 whitespace-nowrap rounded px-1 text-[9px] font-bold ${
                excluded
                  ? "bg-zinc-600 text-zinc-200 line-through"
                  : isHi
                  ? "bg-fuchsia-400 text-black shadow-[0_0_8px_1px_rgba(232,121,249,0.8)]"
                  : "bg-amber-500/90 text-black"
              }`}
            >
              {f.label || "Diagram"}
            </span>
            {/* Resize handle (bottom-right) */}
            {!excluded && (
              <span
                data-handle={f.id}
                className="absolute -bottom-1.5 -right-1.5 h-3.5 w-3.5 cursor-nwse-resize rounded-sm border border-white/70 bg-amber-400"
              />
            )}
          </div>
        );
      })}

      {/* New box being drawn */}
      {drawDraft && (
        <div
          className="absolute rounded-md border-2 border-dashed border-emerald-300 bg-emerald-300/15"
          style={px(drawDraft)}
        />
      )}
    </div>
  );
}
