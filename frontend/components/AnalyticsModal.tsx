"use client";

import { useEffect } from "react";
import { Analytics, AnalyticsRow } from "@/types";
import {
  X,
  Clock,
  IndianRupee,
  Cpu,
  Activity,
  AlertTriangle,
  Coins,
  Layers,
} from "lucide-react";

interface AnalyticsModalProps {
  analytics: Analytics;
  onClose: () => void;
}

// ── formatting helpers ───────────────────────────────────────────────
const fmtInt = (n: number) => n.toLocaleString("en-IN");

// 1 USD ≈ ₹84 (fixed reference rate for display)
const USD_TO_INR = 84;

const fmtINR = (usd: number): string => {
  const inr = usd * USD_TO_INR;
  if (inr >= 1) return `₹${inr.toFixed(2)}`;
  if (inr >= 0.01) return `₹${inr.toFixed(3)}`;
  return `₹${inr.toFixed(4)}`;
};

const fmtUSD = (n: number): string => {
  if (n >= 1) return `$${n.toFixed(2)}`;
  return `$${n.toFixed(4)}`;
};

// Primary ₹ with small $ in brackets
const fmtCost = (usd: number): string => `${fmtINR(usd)}  (${fmtUSD(usd)})`;

const fmtTime = (secs: number) => {
  const s = Math.round(secs);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m ? `${m}m ${r}s` : `${r}s`;
};

const fmtTokens = (n: number) => {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return `${n}`;
};

// Palette used for stage/model bars and the legend.
const PALETTE = [
  "#8b5cf6", // violet
  "#10b981", // emerald
  "#f59e0b", // amber
  "#3b82f6", // blue
  "#ec4899", // pink
  "#14b8a6", // teal
  "#ef4444", // red
  "#a78bfa", // light violet
];

function StatCard({
  icon,
  label,
  value,
  sub,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  accent: string;
}) {
  return (
    <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4">
      <div className="flex items-center gap-2">
        <div
          className="flex h-8 w-8 items-center justify-center rounded-lg"
          style={{ backgroundColor: `${accent}1a`, color: accent }}
        >
          {icon}
        </div>
        <p className="text-xs font-medium text-zinc-400">{label}</p>
      </div>
      <p className="mt-3 text-2xl font-bold text-white">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-zinc-500">{sub}</p>}
    </div>
  );
}

