"use client";

import { PipelineStep } from "@/types";
import {
  FileStack,
  ScanSearch,
  LayoutList,
  PenLine,
  Presentation,
  Loader2,
  CheckCircle2,
  Clock3,
} from "lucide-react";

const ICONS = [FileStack, ScanSearch, LayoutList, PenLine, Presentation];

interface ProcessFlowProps {
  steps: PipelineStep[];
  fileName: string;
}

function StepIcon({
  index,
  status,
}: {
  index: number;
  status: PipelineStep["status"];
}) {
  const Icon = ICONS[index];

  if (status === "done") {
    return (
      <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-500/15 ring-1 ring-emerald-500/30">
        <CheckCircle2 className="h-5 w-5 text-emerald-400" />
      </div>
    );
  }

  if (status === "active") {
    return (
      <div className="relative flex h-11 w-11 items-center justify-center rounded-xl bg-violet-500/15 ring-1 ring-violet-500/40">
        <Icon className="h-5 w-5 text-violet-400" />
        <span className="absolute -right-1 -top-1 flex h-3 w-3">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-violet-400 opacity-75" />
          <span className="relative inline-flex h-3 w-3 rounded-full bg-violet-500" />
        </span>
      </div>
    );
  }

  return (
    <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/[0.04] ring-1 ring-white/8">
      <Icon className="h-5 w-5 text-zinc-600" />
    </div>
  );
}

export default function ProcessFlow({ steps, fileName }: ProcessFlowProps) {
  const activeStep = steps.find((s) => s.status === "active");
  const doneCount = steps.filter((s) => s.status === "done").length;
  const progress = Math.round((doneCount / steps.length) * 100);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="text-center">
        <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-violet-500/20 bg-violet-500/10 px-4 py-1.5">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-400" />
          <span className="text-xs font-medium text-violet-300">
            {activeStep ? activeStep.label : "Starting…"}
          </span>
        </div>
        <h2 className="text-lg font-semibold text-white">
          Converting your PDF to slides
        </h2>
        <p className="mt-1 truncate text-sm text-zinc-500">{fileName}</p>
      </div>

      {/* Progress Bar */}
      <div className="overflow-hidden rounded-full bg-white/5">
        <div
          className="h-1 rounded-full bg-gradient-to-r from-violet-600 to-violet-400 transition-all duration-700 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Steps */}
      <div className="space-y-3">
        {steps.map((step, i) => (
          <div
            key={step.id}
            className={`flex items-center gap-4 rounded-2xl border p-4 transition-all duration-500 ${
              step.status === "active"
                ? "border-violet-500/25 bg-violet-500/8"
                : step.status === "done"
                ? "border-emerald-500/15 bg-emerald-500/5"
                : "border-white/5 bg-white/[0.02]"
            }`}
          >
            <StepIcon index={i} status={step.status} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <p
                  className={`text-sm font-medium transition-colors ${
                    step.status === "active"
                      ? "text-white"
                      : step.status === "done"
                      ? "text-emerald-300"
                      : "text-zinc-500"
                  }`}
                >
                  {step.label}
                </p>
                {step.status === "active" && (
                  <span className="text-xs text-zinc-500 animate-pulse">
                    in progress…
                  </span>
                )}
              </div>
              <p
                className={`mt-0.5 text-xs transition-colors ${
                  step.status === "waiting" ? "text-zinc-700" : "text-zinc-500"
                }`}
              >
                {step.description}
              </p>
            </div>
            <div className="flex-shrink-0">
              {step.status === "waiting" && (
                <Clock3 className="h-4 w-4 text-zinc-700" />
              )}
              {step.status === "active" && (
                <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
              )}
              {step.status === "done" && (
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              )}
            </div>
          </div>
        ))}
      </div>

      <p className="text-center text-xs text-zinc-700">
        This usually takes 30–90 seconds depending on PDF size
      </p>
    </div>
  );
}
