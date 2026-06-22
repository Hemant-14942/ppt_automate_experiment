export interface AnnotationItem {
  id: string;
  type: "circle" | "tick" | "highlight" | "handwritten" | "other";
  label: string;
  selected: boolean;
  reason?: string;
  customName?: string; // for 'other'
}

export interface PDFContext {
  batch: string;
  purpose: string;
  subject: string;
  class_level: string;
  language: string;
  annotations: AnnotationItem[];
  extra_context?: string;
}

export interface AnalyticsRow {
  stage: string;
  model: string;
  attempts: number;
  responses: number;
  failures: number;
  input_tokens: number;
  output_tokens: number;
  thinking_tokens: number;
  total_tokens: number;
  cost_usd: number;
}

export interface AnalyticsTotals {
  attempts: number;
  responses: number;
  failures: number;
  input_tokens: number;
  output_tokens: number;
  thinking_tokens: number;
  total_tokens: number;
  cost_usd: number;
}

export interface Analytics {
  elapsed_seconds: number;
  pricing_note: string;
  totals: AnalyticsTotals;
  rows: AnalyticsRow[];
}

export interface GenerateResponse {
  status: "success" | "error";
  job_id?: string;
  filename?: string;
  download_url?: string;
  preview_url?: string;
  total_pages?: number;
  total_slides?: number;
  message?: string;
  /** Which reference template file was used to build this deck. */
  template_used?: string;
  analytics?: Analytics;
}

// ── Interactive (human-in-the-loop) flow ─────────────────────────────────────

export type PageStatus = "pending" | "approved" | "skipped";

export interface AnnotationView {
  type: string;
  target: string;
  instruction: string;
}

export type PageIntentMode = "all" | "choose";

export interface PageItemView {
  id: string;
  label: string;
  preview: string;
  text: string;
  kind: "question" | "intro";
}

export interface FigureBBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type FigureUseMode = "image" | "text";
export type FigurePlacement = "own_slide" | "on_slide";
export type FigureSize = "small" | "medium" | "large";
export type FigureAlign = "left" | "center" | "right";

export interface FigureView {
  id: string;
  description: string;
  belongs_to?: string | null;
  diagram_type?: string | null;
  bbox?: FigureBBox | null;
  position?: string | null;
  label: string;
  use_mode: FigureUseMode;
  source: "ai" | "manual" | "gallery";
  has_crop: boolean;
  included: boolean;
  placement: FigurePlacement;
  size: FigureSize;
  align: FigureAlign;
  attached_slide_uid?: string | null;
  gallery_id?: string | null;
  rev: number;
}

export interface PageExtractionView {
  page_number: number;
  status: PageStatus;
  content_type: string;
  main_text: string;
  diagrams_described?: string | null;
  table_description?: string | null;
  has_table: boolean;
  instructor_notes?: string | null;
  detected_language?: string | null;
  should_skip: boolean;
  annotations: AnnotationView[];
  last_feedback?: string | null;
  question_count: number;
  items: PageItemView[];
  intent_mode: PageIntentMode;
  selected_item_ids: string[];
  page_instruction?: string | null;
  figures?: FigureView[];
}

export interface PageIntent {
  mode: PageIntentMode;
  selected_item_ids: string[];
  instruction?: string | null;
}

export interface StartSessionResponse {
  session_id: string;
  total_pages: number;
  pages: PageExtractionView[];
  analytics?: Analytics;
}

export interface SlideOutlineView {
  slide_number: number;
  title: string;
  template: string;
  uid?: string;
  source_pages: number[];
  key_points: string[];
  include_diagram: boolean;
  emphasis: string[];
  analytics?: Analytics;
}

export interface PlanResponse {
  session_id: string;
  total_slides: number;
  slides: SlideOutlineView[];
  analytics?: Analytics;
}

export type AppStep =
  | "upload"
  | "configure"
  | "choose-template"
  | "review-pages"
  | "review-plan"
  | "generating"
  | "done";

export interface TemplateOption {
  id: string;
  name: string;
  filename: string;
}

export type PipelineStepStatus = "waiting" | "active" | "done" | "error";

export interface PipelineStep {
  id: number;
  label: string;
  description: string;
  status: PipelineStepStatus;
}

// ── Image gallery ─────────────────────────────────────────────────────────────

export type GalleryImageSource = "crop" | "generated" | "edited";

export interface GalleryImage {
  id: string;
  label: string;
  source: GalleryImageSource;
  mime: string;
  prompt?: string | null;
  parent_id?: string | null;
  figure_ref?: { page: number; id: string } | null;
  created_at: number;
}

export interface GalleryResponse {
  images: GalleryImage[];
}
