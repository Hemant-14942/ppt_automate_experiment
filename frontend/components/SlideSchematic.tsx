"use client";

import { getSlideType, SchematicShape } from "@/lib/slideTypes";

/**
 * A lightweight, schematic ("sketch") preview of a single slide.
 *
 * It draws the SHAPE of a slide layout (heading, bullets, options, table…)
 * using CSS — not a pixel-perfect render of the final PowerPoint. The whole
 * thing scales with its container via CSS container-query units (cqw), so the
 * same component works as a tiny filmstrip thumbnail and as a large stage
 * preview without any size props.
 *
 * Pass `points` to fill it with real content (per-slide preview); leave it
 * empty for a placeholder layout (the type gallery).
 */
export interface SlideSchematicProps {
  type: string;
  title?: string;
  points?: string[];
  /** Theme accent colour (hex). Defaults to the brand orange. */
  accent?: string;
  /** Slide background colour (hex). */
  bg?: string;
  /** Show real text. When false, draws neutral placeholder bars. */
  filled?: boolean;
  className?: string;
}

const DEFAULT_ACCENT = "#f97316";
const DEFAULT_BG = "#16100c";

export default function SlideSchematic({
  type,
  title,
  points = [],
  accent = DEFAULT_ACCENT,
  bg = DEFAULT_BG,
  filled = false,
  className = "",
}: SlideSchematicProps) {
  const def = getSlideType(type);
  return (
    <div
      className={`relative aspect-[16/9] w-full select-none overflow-hidden rounded-lg ring-1 ring-white/10 ${className}`}
      style={{ background: bg, containerType: "size" }}
    >
      {/* faint accent wash from the top-left, echoing the app's light beam */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background: `radial-gradient(120% 90% at 0% 0%, ${accent}22, transparent 55%)`,
        }}
      />
      <div
        className="absolute inset-0 flex flex-col"
        style={{ padding: "6cqw", gap: "3cqh" }}
      >
        <Body
          shape={def.shape}
          pyq={Boolean(def.pyq)}
          title={title}
          points={points}
          accent={accent}
          filled={filled}
        />
      </div>
    </div>
  );
}

function Body({
  shape,
  pyq,
  title,
  points,
  accent,
  filled,
}: {
  shape: SchematicShape;
  pyq: boolean;
  title?: string;
  points: string[];
  accent: string;
  filled: boolean;
}) {
  switch (shape) {
    case "title":
      return <CenteredLayout title={title} points={points} accent={accent} filled={filled} kind="title" />;
    case "section":
      return <CenteredLayout title={title} points={points} accent={accent} filled={filled} kind="section" />;
    case "closing":
      return <CenteredLayout title={title} points={points} accent={accent} filled={filled} kind="closing" />;
    case "numbered":
      return <ListLayout title={title} points={points} accent={accent} filled={filled} numbered />;
    case "bullets":
      return <ListLayout title={title} points={points} accent={accent} filled={filled} />;
    case "table":
      return <TableLayout title={title} accent={accent} filled={filled} />;
    case "bullets_table":
      return <BulletsTableLayout title={title} points={points} accent={accent} filled={filled} />;
    case "passage":
      return <PassageLayout title={title} points={points} accent={accent} filled={filled} />;
    case "mcq":
      return <McqLayout title={title} points={points} accent={accent} filled={filled} pyq={pyq} grid={false} />;
    case "mcq_grid":
      return <McqLayout title={title} points={points} accent={accent} filled={filled} pyq={pyq} grid />;
    case "question":
      return <QuestionLayout title={title} points={points} accent={accent} filled={filled} pyq={pyq} />;
    case "figure":
      return <FigureLayout title={title} accent={accent} filled={filled} />;
    default:
      return <ListLayout title={title} points={points} accent={accent} filled={filled} />;
  }
}

// ── Building blocks ──────────────────────────────────────────────────────────

