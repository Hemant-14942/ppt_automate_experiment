"""
Profiler Agent  (Phase 2)

Runs ONCE, right after extraction and before planning. It looks at the whole
extracted PDF + the instructor's form context and classifies the document into
a ContentProfile, then emits a DeckStrategy that steers the rest of the
pipeline:

  • Planner — structure (one-item-per-slide for question banks, theory-heavy
    for lecture notes, etc.)
  • Writer  — verbosity (terse phrases vs full sentences vs thorough paragraphs)
  • Fit engine — how aggressively to paginate for readability

It is a single cheap LLM call (flash model, structured output). If it fails,
callers fall back to DeckStrategy.default() so the pipeline is never blocked.
"""
import json
from collections import Counter
from google.genai import types

from agents.gemini_client import client
from schemas.extracted_page import ExtractedPage
from schemas.deck_strategy  import DeckStrategy
from schemas.request        import PDFContext
from config import PROFILER_MODEL
from pipeline.token_tracker import record_api_attempt, record_api_failure, record_usage


def _content_signals(extracted_pages: list[ExtractedPage]) -> dict:
    """Compact, quantitative summary of what the PDF actually contains."""
    type_counts = Counter(
        (p.content_type.value if hasattr(p.content_type, "value") else str(p.content_type))
        for p in extracted_pages
    )
    total_annotations = sum(len(p.annotations) for p in extracted_pages)

    # cheap heuristics the LLM can lean on
    mcq_like = sum(
        1 for p in extracted_pages
        if "(a)" in (p.main_text or "").lower() and "(b)" in (p.main_text or "").lower()
    )
    year_tagged = sum(
        1 for p in extracted_pages
        if any(tok in (p.main_text or "") for tok in
               ("PYQ", "SSC", "JEE", "NEET", "UPSC", "20", "19"))
    )
    return {
        "n_pages": len(extracted_pages),
        "content_type_counts": dict(type_counts),
        "total_annotations": total_annotations,
        "pages_with_mcq_options": mcq_like,
        "pages_with_exam_or_year_tags": year_tagged,
    }


def _build_prior_block(prior: dict | None) -> str:
    """Inject calibration learned from past similar decks (Phase 4)."""
    if not prior:
        return ""
    return f"""
LEARNED PRIOR — from {prior.get('runs', '?')} past deck(s) for this
subject+purpose (use as a starting point; let the actual content override):
  • tended toward density: {prior.get('recommended_density', 'balanced')}
  • theory slides averaged ~{prior.get('avg_bullets_per_theory_slide', '?')} bullets
    → suggested target_bullets_per_theory_slide ≈ {prior.get('suggested_theory_bullet_target', 5)}
  • ~{prior.get('avg_slides_per_page', '?')} slides per source page
  • past overflow rate: {prior.get('overflow_rate', 0.0)} (lower is better)
"""


def _build_profiler_prompt(
    extracted_pages: list[ExtractedPage],
    context: PDFContext,
    prior: dict | None = None,
) -> str:
    signals = _content_signals(extracted_pages)

    # short text samples so the model can "see" the material without bloat
    samples = []
    for p in extracted_pages[:6]:
        samples.append({
            "page": p.page_number,
            "type": p.content_type.value if hasattr(p.content_type, "value") else str(p.content_type),
            "text": (p.main_text or "")[:300],
        })

    return f"""You are a curriculum analyst. Classify ONE teaching PDF and decide
the best high-level strategy for turning it into a slide deck.

INSTRUCTOR CONTEXT (their intent — weigh this heavily):
  Subject     : {context.subject}
  Purpose     : {context.purpose}
  Class level : {context.class_level}
  Language    : {context.language}
  {f"Extra note  : {context.extra_context}" if context.extra_context else ""}

QUANTITATIVE SIGNALS extracted from the PDF:
{json.dumps(signals, indent=2)}

CONTENT SAMPLES (first pages):
{json.dumps(samples, indent=2, ensure_ascii=False)}
{_build_prior_block(prior)}
CLASSIFY into one `profile`:
  • theory         — definitions / explanations, few or no questions
  • lecture_notes  — full teaching content, examples, derivations
  • dpp            — daily practice problems (questions + hints, not full solutions)
  • question_bank  — many MCQs / PYQs (lots of (a)(b)(c)(d) options, exam tags)
  • formula_sheet  — mostly formulas / key results, minimal prose
  • mixed          — a genuine blend of theory AND questions

DECIDE `density`:
  • terse    — Revision / Quick recap, or content that is already point-form
  • balanced — default
  • verbose  — Lecture notes, or rich theory that deserves full explanation

THEN set the steering flags:
  • one_item_per_slide        — TRUE for dpp / question_bank (one question per slide).
  • prefer_theory_for_concepts— TRUE unless the doc is almost entirely questions.
  • target_bullets_per_theory_slide — 3-4 for terse, 5-6 balanced, 6-8 verbose.
  • bullet_style              — "phrase" (terse), "sentence" (balanced),
                                "paragraph" (verbose).
  • rationale                 — ONE short sentence on why.

GUIDANCE:
  - Purpose is a strong hint: "Revision"→often terse; "Lecture notes"→verbose;
    "DPP"/"Assignment"/"Test paper"→one_item_per_slide; "Formula sheet"→formula_sheet.
  - But let the actual content override: if purpose=Revision yet the PDF is a
    big MCQ bank, profile=question_bank and one_item_per_slide=TRUE.

Return JSON only, matching the DeckStrategy schema.
"""


def profile_deck(
    extracted_pages: list[ExtractedPage],
    context: PDFContext,
    learned_profiles: list[dict] | None = None,
) -> DeckStrategy:
    """
    Single LLM call → DeckStrategy. Falls back to defaults on any error.

    `learned_profiles` (Phase 4) is the `learned_profiles` list from style.yaml;
    if a calibration exists for this subject+purpose it is injected as a prior.
    """
    if not extracted_pages:
        return DeckStrategy.default()

    # local import avoids a circular dependency (pipeline → agents → pipeline)
    from pipeline.profile_learner import find_learned_profile
    prior = find_learned_profile(learned_profiles, context.subject, context.purpose)

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=DeckStrategy,
    )
    response = None
    try:
        record_api_attempt("planning", PROFILER_MODEL)
        response = client.models.generate_content(
            model=PROFILER_MODEL,
            contents=_build_profiler_prompt(extracted_pages, context, prior),
            config=config,
        )
        record_usage("planning", response.usage_metadata, model=PROFILER_MODEL)
        return response.parsed
    except Exception as e:
        if response is None:
            record_api_failure("planning", PROFILER_MODEL)
        print(f"  Profiler failed ({e}); using balanced defaults")
        return DeckStrategy.default()


def render_strategy_report(strategy: DeckStrategy) -> str:
    """Pretty one-liner for the pipeline log."""
    return (
        f"    Profile: {strategy.profile.value} · density: {strategy.density.value} · "
        f"one-per-slide: {strategy.one_item_per_slide} · "
        f"theory-target: {strategy.target_bullets_per_theory_slide} bullets · "
        f"style: {strategy.bullet_style}\n"
        f"    Rationale: {strategy.rationale}"
    )
