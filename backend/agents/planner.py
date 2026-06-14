import json
import re
from google.genai import types
from agents.gemini_client import client
from schemas.extracted_page import ExtractedPage
from schemas.slide_plan import FullSlidePlan, SlideOutline, TemplateType
from schemas.request import PDFContext
from config import PLANNING_MODEL, MIN_SLIDES
from pipeline.token_tracker import record_api_attempt, record_api_failure, record_usage


# ── Annotation-driven "include" detection ────────────────────────────────────
#
# When the instructor configures an annotation type in the frontend with a
# reason like "include this question" / "mark important" / "do this on a
# slide", the extractor copies that reason into Annotation.instruction.
#
# We detect those "include"-style instructions so the planner knows that EVERY
# annotated item with such an instruction must get its own dedicated slide.

_INCLUDE_HINTS = (
    "include", "dedicated slide", "own slide", "must appear",
    "emphasize", "highlight as", "mark important", "key point",
    "important", "tick", "add", "add in ppt", "add to ppt",
    "added in ppt", "put in ppt", "use in ppt", "take in ppt",
    "ppt", "slide", "do this", "instructor wants",
)

_ONLY_MARKED_HINTS = (
    "only", "only add", "only include", "only tick", "only ticked",
    "tick one", "ticked one", "tick only", "ticked only",
    "only marked", "marked only", "selected only",
)

def _is_include_instruction(instr: str | None) -> bool:
    """True if the instruction looks like 'include this on a slide'."""
    if not instr:
        return False
    low = instr.lower()
    return any(h in low for h in _INCLUDE_HINTS)


def _is_only_marked_instruction(instr: str | None) -> bool:
    """True if the instructor wants the deck filtered to marked items only."""
    if not instr:
        return False
    low = instr.lower()
    has_only_marked = any(h in low for h in _ONLY_MARKED_HINTS)
    mentions_deck = any(h in low for h in ("ppt", "slide", "deck", "presentation"))
    return has_only_marked and (mentions_deck or _is_include_instruction(instr))


def _only_marked_mode(context: PDFContext) -> bool:
    """Selected annotation meanings like 'only add tick one in PPT' filter output."""
    return any(
        ann.selected and _is_only_marked_instruction(ann.reason)
        for ann in context.annotations
    )


def _strategy_block(strategy) -> str:
    """Inject the Profiler's DeckStrategy as structural guidance (if available)."""
    if strategy is None:
        return ""
    one_per = (
        "Because this is a question-style document, EVERY question/problem MUST "
        "get its own slide (one_item_per_slide)."
        if strategy.one_item_per_slide else
        "Group related theory together; do not force one-item-per-slide."
    )
    return f"""
═════════════════════════════════════════════════════════════════════════════
DECK STRATEGY (from the Profiler — high-level shape for THIS document)
═════════════════════════════════════════════════════════════════════════════
  Profile : {strategy.profile.value}
  Density : {strategy.density.value}
  {one_per}
  • Prefer theory_slide for explanatory passages: {strategy.prefer_theory_for_concepts}
  • Target ~{strategy.target_bullets_per_theory_slide} points per theory slide
    (the system will paginate longer ones automatically — do NOT drop content).
  Rationale: {strategy.rationale}
"""