function HeadingTag({
  title,
  accent,
  filled,
  pyq,
}: {
  title?: string;
  accent: string;
  filled: boolean;
  pyq?: boolean;
}) {
  return (
    <div className="flex items-center" style={{ gap: "2cqw" }}>
      {pyq && (
        <span
          className="inline-flex items-center rounded font-semibold uppercase text-black/80"
          style={{ background: accent, padding: "0.6cqw 1.6cqw", fontSize: "2.6cqw" }}
        >
          PYQ
        </span>
      )}
      <span
        className="inline-flex max-w-full items-center rounded"
        style={{ background: accent, padding: "1cqw 2.4cqw", maxWidth: "82%" }}
      >
        {filled && title ? (
          <span
            className="truncate font-semibold text-black/85"
            style={{ fontSize: "3.6cqw", lineHeight: 1.1 }}
          >
            {title}
          </span>
        ) : (
          <span
            className="block rounded-sm bg-black/30"
            style={{ width: "26cqw", height: "2.6cqw" }}
          />
        )}
      </span>
    </div>
  );
}

function Bar({ w, accent, dim }: { w: string; accent?: string; dim?: boolean }) {
  return (
    <span
      className="block rounded-sm"
      style={{
        width: w,
        height: "2.4cqh",
        background: accent ?? (dim ? "rgba(255,255,255,0.12)" : "rgba(255,255,255,0.2)"),
      }}
    />
  );
}

function ListLayout({
  title,
  points,
  accent,
  filled,
  numbered,
}: {
  title?: string;
  points: string[];
  accent: string;
  filled: boolean;
  numbered?: boolean;
}) {
  const rows = filled && points.length ? points.slice(0, 5) : [0, 1, 2, 3];
  return (
    <>
      <HeadingTag title={title} accent={accent} filled={filled} />
      <div className="flex flex-1 flex-col justify-center" style={{ gap: "3.4cqh" }}>
        {rows.map((row, i) => (
          <div key={i} className="flex items-center" style={{ gap: "2cqw" }}>
            {numbered ? (
              <span
                className="flex shrink-0 items-center justify-center rounded-full font-bold text-black/80"
                style={{ background: accent, width: "4.4cqw", height: "4.4cqw", fontSize: "2.6cqw" }}
              >
                {i + 1}
              </span>
            ) : (
              <span
                className="shrink-0"
                style={{
                  width: 0,
                  height: 0,
                  borderTop: "1.4cqw solid transparent",
                  borderBottom: "1.4cqw solid transparent",
                  borderLeft: `2.2cqw solid ${accent}`,
                }}
              />
            )}
            {typeof row === "string" ? (
              <span
                className="line-clamp-1 text-white/85"
                style={{ fontSize: "3.4cqw", lineHeight: 1.15 }}
              >
                {row}
              </span>
            ) : (
              <Bar w={`${72 - i * 8}cqw`} />
            )}
          </div>
        ))}
      </div>
    </>
  );
}

function McqLayout({
  title,
  points,
  accent,
  filled,
  pyq,
  grid,
}: {
  title?: string;
  points: string[];
  accent: string;
  filled: boolean;
  pyq: boolean;
  grid: boolean;
}) {
  // points[0] = question (fallback to title), points[1..4] = options
  const question = filled ? points[0] ?? title : undefined;
  const options = filled ? points.slice(1, 5) : [];
  const letters = ["A", "B", "C", "D"];
  return (
    <>
      <HeadingTag title={pyq ? title ?? "Question" : "Question"} accent={accent} filled pyq={pyq} />
      <div className="flex" style={{ marginTop: "1cqh" }}>
        {question ? (
          <span className="line-clamp-2 text-white/90" style={{ fontSize: "3.4cqw", lineHeight: 1.2 }}>
            {question}
          </span>
        ) : (
          <div className="flex w-full flex-col" style={{ gap: "1.6cqh" }}>
            <Bar w="90cqw" />
            <Bar w="64cqw" dim />
          </div>
        )}
      </div>
      <div
        className={grid ? "grid flex-1 grid-cols-2 content-center" : "flex flex-1 flex-col justify-center"}
        style={{ gap: grid ? "2.4cqw" : "2.4cqh", marginTop: "1cqh" }}
      >
        {letters.map((L, i) => (
          <div
            key={L}
            className="flex items-center rounded"
            style={{
              gap: "1.8cqw",
              padding: "1.2cqw 1.8cqw",
              background: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.08)",
            }}
          >
            <span
              className="flex shrink-0 items-center justify-center rounded-full font-bold"
              style={{
                width: "4.2cqw",
                height: "4.2cqw",
                fontSize: "2.4cqw",
                color: accent,
                border: `0.5cqw solid ${accent}`,
              }}
            >
              {L}
            </span>
            {options[i] ? (
              <span className="line-clamp-1 text-white/80" style={{ fontSize: "3cqw" }}>
                {options[i]}
              </span>
            ) : (
              <Bar w={grid ? "26cqw" : `${60 - i * 6}cqw`} dim />
            )}
          </div>
        ))}
      </div>
    </>
  );
}