// ── Donut chart for the input / output / thinking token split ─────────
function TokenDonut({ analytics }: { analytics: Analytics }) {
  const { input_tokens, output_tokens, thinking_tokens, total_tokens } =
    analytics.totals;
  const segments = [
    { label: "Input", value: input_tokens, color: "#3b82f6" },
    { label: "Output", value: output_tokens, color: "#10b981" },
    { label: "Thinking", value: thinking_tokens, color: "#f59e0b" },
  ].filter((s) => s.value > 0);

  const R = 56;
  const C = 2 * Math.PI * R;
  const total = total_tokens || 1;
  let offset = 0;

  return (
    <div className="flex items-center gap-5">
      <svg width="140" height="140" viewBox="0 0 140 140" className="flex-shrink-0">
        <circle
          cx="70"
          cy="70"
          r={R}
          fill="none"
          stroke="#27272a"
          strokeWidth="16"
        />
        {segments.map((s) => {
          const frac = s.value / total;
          const dash = frac * C;
          const el = (
            <circle
              key={s.label}
              cx="70"
              cy="70"
              r={R}
              fill="none"
              stroke={s.color}
              strokeWidth="16"
              strokeDasharray={`${dash} ${C - dash}`}
              strokeDashoffset={-offset}
              transform="rotate(-90 70 70)"
              strokeLinecap="butt"
            />
          );
          offset += dash;
          return el;
        })}
        <text
          x="70"
          y="66"
          textAnchor="middle"
          className="fill-white"
          style={{ fontSize: 18, fontWeight: 700 }}
        >
          {fmtTokens(total_tokens)}
        </text>
        <text
          x="70"
          y="84"
          textAnchor="middle"
          className="fill-zinc-500"
          style={{ fontSize: 10 }}
        >
          tokens
        </text>
      </svg>

      <div className="space-y-2">
        {segments.map((s) => (
          <div key={s.label} className="flex items-center gap-2">
            <span
              className="h-3 w-3 rounded-sm"
              style={{ backgroundColor: s.color }}
            />
            <span className="text-sm text-zinc-300">{s.label}</span>
            <span className="text-sm font-semibold text-white">
              {fmtInt(s.value)}
            </span>
            <span className="text-xs text-zinc-500">
              ({((s.value / total) * 100).toFixed(0)}%)
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Horizontal bar chart (used for cost + tokens per stage/model) ─────
function BarChart({
  rows,
  valueOf,
  format,
}: {
  rows: AnalyticsRow[];
  valueOf: (r: AnalyticsRow) => number;
  format: (v: number) => string;
}) {
  const max = Math.max(...rows.map(valueOf), 1);
  return (
    <div className="space-y-3">
      {rows.map((r, i) => {
        const v = valueOf(r);
        const pct = (v / max) * 100;
        const color = PALETTE[i % PALETTE.length];
        return (
          <div key={`${r.stage}-${r.model}`}>
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="text-zinc-300">
                <span className="font-medium capitalize text-white">
                  {r.stage}
                </span>{" "}
                <span className="text-zinc-500">· {r.model}</span>
              </span>
              <span className="font-semibold text-white">{format(v)}</span>
            </div>
            <div className="h-2.5 w-full overflow-hidden rounded-full bg-white/[0.05]">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.max(pct, 2)}%`,
                  backgroundColor: color,
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function AnalyticsModal({
  analytics,
  onClose,
}: AnalyticsModalProps) {
  // close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const { totals, rows, elapsed_seconds, pricing_note } = analytics;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="my-8 w-full max-w-4xl rounded-3xl border border-white/10 bg-[#111113] shadow-2xl shadow-black/60"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/8 px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-violet-600/20 text-violet-300">
              <Activity className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">
                Run Analytics
              </h2>
              <p className="text-xs text-zinc-500">
                AI usage, cost &amp; time for this presentation
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/8 bg-white/[0.04] text-zinc-400 transition-all hover:bg-white/[0.08]"
            aria-label="Close analytics"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="space-y-6 p-6">
          {/* Top stat cards */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard
              icon={<IndianRupee className="h-4 w-4" />}
              label="Total Cost"
              value={fmtINR(totals.cost_usd)}
              sub={`${fmtUSD(totals.cost_usd)} · model-aware`}
              accent="#10b981"
            />
            <StatCard
              icon={<Clock className="h-4 w-4" />}
              label="Total Time"
              value={fmtTime(elapsed_seconds)}
              sub="end to end"
              accent="#3b82f6"
            />
            <StatCard
              icon={<Coins className="h-4 w-4" />}
              label="Total Tokens"
              value={fmtTokens(totals.total_tokens)}
              sub={`${fmtInt(totals.total_tokens)} tokens`}
              accent="#f59e0b"
            />
            <StatCard
              icon={<Activity className="h-4 w-4" />}
              label="API Calls"
              value={fmtInt(totals.responses)}
              sub={`${totals.attempts} tries · ${totals.failures} failed`}
              accent="#8b5cf6"
            />
          </div>

          {/* Charts row */}
          <div className="grid gap-4 md:grid-cols-2">
            {/* Token split donut */}
            <div className="rounded-2xl border border-white/8 bg-white/[0.02] p-5">
              <div className="mb-4 flex items-center gap-2">
                <Cpu className="h-4 w-4 text-zinc-400" />
                <h3 className="text-sm font-semibold text-white">
                  Token Breakdown
                </h3>
              </div>
              <TokenDonut analytics={analytics} />
            </div>

            {/* Cost per stage */}
            <div className="rounded-2xl border border-white/8 bg-white/[0.02] p-5">
              <div className="mb-4 flex items-center gap-2">
                <IndianRupee className="h-4 w-4 text-zinc-400" />
                <h3 className="text-sm font-semibold text-white">
                  Cost by Stage &amp; Model
                </h3>
              </div>
              {rows.length ? (
                <BarChart rows={rows} valueOf={(r) => r.cost_usd} format={fmtCost} />
              ) : (
                <p className="text-sm text-zinc-500">No cost data.</p>
              )}
            </div>
          </div>

          {/* Tokens per stage */}
          <div className="rounded-2xl border border-white/8 bg-white/[0.02] p-5">
            <div className="mb-4 flex items-center gap-2">
              <Layers className="h-4 w-4 text-zinc-400" />
              <h3 className="text-sm font-semibold text-white">
                Tokens by Stage &amp; Model
              </h3>
            </div>
            {rows.length ? (
              <BarChart
                rows={rows}
                valueOf={(r) => r.total_tokens}
                format={fmtTokens}
              />
            ) : (
              <p className="text-sm text-zinc-500">No token data.</p>
            )}
          </div>

          {/* Detailed table */}
          <div className="overflow-hidden rounded-2xl border border-white/8">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-white/[0.04] text-zinc-400">
                  <tr>
                    <th className="px-3 py-2.5 font-medium">Stage</th>
                    <th className="px-3 py-2.5 font-medium">Model</th>
                    <th className="px-3 py-2.5 text-right font-medium">Calls</th>
                    <th className="px-3 py-2.5 text-right font-medium">Fail</th>
                    <th className="px-3 py-2.5 text-right font-medium">Input</th>
                    <th className="px-3 py-2.5 text-right font-medium">Output</th>
                    <th className="px-3 py-2.5 text-right font-medium">Think</th>
                    <th className="px-3 py-2.5 text-right font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {rows.map((r, i) => (
                    <tr key={`${r.stage}-${r.model}`} className="text-zinc-300">
                      <td className="px-3 py-2.5">
                        <span className="flex items-center gap-2">
                          <span
                            className="h-2.5 w-2.5 rounded-sm"
                            style={{
                              backgroundColor: PALETTE[i % PALETTE.length],
                            }}
                          />
                          <span className="capitalize text-white">
                            {r.stage}
                          </span>
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-zinc-400">{r.model}</td>
                      <td className="px-3 py-2.5 text-right">{r.responses}</td>
                      <td className="px-3 py-2.5 text-right">
                        {r.failures > 0 ? (
                          <span className="inline-flex items-center gap-1 text-red-400">
                            <AlertTriangle className="h-3 w-3" />
                            {r.failures}
                          </span>
                        ) : (
                          <span className="text-zinc-600">0</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        {fmtInt(r.input_tokens)}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        {fmtInt(r.output_tokens)}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        {fmtInt(r.thinking_tokens)}
                      </td>
                      <td className="px-3 py-2.5 text-right font-semibold text-white">
                        {fmtINR(r.cost_usd)}
                        <span className="ml-1 text-[10px] font-normal text-zinc-500">
                          ({fmtUSD(r.cost_usd)})
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="bg-white/[0.04] font-semibold text-white">
                  <tr>
                    <td className="px-3 py-2.5" colSpan={2}>
                      Total
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      {totals.responses}
                    </td>
                    <td className="px-3 py-2.5 text-right">{totals.failures}</td>
                    <td className="px-3 py-2.5 text-right">
                      {fmtInt(totals.input_tokens)}
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      {fmtInt(totals.output_tokens)}
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      {fmtInt(totals.thinking_tokens)}
                    </td>
                    <td className="px-3 py-2.5 text-right text-emerald-300">
                      {fmtINR(totals.cost_usd)}
                      <span className="ml-1 text-[10px] font-normal text-zinc-500">
                        ({fmtUSD(totals.cost_usd)})
                      </span>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>

          {/* Pricing note */}
          <p className="text-center text-[11px] leading-relaxed text-zinc-600">
            {pricing_note}
          </p>
        </div>
      </div>
    </div>
  );
}