def build_planning_prompt(context: PDFContext, strategy=None) -> str:
    """
    Build the planning prompt using form context.
    Purpose and class level change how slides are structured, but content
    (especially explicit instructor annotations) ALWAYS wins over heuristics.
    The optional DeckStrategy (Phase 2) adds document-level shape guidance.
    """

    only_marked = _only_marked_mode(context)

    if only_marked:
        rules = """
- The instructor selected an annotation meaning that says ONLY marked/ticked
  items should go into the PPT.
- Create slides ONLY for items listed in annotated_targets_that_need_their_own_slide.
- Do NOT create slides for unmarked questions, even if the purpose is Assignment,
  DPP, or Test paper.
- Keep only essential shared context that is needed to understand a marked item.
"""
    else:
        # purpose-specific rules — these are SOFT guidance, not hard caps
        purpose_rules = {
        "Lecture notes": """
- Full detailed coverage — every concept and example gets its own slide
- Include all diagrams and examples
- Use theory_slide for explanations, content_image for diagram pages
- There is NO limit on slide count — create as many slides as the content needs
""",
        "Revision": """
- Default style: concise bullets, no long explanations, skip non-essential examples
- BUT if the PDF is a QUESTION BANK (many MCQs / PYQs / numbered problems),
  every annotated/important question MUST get its own dedicated slide —
  do NOT sample, do NOT pick "representative" questions, do NOT cap at any number.
- If the PDF is a CONCEPT-revision sheet (definitions, formulas, key points
  with no questions), keep the deck short (5-10 slides) using theory_slide.
- There is NO limit on slide count — create as many slides as the content needs.
  If there are 30 annotated questions, create 30+ slides.
""",
        "DPP": """
- Each problem in the PDF gets exactly ONE slide (question + hints, no full solution)
- Group by difficulty if visible
- There is NO limit on slide count — one slide per problem, however many there are
""",
        "Assignment": """
- Each question in the PDF gets exactly ONE slide — questions only, no answers
- There is NO limit on slide count — one slide per question
""",
        "Test paper": """
- Format like an exam paper — each question on its own slide
- Questions grouped by section
- Include marks allocation if visible
- There is NO limit on slide count — one slide per question
""",
        "Formula sheet": """
- One formula or concept per slide
- Large text, minimal clutter
- Use theory_slide for visual formulas
- There is NO limit on slide count
""",
        "Chapter summary": """
- Overview of the full chapter — one topic per slide
- There is NO limit on slide count
""",
        "Mind map / overview": """
- Show topic connections — one major topic per slide
- Use theory_slide where possible
- There is NO limit on slide count
""",
        "Quick recap": """
- Maximum 5-6 slides — only the most critical points (exception: if the PDF
  is a question bank, every annotated question still gets its own slide)
- Very concise bullets — max 3 per slide
""",
        }

        rules = purpose_rules.get(context.purpose, f"""
- Total slide count is content-driven — NO upper cap. Min {MIN_SLIDES}.
- Create as many slides as the content demands.
- Balance detail and brevity per slide, but never skip content.
""")

    # tell the planner what the instructor configured per annotation TYPE
    annotation_meanings_block = ""
    if context.annotations:
        lines = []
        for ann in context.annotations:
            if not ann.selected:
                continue
            name = ann.customName if ann.type == "other" and ann.customName else ann.label
            reason = (ann.reason or "").strip() or "emphasize this on the slide"
            include_flag = " [INCLUDE-ON-DEDICATED-SLIDE]" if _is_include_instruction(reason) else ""
            lines.append(f"  - {ann.type} ({name}){include_flag}: {reason}")
        if lines:
            annotation_meanings_block = (
                "\nInstructor-defined annotation meanings (from the frontend form):\n"
                + "\n".join(lines)
                + "\n"
            )

    only_marked_instruction = (
        "If the instructor's annotation meaning says ONLY marked/ticked items "
        "should be in the PPT, this is an EXCLUSIVE FILTER: ignore unmarked "
        "questions when creating slides. Keep the full extracted text only as "
        "source context.\n"
        if only_marked else ""
    )

    return f"""
You are an expert teacher and presentation designer.

Subject: {context.subject}
Purpose: {context.purpose}
Class level: {context.class_level}
Language: {context.language}
Batch: {context.batch}
{f"Extra context: {context.extra_context}" if context.extra_context else ""}
{annotation_meanings_block}
{_strategy_block(strategy)}
You are given the FULL extracted content from a teaching PDF — one object per page.
Each page object has the complete main_text PLUS a list of annotations the
extractor found on that page (e.g. a circle on "Q.631", a square on
"Question number 30"). The annotations carry the instructor's intent.

Your job is to design a slide deck whose LENGTH is driven by content, not a
fixed count. There is ABSOLUTELY NO CAP on the number of slides you can create.
If the content needs 50 slides, create 50. If it needs 100, create 100.

═════════════════════════════════════════════════════════════════════════════
TOP-PRIORITY RULE 0 — USER INSTRUCTIONS OVERRIDE EVERYTHING
═════════════════════════════════════════════════════════════════════════════

Each page object may have an "instructor_notes" field AND an
"INSTRUCTOR_INSTRUCTION_HIGH_PRIORITY" field. Both carry explicit instructions
the user typed for that specific page (e.g. "include only Q5 and Q7",
"ignore the header", "Q15 text is wrong — use the corrected version").

These are the HIGHEST-PRIORITY inputs in the entire prompt:
  • They override purpose rules, heuristics, and annotation counts.
  • If a page says "include only Q5 and Q7", emit slides for Q5 and Q7 ONLY
    from that page — nothing else from that page's main_text.
  • If a page says "ignore the header", never put that header on a slide.
  • Process instructor_notes for EVERY page before deciding what slides to
    create for that page. Never skip them.

═════════════════════════════════════════════════════════════════════════════
TOP-PRIORITY RULE 1 — SELECTED QUESTIONS EACH GET THEIR OWN SLIDE
═════════════════════════════════════════════════════════════════════════════

Each page may carry a "questions_in_this_page_each_needs_its_own_slide" field.
This count is the MINIMUM number of body slides you must emit for that page.
  • One slide per question — do NOT merge, group, or drop any.
  • The global DECK SHAPE summary above states the total minimum. Your plan
    WILL BE REJECTED if it falls short.

═════════════════════════════════════════════════════════════════════════════
TOP-PRIORITY RULE 2 — ANNOTATIONS ARE INSTRUCTIONS, NOT DECORATIONS
═════════════════════════════════════════════════════════════════════════════

{only_marked_instruction}
If an annotation's instruction matches the instructor's "include" intent
(e.g. "INCLUDE this question on a dedicated slide", "emphasize on the slide",
"mark important", "key point"), then:

  • EVERY such annotated item MUST appear on its own dedicated slide.
  • The "annotation_count_with_include_intent" field on each page tells you
    EXACTLY how many such items live on that page. You MUST emit at LEAST
    that many body slides for that page.
  • Look at "annotated_targets_that_need_their_own_slide" — it lists the
    exact question numbers / labels that each need a slide. Walk through
    that list IN ORDER and emit one slide per target. Do not skip any
    target just because it looks similar to a neighbour.
  • Do NOT sample. Do NOT pick "representative" examples. Do NOT merge
    multiple annotated items into one slide. Do NOT skip any.
  • There is NO maximum slide limit. If a page has 20 circled question
    numbers, create 20 slides. If across all pages there are 50 annotated
    items, you MUST produce at least 50 body slides.
  • If a page has 16 circled question numbers (e.g. Q.660-Q.676), the deck
    MUST have 16 slides for those 16 questions — one per number, even if
    the questions look topically similar. The instructor circled all 16
    because they want all 16 reviewed.
  • Self-check before finalising: for every page p, count how many slides
    in your plan have p in source_pages. That count MUST be ≥
    annotation_count_with_include_intent for p. If it isn't, add the
    missing slides BEFORE returning.
  • COMMON FAILURE MODE: producing only 8-12 slides when there are 20+
    annotated items. This is WRONG. Check your total against the required
    minimum BEFORE returning.

Annotations that just describe formatting (underline marking a correct
answer, a struck-out exam tag, a handwritten 'o' next to options) are
INFORMATIONAL — use them when filling slides, but they do NOT each create
a new slide on their own.

═════════════════════════════════════════════════════════════════════════════
Purpose-specific guidance for "{context.purpose}"
═════════════════════════════════════════════════════════════════════════════
{rules}

═════════════════════════════════════════════════════════════════════════════
Available slide templates (pick the BEST fit for each piece of content)
═════════════════════════════════════════════════════════════════════════════

  STRUCTURAL
  - title_slide        → DO NOT use; design-provided title slides are handled outside this pipeline
  - recap_slide        → only when the PDF references a "previous lecture / last class"
  - topics_slide       → only when the PDF lists the agenda / topics to be covered
  - section_heading    → use SPARINGLY between major topic shifts; NEVER between
                         consecutive MCQs of the same set

  BODY
  - theory_slide       → definitions, explanations, formulas, key rules — 3-4 points
                         If a theory passage has more than 4 points, split it into
                         multiple theory_slide entries (same title, 3-4 points each).
  - table_slide        → a page whose primary content is a TABLE (rows × columns of
                         numbers, factors, comparison data, schedules). Pick this
                         WHENEVER the source shows tabular data that loses meaning if
                         prosified into bullets — discount-factor tables, comparison
                         charts, score grids, periodicity tables, etc. The writer
                         will preserve the table structure (headers + rows).
  - theory_table_slide → a page where a SHORT theory explanation directly accompanies
                         a SMALL reference table (≤ ~6 rows × ~5 columns) and the two
                         belong together. Use this only when both fit comfortably on
                         one slide. If the theory is long OR the table is large,
                         split into separate theory_slide + table_slide entries.
                         Decision recipe:
                           - theory ≤ 3 short bullets AND table ≤ 6 rows × 5 cols
                             → theory_table_slide
                           - otherwise → theory_slide(s) + table_slide
  - passage_slide      → a CLOZE / reading-comprehension PASSAGE shown VERBATIM with
                         its blanks intact (e.g. "__X__", "__Y__", ".....(1).....").
                         Use this — NOT theory_slide — whenever the source has a
                         "Directions (Q. n-m): Cloze Test / Comprehension – Passage k"
                         block. The passage is reproduced word-for-word so students
                         can read the gaps; the actual fill-in questions become
                         separate mcq_slide/question_only slides AFTER it.
  - mcq_slide          → MCQ with long options (full sentences / phrases)
  - mcq_grid_slide     → MCQ with short options (1-3 words, e.g. single-word substitutions)
  - question_only      → long-answer / subjective question without 4 options
  - pyq_slide          → MCQ marked as "PYQ" / "past year" / has exam-year info (long options)
  - pyq_grid_slide     → PYQ MCQ with short options
  - pyq_question_only  → PYQ subjective question

  CLOSING
  - summary            → DO NOT use; keep the generated deck focused on source content
  - homework_slide     → only when PDF has practice tasks / "do at home" / assignment
  - thank_you_slide    → always the final slide

═════════════════════════════════════════════════════════════════════════════
Structural rules
═════════════════════════════════════════════════════════════════════════════

1. Do NOT create a title_slide. The design team provides the title slide separately.
2. The generated deck should start directly with the first useful content slide.
3. Do NOT create a summary slide. It adds cost/time and is not needed.
4. The deck MUST end with thank_you_slide.
5. homework_slide is OPTIONAL — include only if the PDF actually lists practice tasks.
6. recap_slide and topics_slide are OPTIONAL — include only if such content exists.
7. section_heading is used to separate major topics. Do NOT insert one between
   two consecutive MCQs from the same exercise.
8. Choose mcq_slide vs mcq_grid_slide by option length:
     - all four options ≤ 3 words   → mcq_grid_slide
     - otherwise                    → mcq_slide
9. Mark a question as pyq_* if it carries year info (e.g., "SSC CGL 11/09/2019",
   "JEE 2022", "NEET 2021"). Otherwise use the plain mcq_* variant.
10. Every question goes on its own slide — never merge multiple questions.
11. If the PDF contains BOTH theory passages AND annotated questions, include
    both kinds of slides: theory_slides for the theory passages, mcq/pyq
    slides for every annotated question.
12. The slide TITLE for an mcq/pyq slide should be the question stem itself
    (e.g. "A large number of fish swimming together"), NOT a number like
    "Q.661". This makes the deck student-friendly.
12b. DUPLICATE TITLES — NEVER give two consecutive slides the exact same title.
    If a topic spans multiple slides, differentiate them:
      ✓  "Cost of Project M — Setup"  then  "Cost of Project M — Calculation"
      ✓  "Dividend Payout Ratio"  then  "Dividend Per Share"
      ✗  "CALCULATION OF DIVIDEND PAYOUT RATIO" then "CALCULATION OF DIVIDEND PAYOUT RATIO"
    Each slide title MUST be unique and describe that specific slide's content.
12c. SOLUTION SLIDES — when a slide presents a worked-out solution or answer
    derivation, prefix the title with "Solution:" so the renderer can add a
    distinct visual treatment. Example: "Solution: Cost of Project M".
13. TABLE coverage (CRITICAL — do not prosify tables):
    If the source page shows a rendered TABLE (a row × column grid of
    values — discount factors, comparison data, schedules, score grids,
    multi-row formulas with named columns), DO NOT cram its cells into
    theory bullets. Tables turn into unreadable prose ("For year 1 the
    factors are 0.869, 0.877, 0.885..."). Instead:
      (a) If the page is mostly that table → ONE table_slide.
      (b) If the page has a short paragraph PLUS a small table that explain
          each other → ONE theory_table_slide (bullets above, table below).
      (c) If the table is referenced by later questions, keep the table on
          ITS OWN slide (table_slide) — the question slides that follow do
          NOT re-render the table; they just refer to it.
      (d) Never split one logical table across multiple slides; if the
          table is very large, use table_slide and let the renderer
          auto-shrink the font.
    The writer will extract headers + rows from the source; the planner's
    job is just to pick the right layout.
14. CLOZE / READING-COMPREHENSION coverage (CRITICAL — do not under-cover):
    If the PDF contains cloze/comprehension passages (a paragraph with numbered
    or lettered blanks like "__X__", "__Y__", ".....(1).....", followed by
    answer options), then for EVERY passage in the document you MUST emit:
      (a) ONE passage_slide reproducing that passage VERBATIM with its blanks
          intact (title = a short label like "Passage 1"; the planner does NOT
          fill the text — the writer copies it word-for-word from the source).
      (b) ONE question slide (mcq_slide / mcq_grid_slide / question_only) for
          EACH blank in that passage, in order, carrying that blank's options.
    Do NOT collapse multiple passages into one slide. Do NOT keep only the first
    passage. If the source has Passage 1, Passage 2, Passage 3 … each one gets
    its own passage_slide plus its own set of per-blank question slides. The
    blanks must stay as blanks on the passage_slide — never fill them in.

═════════════════════════════════════════════════════════════════════════════
What to fill for each slide
═════════════════════════════════════════════════════════════════════════════

- slide_number    → 1-indexed
- title           → see rule 11 (question stem for MCQs; topic for theory)
- template        → from the list above
- source_pages    → list of page numbers from the PDF that this slide draws from
- key_points      → 3-5 short phrases describing what the slide carries
                    (for MCQs: the 4 options; for theory: the bullet points;
                    for pyq: also include the exam tag)
- emphasis        → list of instructor-marked items relevant to this slide
                    (e.g. ["circle on Q.661 — include this question"])
- include_diagram → true if the source page had a diagram worth showing

═════════════════════════════════════════════════════════════════════════════
VERBATIM CONTENT RULE — NO REWORDING EVER (ABSOLUTE)
═════════════════════════════════════════════════════════════════════════════

The PDF content is sacred. You are a PLANNER, not an author. You must NEVER:
  ✗ Paraphrase, reword, simplify, or "improve" any question, option, formula,
    theorem, definition, or problem statement from the source.
  ✗ Change a single word, number, unit, symbol, or punctuation mark in any
    question stem or answer option.
  ✗ Merge, split, summarise, or restructure the wording of any source content.

The title field for question slides MUST be the EXACT question text from
main_text — copy it character-for-character. The writer will do the same.
If the student compares the slide to the original PDF, they must see
IDENTICAL wording. Any change — even "and" → "&" — is a content error.

This applies equally to theory content: formulas, values, variable names,
and defined terms must appear in the plan exactly as they appear in the source.

Create the slide plan now. Do NOT pad with filler. Do NOT skip annotated items.
"""