function QuestionLayout({
  title,
  points,
  accent,
  filled,
  pyq,
}: {
  title?: string;
  points: string[];
  accent: string;
  filled: boolean;
  pyq: boolean;
}) {
  const q = filled ? points[0] ?? title : undefined;
  return (
    <>
      <HeadingTag title="Question" accent={accent} filled pyq={pyq} />
      <div className="flex flex-1 flex-col justify-center" style={{ gap: "2cqh" }}>
        {q ? (
          <span className="line-clamp-4 text-white/90" style={{ fontSize: "4cqw", lineHeight: 1.3 }}>
            {q}
          </span>
        ) : (
          <>
            <Bar w="92cqw" />
            <Bar w="86cqw" />
            <Bar w="70cqw" dim />
          </>
        )}
      </div>
    </>
  );
}

function TableLayout({ title, accent, filled }: { title?: string; accent: string; filled: boolean }) {
  return (
    <>
      <HeadingTag title={title} accent={accent} filled={filled} />
      <div
        className="flex flex-1 flex-col overflow-hidden rounded"
        style={{ border: "1px solid rgba(255,255,255,0.14)", marginTop: "1cqh" }}
      >
        {/* header row */}
        <div className="flex" style={{ background: accent }}>
          {[0, 1, 2].map((c) => (
            <div
              key={c}
              className="flex-1"
              style={{
                padding: "1.6cqw",
                borderRight: c < 2 ? "1px solid rgba(0,0,0,0.25)" : undefined,
              }}
            >
              <span className="block rounded-sm bg-black/30" style={{ height: "2.2cqh", width: "70%" }} />
            </div>
          ))}
        </div>
        {/* body rows */}
        {[0, 1, 2].map((r) => (
          <div
            key={r}
            className="flex flex-1"
            style={{ borderTop: "1px solid rgba(255,255,255,0.1)" }}
          >
            {[0, 1, 2].map((c) => (
              <div
                key={c}
                className="flex flex-1 items-center"
                style={{
                  padding: "1.4cqw",
                  borderRight: c < 2 ? "1px solid rgba(255,255,255,0.1)" : undefined,
                }}
              >
                <Bar w={`${60 - c * 6}%`} dim />
              </div>
            ))}
          </div>
        ))}
      </div>
    </>
  );
}

