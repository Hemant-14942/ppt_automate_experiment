import {
  AppStep,
  PDFContext,
  GenerateResponse,
  PageExtractionView,
  PlanResponse,
} from "@/types";

/**
 * Shared client-side session persistence.
 *
 * The wizard (app/page.tsx) and the Slide Studio (app/studio/page.tsx) both
 * read/write the SAME localStorage key so the user can move between the two
 * without losing their place. Keep the shape in sync across both surfaces.
 */
export const STORAGE_KEY = "deckpilot_session";

/**
 * Separate key for template selection — persisted immediately when the user
 * picks a template, independent of whether a session exists yet.
 * This prevents the common bug where the template is lost because
 * saveToStorage guards on `sessionId` being set.
 */
const TEMPLATE_KEY = "deckpilot_template";

/** Save the selected template filename independently of session state. */
export function saveTemplate(filename: string | null) {
  try {
    if (filename) {
      localStorage.setItem(TEMPLATE_KEY, filename);
    } else {
      localStorage.removeItem(TEMPLATE_KEY);
    }
  } catch {
    // localStorage blocked — fail silently
  }
}

/** Load the last-saved template filename (survives session clear). */
export function loadTemplate(): string | null {
  try {
    return localStorage.getItem(TEMPLATE_KEY) ?? null;
  } catch {
    return null;
  }
}

export interface PersistedState {
  sessionId: string;
  step: AppStep;
  context: PDFContext;
  pages: PageExtractionView[];
  plan: PlanResponse | null;
  result: GenerateResponse | null;
  selectedTemplate: string | null;
  savedAt: number;
}

export function loadFromStorage(): PersistedState | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as PersistedState;
  } catch {
    return null;
  }
}

export function saveToStorage(state: Partial<PersistedState>) {
  try {
    const existing = loadFromStorage();
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ ...existing, ...state, savedAt: Date.now() })
    );
  } catch {
    // localStorage may be blocked (private mode, quota exceeded) — fail silently
  }
}

export function clearStorage() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