# A cloze / comprehension passage is introduced by a "Directions (Q n-m): …"
# header. Each DISTINCT question-range = one passage that needs its own slide.
_PASSAGE_DIR_RE = re.compile(
    r'directions?\s*\(\s*(?:q\.?\s*(?:no\.?)?\s*)?(\d+)\s*[-–—]\s*(\d+)\s*\)',
    re.IGNORECASE,
)


def _source_passage_ranges(extracted_pages: list[ExtractedPage]) -> list[str]:
    """Distinct question-ranges of cloze/comprehension passages found in the source."""
    ranges: list[str] = []
    seen: set[str] = set()
    for p in extracted_pages:
        for m in _PASSAGE_DIR_RE.finditer(p.main_text or ""):
            key = f"{m.group(1)}-{m.group(2)}"
            if key not in seen:
                seen.add(key)
                ranges.append(key)
    return ranges


def _count_source_passages(extracted_pages: list[ExtractedPage]) -> int:
    return len(_source_passage_ranges(extracted_pages))


def _count_plan_passages(plan: FullSlidePlan) -> int:
    return sum(1 for s in plan.slides if s.template.value == "passage_slide")


def _strip_unneeded_structural_slides(plan: FullSlidePlan) -> FullSlidePlan:
    """Remove slides that are now supplied externally or intentionally skipped."""
    skipped = {TemplateType.title_slide, TemplateType.summary}
    slides = [s for s in plan.slides if s.template not in skipped]
    for idx, slide in enumerate(slides, start=1):
        slide.slide_number = idx
    return FullSlidePlan(total_slides=len(slides), slides=slides)


