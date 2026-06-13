"use client";

import { PDFContext } from "@/types";
import { ChevronDown, Info } from "lucide-react";

interface ContextFormProps {
  context: PDFContext;
  onChange: (ctx: PDFContext) => void;
}

const inputCls =
  "w-full rounded-xl border border-white/8 bg-white/4 px-4 py-2.5 text-sm text-white placeholder-zinc-600 outline-none transition-all focus:border-violet-500/60 focus:bg-white/6 focus:ring-1 focus:ring-violet-500/30";

const selectCls =
  "w-full appearance-none rounded-xl border border-white/8 bg-white/4 px-4 py-2.5 text-sm text-white outline-none transition-all focus:border-violet-500/60 focus:bg-white/6 focus:ring-1 focus:ring-violet-500/30 cursor-pointer";

const labelCls = "mb-1.5 block text-xs font-medium uppercase tracking-wider text-zinc-500";

function SelectWrapper({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative">
      {children}
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-600" />
    </div>
  );
}

export default function ContextForm({ context, onChange }: ContextFormProps) {
  const set = <K extends keyof PDFContext>(key: K, val: PDFContext[K]) =>
    onChange({ ...context, [key]: val });

  return (
    <div className="space-y-6">
      {/* Row 1: Subject + Batch */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelCls}>Subject *</label>
          <SelectWrapper>
            <select
              className={selectCls}
              value={context.subject}
              onChange={(e) => set("subject", e.target.value)}
            >
              <option value="" disabled>
                Select subject
              </option>
              <option value="Physics">Physics</option>
              <option value="Chemistry">Chemistry</option>
              <option value="Mathematics">Mathematics</option>
              <option value="Biology">Biology</option>
              <option value="English">English</option>
              <option value="Social Science">Social Science</option>
              <option value="Other">Other</option>
            </select>
          </SelectWrapper>
        </div>
        <div>
          <label className={labelCls}>Batch *</label>
          <input
            className={inputCls}
            placeholder="e.g. JEE 2025 Batch A"
            value={context.batch}
            onChange={(e) => set("batch", e.target.value)}
          />
        </div>
      </div>

      {/* Row 2: Purpose + Category (optional) */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelCls}>Purpose *</label>
          <SelectWrapper>
            <select
              className={selectCls}
              value={context.purpose}
              onChange={(e) => set("purpose", e.target.value)}
            >
              <option value="" disabled>
                Select purpose
              </option>
              <option value="Revision">Revision</option>
              <option value="Lecture Notes">Lecture Notes</option>
              <option value="DPP">DPP (Daily Practice)</option>
              <option value="Summary">Summary</option>
              <option value="Assignment">Assignment</option>
              <option value="Test Paper">Test Paper</option>
              <option value="Formula Sheet">Formula Sheet</option>
            </select>
          </SelectWrapper>
        </div>
        <div>
          <label className={labelCls}>Category / Level (optional)</label>
          <SelectWrapper>
            <select
              className={selectCls}
              value={context.class_level}
              onChange={(e) => set("class_level", e.target.value)}
            >
              <option value="">Not specified</option>
              <option value="Class 1-5">Class 1-5</option>
              <option value="Class 6-8">Class 6-8</option>
              <option value="Class 9-10">Class 9-10</option>
              <option value="Class 11-12">Class 11-12</option>
              <option value="UG / College">UG / College</option>
              <option value="Competitive Exam">Competitive Exam</option>
            </select>
          </SelectWrapper>
        </div>
      </div>

      {/* Row 3: Language */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelCls}>Language *</label>
          <SelectWrapper>
            <select
              className={selectCls}
              value={context.language}
              onChange={(e) => set("language", e.target.value)}
            >
              <option value="Same as source">Same as source (keep original)</option>
              <option value="English">English</option>
              <option value="Hindi">Hindi</option>
              <option value="Hinglish">Hinglish</option>
            </select>
          </SelectWrapper>
        </div>
      </div>

      {/* What happens next — sets expectations, replaces the old annotation form */}
      <div className="flex items-start gap-3 rounded-2xl border border-violet-500/15 bg-violet-500/5 p-4">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-violet-400" />
        <p className="text-xs leading-relaxed text-zinc-400">
          Next, you&apos;ll review every page the AI read. For each page you
          decide what goes into the PPT — keep everything, pick specific
          questions, or skip the page. No need to configure marks here.
        </p>
      </div>

      {/* Extra Context */}
      <div>
        <label className={labelCls}>Extra Context (optional)</label>
        <textarea
          className={`${inputCls} min-h-[80px] resize-none`}
          placeholder="Any additional instructions for the AI…"
          value={context.extra_context || ""}
          onChange={(e) => set("extra_context", e.target.value || undefined)}
        />
      </div>
    </div>
  );
}
