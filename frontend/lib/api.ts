import {
  PDFContext,
  GenerateResponse,
  StartSessionResponse,
  PageExtractionView,
  PageIntent,
  PlanResponse,
  SlideOutlineView,
  TemplateOption,
  GalleryImage,
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

/** Cropped PNG of a detected diagram region (for the Diagrams review tab).
 *  `rev` busts the browser cache after the box is re-adjusted. */
export function getFigureCropURL(
  sessionId: string,
  page: number,
  figureId: string,
  rev: number = 0
): string {
  return `${BASE_URL}/api/session/${sessionId}/page/${page}/figure/${encodeURIComponent(
    figureId
  )}/crop?v=${rev}`;
}

export interface FigureBBoxInput {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Apply user edits (label / question link / image-vs-text / box / placement). */
export async function updateFigure(
  sessionId: string,
  page: number,
  figureId: string,
  edits: {
    label?: string;
    belongs_to?: string;
    use_mode?: "image" | "text";
    included?: boolean;
    placement?: "own_slide" | "on_slide";
    size?: "small" | "medium" | "large";
    align?: "left" | "center" | "right";
    attached_slide_uid?: string;
    bbox?: FigureBBoxInput;
  }
): Promise<PageExtractionView> {
  const res = await fetch(
    `${BASE_URL}/api/session/${sessionId}/page/${page}/figure/${encodeURIComponent(
      figureId
    )}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(edits),
    }
  );
  return asJson<PageExtractionView>(res);
}

/** Manually add a figure (box drawn by the user) the AI missed. */
export async function addFigure(
  sessionId: string,
  page: number,
  body: {
    bbox: FigureBBoxInput;
    label?: string;
    belongs_to?: string;
    diagram_type?: string;
    description?: string;
    use_mode?: "image" | "text";
    placement?: "own_slide" | "on_slide";
  }
): Promise<PageExtractionView> {
  const res = await fetch(
    `${BASE_URL}/api/session/${sessionId}/page/${page}/figure`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  return asJson<PageExtractionView>(res);
}

/** Permanently delete a figure from a page. */
export async function deleteFigure(
  sessionId: string,
  page: number,
  figureId: string
): Promise<PageExtractionView> {
  const res = await fetch(
    `${BASE_URL}/api/session/${sessionId}/page/${page}/figure/${encodeURIComponent(
      figureId
    )}`,
    { method: "DELETE" }
  );
  return asJson<PageExtractionView>(res);
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

/** Fetch the already-built plan for a session (used by the Slide Studio). */
export async function getPlan(sessionId: string): Promise<PlanResponse> {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/plan`, {
    cache: "no-store",
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
  sessionId: string,
  templateFilename?: string | null,
): Promise<GenerateResponse> {
  const body = templateFilename ? JSON.stringify({ template_filename: templateFilename }) : undefined;
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/generate`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : {},
    body,
  });
  return asJson<GenerateResponse>(res);
}

export async function endSession(sessionId: string): Promise<void> {
  await fetch(`${BASE_URL}/api/session/${sessionId}`, { method: "DELETE" }).catch(
    () => {}
  );
}

/** Fetch the list of available PPT templates from the backend. */
export async function fetchTemplates(): Promise<TemplateOption[]> {
  try {
    const res = await fetch(`${BASE_URL}/api/templates`);
    if (!res.ok) return [];
    const data = await res.json();
    return (data.templates as TemplateOption[]) ?? [];
  } catch {
    return [];
  }
}

/** Store the user's chosen template in the session. */
export async function setSessionTemplate(
  sessionId: string,
  filename: string
): Promise<void> {
  await fetch(`${BASE_URL}/api/session/${sessionId}/template`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename }),
  });
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

// ── Image Gallery API ─────────────────────────────────────────────────────────

/** List all gallery images for a session (metadata only). */
export async function getGallery(sessionId: string): Promise<GalleryImage[]> {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/gallery`, {
    cache: "no-store",
  });
  const data = await asJson<{ images: GalleryImage[] }>(res);
  return data.images;
}

/** Direct URL to serve a gallery image as PNG (usable in <img src={...}>). */
export function getGalleryImageURL(sessionId: string, imageId: string): string {
  return `${BASE_URL}/api/session/${sessionId}/gallery/${encodeURIComponent(imageId)}`;
}

/** Crop an existing figure and save it to the gallery. */
export async function saveFigureToGallery(
  sessionId: string,
  page: number,
  figureId: string,
  label?: string
): Promise<GalleryImage> {
  const res = await fetch(
    `${BASE_URL}/api/session/${sessionId}/gallery/from-figure`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page, figure_id: figureId, label }),
    }
  );
  return asJson<GalleryImage>(res);
}

/** Generate a brand-new image from a text prompt (Imagen 3). */
export async function generateGalleryImage(
  sessionId: string,
  prompt: string,
  label?: string
): Promise<GalleryImage> {
  const res = await fetch(
    `${BASE_URL}/api/session/${sessionId}/gallery/generate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, label }),
    }
  );
  return asJson<GalleryImage>(res);
}

/** Edit an existing gallery image with a natural-language instruction. */
export async function editGalleryImage(
  sessionId: string,
  imageId: string,
  prompt: string,
  label?: string
): Promise<GalleryImage> {
  const res = await fetch(
    `${BASE_URL}/api/session/${sessionId}/gallery/edit`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_id: imageId, prompt, label }),
    }
  );
  return asJson<GalleryImage>(res);
}

/** Remove an image from the gallery. Returns the updated list. */
export async function deleteGalleryImage(
  sessionId: string,
  imageId: string
): Promise<GalleryImage[]> {
  const res = await fetch(
    `${BASE_URL}/api/session/${sessionId}/gallery/${encodeURIComponent(imageId)}`,
    { method: "DELETE" }
  );
  const data = await asJson<{ images: GalleryImage[] }>(res);
  return data.images;
}

/**
 * Add a gallery image to the slide deck as a figure on the first approved page.
 * Returns the updated PageExtractionView for that page so the caller can sync state.
 */
export async function useGalleryImageInDeck(
  sessionId: string,
  imageId: string
): Promise<PageExtractionView> {
  const res = await fetch(
    `${BASE_URL}/api/session/${sessionId}/gallery/${encodeURIComponent(imageId)}/use-in-deck`,
    { method: "POST" }
  );
  return asJson<PageExtractionView>(res);
}