def _count_include_annotations(page: ExtractedPage) -> int:
    """How many annotations on this page carry an 'include on its own slide' intent."""
    return sum(1 for a in page.annotations if _is_include_instruction(a.instruction))


def _count_questions_in_text(page: ExtractedPage) -> int:
    """
    Count detectable numbered questions in this page's main_text.

    Used when no tick/annotation system is active — the user picked questions via
    the checkbox UI, curated_pages() already filtered main_text to only those
    questions, and we need to tell the planner "one slide per question here".
    """
    from pipeline.page_items import split_page_items
    items = split_page_items(page.page_number, page.main_text)
    return sum(1 for it in items if it["kind"] == "question")


def _summarize_include_targets(page: ExtractedPage) -> list[str]:
    """Compact list of the annotation TARGETS that must each get a slide. No limit."""
    targets = []
    for a in page.annotations:
        if _is_include_instruction(a.instruction):
            t = (a.target or "").strip()
            if t:
                targets.append(t)
    return targets


def _looks_tabular(text: str) -> bool:
    """
    Heuristic table sniff for the planner — catches tables that extraction did
    NOT flag (has_table=false) because they were borderless / tab-aligned, e.g.
    a "Indian Civilization vs Western Civilization" two-column comparison.

    A page is treated as tabular if EITHER:
      • it has ≥3 pipe-delimited rows ("a | b | c"), OR
      • it has ≥3 lines that each split into ≥2 columns by a TAB or a run of
        2+ spaces (aligned columns), OR
      • it mentions a comparison ("vs"/"versus"/"comparison") AND has ≥2 such
        aligned multi-column lines.
    """
    if not text:
        return False
    if text.count(" | ") >= 3:
        return True

    lines = [ln for ln in text.splitlines() if ln.strip()]
    multicol = 0
    for ln in lines:
        if "\t" in ln or len(re.split(r"\s{2,}", ln.strip())) >= 2:
            multicol += 1
    if multicol >= 3:
        return True

    low = text.lower()
    if multicol >= 2 and (" vs " in low or " versus " in low or "comparison" in low):
        return True
    return False


