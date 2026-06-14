"use client";

import { useRef, useState, useCallback } from "react";
import { UploadCloud, FileText, X } from "lucide-react";

interface FileUploadProps {
  file: File | null;
  onFileSelect: (file: File) => void;
  onFileClear: () => void;
}

export default function FileUpload({
  file,
  onFileSelect,
  onFileClear,
}: FileUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleFile = useCallback(
    (f: File) => {
      if (!f.name.endsWith(".pdf")) {
        alert("Only PDF files are accepted.");
        return;
      }
      onFileSelect(f);
    },
    [onFileSelect]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const f = e.dataTransfer.files[0];
      if (f) handleFile(f);
    },
    [handleFile]
  );

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };
  const onDragLeave = () => setIsDragging(false);

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  if (file) {
    return (
      <div className="animate-pop flex items-center gap-4 rounded-2xl border border-violet-500/30 bg-violet-500/[0.07] px-5 py-4 ring-1 ring-violet-500/10">
        <div className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl bg-violet-500/15">
          <FileText className="h-5 w-5 text-violet-300" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-white">{file.name}</p>
          <p className="mt-0.5 flex items-center gap-1.5 text-xs text-zinc-500">
            <span className="inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
            {formatBytes(file.size)} · ready to analyse
          </p>
        </div>
        <button
          onClick={onFileClear}
          aria-label="Remove file"
          className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg text-zinc-500 transition-colors hover:bg-white/5 hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      className={`group relative flex cursor-pointer flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed px-8 py-14 text-center transition-all duration-200 ${
        isDragging
          ? "scale-[1.01] border-violet-400 bg-violet-500/10 ring-2 ring-violet-500/20"
          : "border-white/10 bg-white/[0.02] hover:border-white/20 hover:bg-white/[0.04]"
      }`}
    >
      <div
        className={`flex h-14 w-14 items-center justify-center rounded-2xl transition-colors duration-200 ${
          isDragging ? "bg-violet-500/20" : "bg-white/5 group-hover:bg-white/10"
        }`}
      >
        <UploadCloud
          className={`h-6 w-6 transition-colors duration-200 ${
            isDragging ? "text-violet-400" : "text-zinc-400 group-hover:text-white"
          }`}
        />
      </div>
      <div>
        <p className="text-sm font-medium text-white">
          Drop your PDF here{" "}
          <span className="text-zinc-500">or click to browse</span>
        </p>
        <p className="mt-1 text-xs text-zinc-600">PDF files only · Max 50MB</p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handleFile(f);
        }}
      />
    </div>
  );
}
