/**
 * Slide-type catalog — the single source of truth for how each backend
 * TemplateType (see backend/schemas/slide_plan.py) is presented in the UI:
 * its label, category, colour accent, description, and the schematic "shape"
 * used to draw a layout preview.
 *
 * Keep the `key` values in sync with the backend TemplateType enum.
 */

export type SlideCategory =
  | "structural"
  | "theory"
  | "question"
  | "table"
  | "figure"
  | "closing";

/** Which schematic layout to draw for a given type. */
export type SchematicShape =
  | "title"
  | "numbered"
  | "section"
  | "bullets"
  | "table"
  | "bullets_table"
  | "passage"
  | "mcq"
  | "mcq_grid"
  | "question"
  | "figure"
  | "closing";

export interface SlideTypeDef {
  key: string;
  label: string;
  category: SlideCategory;
  description: string;
  shape: SchematicShape;
  /** Whether the PYQ "exam year" tag should be drawn. */
  pyq?: boolean;
  /** Show this type in the per-slide "change type" picker. */
  pickable: boolean;
}

export interface CategoryMeta {
  key: SlideCategory;
  label: string;
  /** Tailwind-ish hex used for accents/dots/bars across the studio. */
  color: string;
}

export const CATEGORY_META: Record<SlideCategory, CategoryMeta> = {
  question: { key: "question", label: "Questions", color: "#818cf8" }, // indigo-400
  theory: { key: "theory", label: "Theory", color: "#22d3ee" }, // cyan-400
  table: { key: "table", label: "Tables", color: "#fbbf24" }, // amber-400
  figure: { key: "figure", label: "Figures", color: "#34d399" }, // emerald-400
  structural: { key: "structural", label: "Structure", color: "#a1a1aa" }, // zinc-400
  closing: { key: "closing", label: "Closing", color: "#f472b6" }, // pink-400
};

export const SLIDE_TYPES: SlideTypeDef[] = [
  // ── Structural ────────────────────────────────────────────────────────────
  {
    key: "title_slide",
    label: "Title",
    category: "structural",
    description: "Opening slide — chapter, subject and purpose.",
    shape: "title",
    pickable: true,
  },
  {
    key: "recap_slide",
    label: "Recap",
    category: "structural",
    description: "“Recap of previous lecture” — numbered points.",
    shape: "numbered",
    pickable: true,
  },
  {
    key: "topics_slide",
    label: "Topics",
    category: "structural",
    description: "“Topics to be covered” — numbered agenda.",
    shape: "numbered",
    pickable: true,
  },
  {
    key: "section_heading",
    label: "Section",
    category: "structural",
    description: "Divider shown when a new topic begins.",
    shape: "section",
    pickable: true,
  },
  // ── Theory ─────────────────────────────────────────────────────────────────
  {
    key: "theory_slide",
    label: "Theory",
    category: "theory",
    description: "Explanation, definitions or a formula list.",
    shape: "bullets",
    pickable: true,
  },
  {
    key: "passage_slide",
    label: "Passage",
    category: "theory",
    description: "Reading-comprehension / cloze passage, verbatim.",
    shape: "passage",
    pickable: true,
  },
  // ── Tables ─────────────────────────────────────────────────────────────────
  {
    key: "table_slide",
    label: "Table",
    category: "table",
    description: "A real rendered table — headers and rows.",
    shape: "table",
    pickable: true,
  },
  {
    key: "theory_table_slide",
    label: "Theory + Table",
    category: "table",
    description: "Short theory bullets above a reference table.",
    shape: "bullets_table",
    pickable: true,
  },
  // ── Questions ──────────────────────────────────────────────────────────────
  {
    key: "mcq_slide",
    label: "MCQ",
    category: "question",
    description: "Question with four options in a single column.",
    shape: "mcq",
    pickable: true,
  },
  {
    key: "mcq_grid_slide",
    label: "MCQ Grid",
    category: "question",
    description: "Question with four short options in a 2×2 grid.",
    shape: "mcq_grid",
    pickable: true,
  },
  {
    key: "question_only",
    label: "Question",
    category: "question",
    description: "Long-answer / subjective question — no options.",
    shape: "question",
    pickable: true,
  },
  {
    key: "pyq_slide",
    label: "PYQ",
    category: "question",
    description: "Past-year MCQ with an exam-year tag, single column.",
    shape: "mcq",
    pyq: true,
    pickable: true,
  },
  {
    key: "pyq_grid_slide",
    label: "PYQ Grid",
    category: "question",
    description: "Past-year MCQ with a 2×2 option grid.",
    shape: "mcq_grid",
    pyq: true,
    pickable: true,
  },
  {
    key: "pyq_question_only",
    label: "PYQ Subjective",
    category: "question",
    description: "Past-year subjective question — no options.",
    shape: "question",
    pyq: true,
    pickable: true,
  },
  // ── Figures ────────────────────────────────────────────────────────────────
  {
    key: "figure_slide",
    label: "Figure",
    category: "figure",
    description: "A diagram / figure as a cropped image or description.",
    shape: "figure",
    pickable: false, // injected from the Diagrams review, not hand-picked
  },
  // ── Closing ────────────────────────────────────────────────────────────────
  {
    key: "summary",
    label: "Summary",
    category: "closing",
    description: "Key takeaways at the end of the deck.",
    shape: "bullets",
    pickable: true,
  },
  {
    key: "homework_slide",
    label: "Homework",
    category: "closing",
    description: "Practice / assignment list.",
    shape: "bullets",
    pickable: true,
  },
  {
    key: "thank_you_slide",
    label: "Thank You",
    category: "closing",
    description: "Decorative closing slide.",
    shape: "closing",
    pickable: true,
  },
];

const BY_KEY: Record<string, SlideTypeDef> = Object.fromEntries(
  SLIDE_TYPES.map((t) => [t.key, t])
);

const FALLBACK: SlideTypeDef = {
  key: "unknown",
  label: "Slide",
  category: "structural",
  description: "Slide layout.",
  shape: "bullets",
  pickable: false,
};

export function getSlideType(key: string): SlideTypeDef {
  return BY_KEY[key] ?? { ...FALLBACK, key, label: key };
}

export function categoryColor(key: string): string {
  return CATEGORY_META[getSlideType(key).category].color;
}

/** Pickable types grouped by category, in display order. */
export const PICKABLE_BY_CATEGORY: { meta: CategoryMeta; types: SlideTypeDef[] }[] =
  (["question", "theory", "table", "structural", "closing"] as SlideCategory[])
    .map((cat) => ({
      meta: CATEGORY_META[cat],
      types: SLIDE_TYPES.filter((t) => t.category === cat && t.pickable),
    }))
    .filter((g) => g.types.length > 0);