def _detect_table_pages(extracted_pages: list[ExtractedPage]) -> str:
    """Generate a TABLE DETECTION summary for the planner prompt."""
    table_pages = []
    for p in extracted_pages:
        has_explicit = getattr(p, 'has_table', False)
        text = (p.main_text or "")
        ct = p.content_type.value if hasattr(p.content_type, 'value') else str(p.content_type)
        if has_explicit or _looks_tabular(text) or ct == "table":
            desc = getattr(p, 'table_description', None) or "(table detected from content)"
            table_pages.append(f"  - Page {p.page_number}: {desc}")
    if not table_pages:
        return ""
    return (
        "\n⚠️ TABLE DETECTION — HARD CONSTRAINT ⚠️\n"
        "The following pages contain TABLES (grids of values). For EACH such "
        "page you MUST emit at least ONE slide whose template is table_slide "
        "(table only) or theory_table_slide (≤3 bullets + small table) that "
        "carries the table data. Even if the page ALSO has theory prose that you "
        "split onto separate theory_slides, the TABLE portion gets its own "
        "table_slide. NEVER prosify a table into theory bullets like 'the factors "
        "are 0.869, 0.877…' — that is unreadable. Give the table slide a clear "
        "title like 'Discount Factors' or 'PV Factors'.\n"
        + "\n".join(table_pages) + "\n"
    )