function BulletsTableLayout({
  title,
  points,
  accent,
  filled,
}: {
  title?: string;
  points: string[];
  accent: string;
  filled: boolean;
}) {
  const rows = filled && points.length ? points.slice(0, 2) : [0, 1];
  return (
    <>
      <HeadingTag title={title} accent={accent} filled={filled} />
      <div className="flex flex-col" style={{ gap: "2cqh", marginTop: "0.5cqh" }}>
        {rows.map((row, i) => (
          <div key={i} className="flex items-center" style={{ gap: "2cqw" }}>
            <span
              className="shrink-0"
              style={{
                width: 0,
                height: 0,
                borderTop: "1.2cqw solid transparent",
                borderBottom: "1.2cqw solid transparent",
                borderLeft: `2cqw solid ${accent}`,
              }}
            />
            {typeof row === "string" ? (
              <span className="line-clamp-1 text-white/85" style={{ fontSize: "3.2cqw" }}>
                {row}
              </span>
            ) : (
              <Bar w={`${78 - i * 10}cqw`} />
            )}
          </div>
        ))}
      </div>
      <div
        className="flex flex-1 flex-col overflow-hidden rounded"
        style={{ border: "1px solid rgba(255,255,255,0.14)" }}
      >
        <div className="flex" style={{ background: accent }}>
          {[0, 1, 2].map((c) => (
            <div key={c} className="flex-1" style={{ padding: "1.2cqw", borderRight: c < 2 ? "1px solid rgba(0,0,0,0.25)" : undefined }}>
              <span className="block rounded-sm bg-black/30" style={{ height: "1.8cqh", width: "70%" }} />
            </div>
          ))}
        </div>
        {[0, 1].map((r) => (
          <div key={r} className="flex flex-1" style={{ borderTop: "1px solid rgba(255,255,255,0.1)" }}>
            {[0, 1, 2].map((c) => (
              <div key={c} className="flex flex-1 items-center" style={{ padding: "1.2cqw", borderRight: c < 2 ? "1px solid rgba(255,255,255,0.1)" : undefined }}>
                <Bar w={`${60 - c * 6}%`} dim />
              </div>
            ))}
          </div>
        ))}
      </div>
    </>
  );
}

function PassageLayout({
  title,
  points,
  accent,
  filled,
}: {
  title?: string;
  points: string[];
  accent: string;
  filled: boolean;
}) {
  const text = filled ? points.join(" ") : "";
  return (
    <>
      <div
        className="flex items-center rounded"
        style={{ background: `${accent}22`, borderLeft: `1.4cqw solid ${accent}`, padding: "1.4cqw 2cqw" }}
      >
        {filled && title ? (
          <span className="line-clamp-1 font-medium text-white/85" style={{ fontSize: "3cqw" }}>
            {title}
          </span>
        ) : (
          <Bar w="40cqw" />
        )}
      </div>
      <div className="flex flex-1 flex-col justify-center" style={{ gap: "2cqh" }}>
        {text ? (
          <span className="line-clamp-5 text-white/80" style={{ fontSize: "3cqw", lineHeight: 1.4 }}>
            {text}
          </span>
        ) : (
          [92, 96, 88, 94, 60].map((w, i) => <Bar key={i} w={`${w}cqw`} dim={i % 2 === 1} />)
        )}
      </div>
    </>
  );
}

function FigureLayout({ title, accent, filled }: { title?: string; accent: string; filled: boolean }) {
  return (
    <>
      <HeadingTag title={title} accent={accent} filled={filled} />
      <div
        className="flex flex-1 items-center justify-center rounded"
        style={{ border: `0.6cqw dashed ${accent}`, background: "rgba(255,255,255,0.03)", marginTop: "1cqh" }}
      >
        <svg viewBox="0 0 24 24" width="16%" height="16%" fill="none" stroke={accent} strokeWidth="1.6">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <circle cx="8.5" cy="8.5" r="1.8" />
          <path d="m21 15-5-5L5 21" />
        </svg>
      </div>
    </>
  );
}

function CenteredLayout({
  title,
  points,
  accent,
  filled,
  kind,
}: {
  title?: string;
  points: string[];
  accent: string;
  filled: boolean;
  kind: "title" | "section" | "closing";
}) {
  const sub = filled ? points[0] : undefined;
  const heading = filled
    ? title ?? (kind === "closing" ? "Thank You" : "Title")
    : undefined;
  return (
    <div className="flex flex-1 flex-col items-center justify-center text-center" style={{ gap: "2.5cqh" }}>
      <span className="rounded-full" style={{ background: accent, width: "14cqw", height: "1.2cqh" }} />
      {heading ? (
        <span
          className="line-clamp-2 font-bold text-white"
          style={{ fontSize: kind === "closing" ? "9cqw" : "7cqw", lineHeight: 1.1 }}
        >
          {heading}
        </span>
      ) : (
        <Bar w="56cqw" accent="rgba(255,255,255,0.32)" />
      )}
      {sub ? (
        <span className="line-clamp-1 text-white/60" style={{ fontSize: "3.4cqw" }}>
          {sub}
        </span>
      ) : (
        <Bar w="34cqw" dim />
      )}
    </div>
  );
}
