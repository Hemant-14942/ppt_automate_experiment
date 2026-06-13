import {
  PDFContext,
  GenerateResponse,
  StartSessionResponse,
  PageExtractionView,
  PageIntent,
  PlanResponse,
  SlideOutlineView,
} from "@/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || `Server error: ${res.status}`);
  }
  return res.json();
}

export async function generatePPT(
  file: File,
  context: PDFContext
): Promise<GenerateResponse> {
  const formData = new FormData();
  formData.append("pdf_file", file);
  formData.append("context_json", JSON.stringify(context));

  const res = await fetch(`${BASE_URL}/api/generate`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || `Server error: ${res.status}`);
  }

  return res.json();
}

export async function generatePPTFromUrl(
  pdfUrl: string,
  context: PDFContext
): Promise<GenerateResponse> {
  const formData = new FormData();
  formData.append("pdf_url", pdfUrl);
  formData.append("context_json", JSON.stringify(context));

  const res = await fetch(`${BASE_URL}/api/generate-from-url`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || `Server error: ${res.status}`);
  }

  return res.json();
}

/**
 * Download URLs go through the Next.js proxy routes (/api/download/... and
 * /api/download-pdf/...) so they are same-origin. The browser's `download`
 * attribute only works on same-origin URLs — a direct link to the FastAPI
 * backend (different port) would open a blank tab instead of saving the file.
 */
export function getDownloadURL(filename: string): string {
  return `/api/download/${encodeURIComponent(filename)}`;
}

export function getPreviewURL(filename: string): string {
  return `${BASE_URL}/api/preview/${encodeURIComponent(filename)}`;
}

export function getPdfDownloadURL(filename: string): string {
  return `/api/download-pdf/${encodeURIComponent(filename)}`;
}

export interface HealthStatus {
  online: boolean;
  previewAvailable: boolean;
}

export async function checkHealth(): Promise<HealthStatus> {
  try {
    const res = await fetch(`${BASE_URL}/api/health`, { cache: "no-store" });
    if (!res.ok) return { online: false, previewAvailable: false };
    const data = await res.json();
    return {
      online: true,
      previewAvailable: Boolean(data.preview_available),
    };
  } catch {
    return { online: false, previewAvailable: false };
  }
}

// ── Interactive (human-in-the-loop) session API ──────────────────────────────

export async function startSession(
  source: { file?: File; url?: string },
  context: PDFContext
): Promise<StartSessionResponse> {
  const formData = new FormData();
  formData.append("context_json", JSON.stringify(context));
  if (source.file) formData.append("pdf_file", source.file);
  if (source.url) formData.append("pdf_url", source.url);

  const res = await fetch(`${BASE_URL}/api/session/start`, {
    method: "POST",
    body: formData,
  });
  return asJson<StartSessionResponse>(res);
}

export function getPageImageURL(sessionId: string, page: number): string {
  return `${BASE_URL}/api/session/${sessionId}/page-image/${page}`;
}

export async function reExtractPage(
  sessionId: string,
  page: number,
  feedback: string
): Promise<PageExtractionView> {
  const res = await fetch(
    `${BASE_URL}/api/session/${sessionId}/page/${page}/re-extract`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ feedback }),
    }
  );
  return asJson<PageExtractionView>(res);
}

export async function setPageStatus(
  sessionId: string,
  page: number,
  status: "approved" | "skipped" | "pending"
): Promise<PageExtractionView> {
  const res = await fetch(
    `${BASE_URL}/api/session/${sessionId}/page/${page}/status`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }
  );
  return asJson<PageExtractionView>(res);
}

export async function setPageIntent(
  sessionId: string,
  page: number,
  intent: PageIntent
): Promise<PageExtractionView> {
  const res = await fetch(
    `${BASE_URL}/api/session/${sessionId}/page/${page}/intent`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(intent),
    }
  );
  return asJson<PageExtractionView>(res);
}

export async function buildPlan(sessionId: string): Promise<PlanResponse> {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/plan`, {
    method: "POST",
  });
  return asJson<PlanResponse>(res);
}

export async function rewriteSlide(
  sessionId: string,
  slide: number,
  feedback: string
): Promise<SlideOutlineView> {
  const res = await fetch(
    `${BASE_URL}/api/session/${sessionId}/slide/${slide}/rewrite`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ feedback }),
    }
  );
  return asJson<SlideOutlineView>(res);
}

export async function editSlide(
  sessionId: string,
  slide: number,
  edits: { title?: string; key_points?: string[]; template?: string }
): Promise<SlideOutlineView> {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/slide/${slide}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(edits),
  });
  return asJson<SlideOutlineView>(res);
}

export async function deleteSlide(
  sessionId: string,
  slide: number
): Promise<PlanResponse> {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/slide/${slide}`, {
    method: "DELETE",
  });
  return asJson<PlanResponse>(res);
}

export async function addSlide(
  sessionId: string,
  body: {
    after_slide_number: number;
    source_page: number;
    title?: string;
    feedback?: string;
  }
): Promise<PlanResponse> {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/slide/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return asJson<PlanResponse>(res);
}

export async function reorderSlides(
  sessionId: string,
  order: number[]
): Promise<PlanResponse> {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/slides/reorder`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ order }),
  });
  return asJson<PlanResponse>(res);
}

export async function generateFromSession(
  sessionId: string
): Promise<GenerateResponse> {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/generate`, {
    method: "POST",
  });
  return asJson<GenerateResponse>(res);
}

export async function endSession(sessionId: string): Promise<void> {
  await fetch(`${BASE_URL}/api/session/${sessionId}`, { method: "DELETE" }).catch(
    () => {}
  );
}

export async function checkSessionAlive(sessionId: string): Promise<boolean> {
  try {
    const res = await fetch(`${BASE_URL}/api/session/${sessionId}/status`, {
      cache: "no-store",
    });
    return res.ok;
  } catch {
    return false;
  }
}