def _global_summary(
    extracted_pages: list[ExtractedPage],
    context: PDFContext,
    question_count_override: int = 0,
) -> str:
    """
    Top-of-prompt summary the planner reads BEFORE the per-page JSON.

    `question_count_override` is set when the user selected questions via the
    checkbox UI (no tick annotations). curated_pages() already filtered
    main_text to only those questions, so the override tells the planner
    "there are N questions in what you're seeing — every one needs its own slide."
    """
    total_include = sum(_count_include_annotations(p) for p in extracted_pages)
    only_marked = _only_marked_mode(context)
    per_page = []
    for p in extracted_pages:
        n = _count_include_annotations(p)
        if n > 0:
            targets = _summarize_include_targets(p)
            targets_str = ", ".join(targets[:10])
            if len(targets) > 10:
                targets_str += f" ... and {len(targets) - 10} more"
            per_page.append(
                f"page {p.page_number}: {n} item(s) marked for inclusion "
                f"[{targets_str}]"
            )

    # ── Checkbox-based selection (no annotations, but user hand-picked questions) ──
    if total_include == 0 and question_count_override > 0:
        per_page_q = []
        for p in extracted_pages:
            from pipeline.page_items import split_page_items
            items = split_page_items(p.page_number, p.main_text)
            q_count = sum(1 for it in items if it["kind"] == "question")
            if q_count:
                per_page_q.append(f"page {p.page_number}: {q_count} question(s)")
        per_page_str = "\n  - ".join(per_page_q) if per_page_q else "(see main_text)"
        return (
            f"⚠️ HARD CONSTRAINT — USER-SELECTED QUESTIONS ⚠️\n"
            f"The user reviewed each page and hand-picked the questions to include.\n"
            f"main_text for each page contains ONLY those selected questions.\n"
            f"Total selected questions across all pages: {question_count_override}\n"
            f"  - {per_page_str}\n\n"
            f"RULES (NON-NEGOTIABLE):\n"
            f"  1. Create EXACTLY ONE body slide per question — do NOT merge, group,\n"
            f"     or drop any question.\n"
            f"  2. MINIMUM body slides required: {question_count_override}.\n"
            f"  3. If a page has an instructor_notes field, FOLLOW IT — it is the\n"
            f"     user's explicit instruction and overrides any heuristic.\n"
            f"  4. Do NOT add slides for content that is not in main_text.\n\n"
            f"YOUR PLAN WILL BE REJECTED if it has fewer than {question_count_override} "
            f"body slides."
        )

    if total_include == 0:
        if only_marked:
            return (
                "DECK SHAPE — ONLY-MARKED mode is active, but no marked items "
                "were detected in extraction. Do not invent marked targets. "
                "Create only a thank_you_slide unless the user re-extracts the "
                "page and the annotation is detected."
            )
        return (
            "DECK SHAPE — no annotated items detected. Plan based on the text "
            "content only, following the purpose-specific guidance above.\n"
            "Create as many slides as the content demands — there is no upper limit.\n"
            "If instructor_notes are present on any page, treat them as HIGH-PRIORITY "
            "instructions and follow them exactly."
        )
    if only_marked:
        return (
            f"⚠️ HARD CONSTRAINT — ONLY MARKED ITEMS GO INTO THE PPT ⚠️\n"
            f"The instructor's annotation meaning says to include ONLY marked/ticked "
            f"items. The extractor found {total_include} marked item(s):\n  - "
            + "\n  - ".join(per_page)
            + f"\n\n"
            f"Create EXACTLY {total_include} body slide(s), one per marked target, "
            f"plus the final thank_you_slide. Do NOT add slides for unmarked "
            f"questions from main_text. main_text is provided only so you can copy "
            f"the full wording of the marked targets.\n"
            f"YOUR PLAN WILL BE REJECTED if it has fewer OR more than "
            f"{total_include} body slides."
        )
    return (
        f"⚠️ HARD CONSTRAINT — DECK SHAPE ⚠️\n"
        f"The extractor found {total_include} item(s) the instructor "
        f"marked for inclusion on a dedicated slide:\n  - "
        + "\n  - ".join(per_page)
        + f"\n\n"
        f"MINIMUM body slides required: {total_include} "
        f"(one per annotated item). This is NON-NEGOTIABLE.\n"
        f"Plus: thank_you_slide at end only. Do NOT add title_slide or summary.\n"
        f"You may add theory_slides for any non-question theory content, "
        f"and section_heading between major topic shifts.\n\n"
        f"YOUR PLAN WILL BE REJECTED if it has fewer than {total_include} "
        f"body slides. Do NOT approximate. Do NOT sample. Include ALL {total_include}."
    )


MAX_PLAN_RETRIES = 2


def plan_slides(
    extracted_pages: list[ExtractedPage],
    context: PDFContext,
    strategy=None,
) -> FullSlidePlan:
    """
    Takes all extracted pages + context.
    Returns a FullSlidePlan object.

    Key design choices:
      • main_text is sent IN FULL — no truncation. The planner cannot make
        good decisions if it can't see most of the source content.
      • Each page carries an 'annotation_count_with_include_intent' field so
        the planner knows exactly how many dedicated slides each page needs.
      • A global DECK SHAPE summary sits at the top of the prompt so the
        planner sees the required slide count BEFORE reading page details.
      • If the planner returns fewer body slides than annotated items demand,
        we RETRY with explicit feedback about the shortfall.
    """

    # ── Per-page question counts (for checkbox-selection enforcement) ────────
    annotation_total = sum(_count_include_annotations(p) for p in extracted_pages)
    # When no annotation marks exist the user selected via checkboxes.
    # curated_pages() already filtered main_text → count what's in there now.
    question_count_per_page: dict[int, int] = {}
    if annotation_total == 0:
        for p in extracted_pages:
            qc = _count_questions_in_text(p)
            if qc:
                question_count_per_page[p.page_number] = qc
    question_count_total = sum(question_count_per_page.values())

    pages_data = []
    for page in extracted_pages:
        include_n = _count_include_annotations(page)
        include_targets = _summarize_include_targets(page)
        page_entry = {
            "page_number":        page.page_number,
            "content_type":       page.content_type,
            "main_text":          page.main_text,
            "diagrams_described": page.diagrams_described,
            "instructor_notes":   page.instructor_notes,
            "annotation_count_with_include_intent": include_n,
            "annotated_targets_that_need_their_own_slide": include_targets,
            "annotations": [
                {
                    "type":        ann.type,
                    "target":      ann.target,
                    "instruction": ann.instruction,
                    "is_include_intent": _is_include_instruction(ann.instruction),
                }
                for ann in page.annotations
            ]
        }
        # Inject per-page question count so the AI knows exactly how many
        # slides this page requires even without explicit annotations.
        pq = question_count_per_page.get(page.page_number, 0)
        if pq:
            page_entry["questions_in_this_page_each_needs_its_own_slide"] = pq
        # Surface instructor_notes as a top-priority field so it's hard to miss.
        if page.instructor_notes:
            page_entry["INSTRUCTOR_INSTRUCTION_HIGH_PRIORITY"] = (
                f"⚠️ USER INSTRUCTION FOR THIS PAGE: {page.instructor_notes} — "
                f"This overrides any heuristic. Follow it exactly."
            )
        if getattr(page, 'has_table', False):
            page_entry["has_table"] = True
            page_entry["table_description"] = getattr(page, 'table_description', None) or ""
            page_entry["TABLE_LAYOUT_HINT"] = (
                "⚠️ This page contains a TABLE. Use table_slide (table only) or "
                "theory_table_slide (short theory + table). Do NOT use theory_slide "
                "and prosify the table data into bullet text."
            )
        pages_data.append(page_entry)

    prompt = build_planning_prompt(context, strategy)
    only_marked = _only_marked_mode(context)
    summary = _global_summary(extracted_pages, context, question_count_override=question_count_total)

    # Detect cloze/comprehension passages so we can REQUIRE one passage_slide each.
    passage_ranges = _source_passage_ranges(extracted_pages)
    expected_passages = len(passage_ranges)
    passage_block = ""
    if expected_passages:
        passage_block = (
            f"\n\n⚠️ PASSAGE COVERAGE — HARD CONSTRAINT ⚠️\n"
            f"The source contains {expected_passages} distinct cloze/comprehension "
            f"passage(s), identified by these Directions ranges: "
            f"{', '.join(passage_ranges)}.\n"
            f"You MUST emit EXACTLY ONE passage_slide for EACH of these "
            f"{expected_passages} passages (reproduce the passage verbatim, blanks "
            f"intact), PLUS one question slide per blank. Do NOT drop, merge, or "
            f"skip any passage. Your plan will be REJECTED if it has fewer than "
            f"{expected_passages} passage_slides.\n"
        )

    table_block = _detect_table_pages(extracted_pages)

    full_prompt = (
        f"{prompt}\n\n"
        f"{summary}"
        f"{passage_block}"
        f"{table_block}\n\n"
        f"Here is the extracted page data (full text for source context"
        f"{' — create slides only for marked targets' if only_marked else ' — do not skip any'}):\n"
        f"{json.dumps(pages_data, indent=2, ensure_ascii=False)}"
    )

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=FullSlidePlan
    )

    # Use annotation count if any annotations exist; otherwise fall back to the
    # question count derived from curated main_text (checkbox selection path).
    expected_min_body = annotation_total or question_count_total

    plan = None
    for attempt in range(1, MAX_PLAN_RETRIES + 2):
        current_prompt = full_prompt

        if attempt > 1 and plan is not None:
            actual_body = sum(
                1 for s in plan.slides
                if s.template.value in {
                    "theory_slide", "mcq_slide", "mcq_grid_slide", "question_only",
                    "pyq_slide", "pyq_grid_slide", "pyq_question_only",
                }
            )
            actual_passages = _count_plan_passages(plan)
            shortfall_lines = ["\n\n⚠️ RETRY — YOUR PREVIOUS PLAN WAS REJECTED."]
            if actual_body < expected_min_body:
                shortfall_lines.append(
                    f"• You produced only {actual_body} body slides but the instructor "
                    f"annotated {expected_min_body} items that each need their own slide "
                    f"(short by {expected_min_body - actual_body}). Walk EVERY page's "
                    f"'annotated_targets_that_need_their_own_slide' list and emit one "
                    f"slide per target. Do NOT sample."
                )
            if only_marked and actual_body > expected_min_body:
                shortfall_lines.append(
                    f"• ONLY-MARKED mode is active. You produced {actual_body} body "
                    f"slides, but only {expected_min_body} marked item(s) should go "
                    f"into the PPT. Remove slides for unmarked questions and return "
                    f"EXACTLY {expected_min_body} body slide(s), plus thank_you_slide."
                )
            if actual_passages < expected_passages:
                shortfall_lines.append(
                    f"• You produced only {actual_passages} passage_slides but the source "
                    f"has {expected_passages} passages ({', '.join(passage_ranges)}) — "
                    f"short by {expected_passages - actual_passages}. Emit ONE "
                    f"passage_slide for EVERY passage range, plus its per-blank question "
                    f"slides. Do NOT drop or merge any passage."
                )
            current_prompt = full_prompt + "\n".join(shortfall_lines) + "\n"
            print(f"    Retry {attempt - 1}: body={actual_body}/{expected_min_body}, "
                  f"passages={actual_passages}/{expected_passages}. Re-planning...")

        try:
            record_api_attempt("planning", PLANNING_MODEL)
            response = client.models.generate_content(
                model=PLANNING_MODEL,
                contents=current_prompt,
                config=config
            )
        except Exception:
            record_api_failure("planning", PLANNING_MODEL)
            raise
        record_usage("planning", response.usage_metadata, model=PLANNING_MODEL)

        try:
            plan = response.parsed
        except Exception as e:
            raise ValueError(f"Planner agent failed: {e}")
        plan = _strip_unneeded_structural_slides(plan)

        actual_body = sum(
            1 for s in plan.slides
            if s.template.value in {
                "theory_slide", "mcq_slide", "mcq_grid_slide", "question_only",
                "pyq_slide", "pyq_grid_slide", "pyq_question_only",
            }
        )
        actual_passages = _count_plan_passages(plan)

        body_ok = (
            actual_body == expected_min_body
            if only_marked
            else expected_min_body == 0 or actual_body >= expected_min_body
        )
        passages_ok = actual_passages >= expected_passages
        if body_ok and passages_ok:
            break

    print(f"  Slide plan created — {plan.total_slides} slides "
          f"(body={actual_body}/{'=' if only_marked else '≥'}{expected_min_body} annotated, "
          f"passages={actual_passages}/{expected_passages})")
    if expected_min_body > 0 and actual_body < expected_min_body:
        print(f"  ⚠️  WARNING: planner still short by {expected_min_body - actual_body} "
              f"body slides after {MAX_PLAN_RETRIES} retries")
    if only_marked and actual_body > expected_min_body:
        print(f"  ⚠️  WARNING: planner still has {actual_body - expected_min_body} "
              f"extra unmarked body slides after {MAX_PLAN_RETRIES} retries")
    if actual_passages < expected_passages:
        print(f"  ⚠️  WARNING: planner still short by {expected_passages - actual_passages} "
              f"passage slides after {MAX_PLAN_RETRIES} retries")
    return plan


def replan_single_slide(
    outline: SlideOutline,
    extracted_pages: list[ExtractedPage],
    context: PDFContext,
    feedback: str,
) -> SlideOutline:
    """
    Interactive mode — rewrite ONE slide's outline using the user's feedback.

    The user reviewed the planned slide and asked for a change (e.g. "show all
    four options in full", "this should be a theory slide, not an MCQ", "use the
    full question stem as the title"). We give the model the current outline, the
    text of the source pages this slide draws from, and the feedback, and return a
    corrected SlideOutline. The slide_number is preserved by the caller.
    """
    # Only feed the relevant source pages so the prompt stays small + focused.
    src_nums = set(outline.source_pages or [])
    by_num = {p.page_number: p for p in extracted_pages}
    src_text_parts = []
    for n in sorted(src_nums):
        p = by_num.get(n)
        if p is not None:
            src_text_parts.append(f"--- Page {n} ---\n{p.main_text or ''}")
    if not src_text_parts:  # fall back to all pages if source_pages was empty
        src_text_parts = [
            f"--- Page {p.page_number} ---\n{p.main_text or ''}"
            for p in extracted_pages
        ]
    source_text = "\n\n".join(src_text_parts)

    template_values = ", ".join(t.value for t in TemplateType)

    prompt = f"""You are revising ONE slide in a teaching deck based on direct
user feedback. Return the corrected slide outline as JSON.

Subject: {context.subject} · Purpose: {context.purpose} · Language: {context.language}

CURRENT SLIDE OUTLINE:
  slide_number : {outline.slide_number}
  title        : {outline.title}
  template     : {outline.template.value}
  source_pages : {outline.source_pages}
  key_points   : {outline.key_points}
  include_diagram : {outline.include_diagram}

SOURCE CONTENT (verbatim from the PDF pages this slide draws from):
{source_text}

USER FEEDBACK (apply this exactly):
  "{feedback.strip()}"

Rules:
• Keep slide_number = {outline.slide_number}.
• template MUST be one of: {template_values}
• For an MCQ/question slide, the title should be the question stem itself and
  key_points should carry the options / sub-points.
• Only change what the feedback asks for; preserve everything else that was
  already correct. Do not invent content not present in the source.

Return JSON matching the SlideOutline schema."""

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=SlideOutline,
    )
    try:
        record_api_attempt("planning", PLANNING_MODEL)
        response = client.models.generate_content(
            model=PLANNING_MODEL,
            contents=prompt,
            config=config,
        )
    except Exception:
        record_api_failure("planning", PLANNING_MODEL)
        raise
    record_usage("planning", response.usage_metadata, model=PLANNING_MODEL)

    revised = response.parsed
    if revised is None:
        raise ValueError("Slide re-plan failed: empty response")
    revised.slide_number = outline.slide_number  # never let the model renumber
    return revised