"""
Layout Picker Agent

After the Planner produces a draft slide plan, this agent runs per-slide
in parallel. For each slide, it looks at:
  - the planner's chosen layout
  - the actual source-page content the slide draws from
  - a few neighbour slides for flow context

and decides whether the layout is the BEST fit. If a better layout exists
it returns a high-confidence suggestion that the orchestrator applies.

Why this matters: the planner does the whole deck in one LLM call and
often makes layout mistakes at the margins, e.g.:
  - picks `mcq_grid_slide` when options are long sentences
  - picks `mcq_slide` when options are 1-word answers (grid would look better)
  - picks `theory_slide` for a page that is actually a section divider
"""

import asyncio
import json
from google.genai import types

from agents.gemini_client import client
from schemas.extracted_page import ExtractedPage
from schemas.slide_plan   import FullSlidePlan, SlideOutline, TemplateType
from schemas.plan_review  import LayoutSuggestion
from schemas.request      import PDFContext
from config import LAYOUT_MODEL, MAX_CONCURRENT_AGENTS
from pipeline.token_tracker import record_api_attempt, record_api_failure, record_usage


# Slides whose layout is essentially fixed and should NOT be reviewed
# (the planner has structural rules pinning them in place).
_LOCKED_LAYOUTS = {
    TemplateType.title_slide,
    TemplateType.thank_you_slide,
    TemplateType.summary,
}


def _build_picker_prompt(
    slide:    SlideOutline,
    sources:  list[ExtractedPage],
    deck_size: int,
    neighbour_summaries: list[str],
) -> str:
    """Per-slide picker prompt — short, focused, cheap."""
    src_dump = []
    any_table = False
    for p in sources:
        has_table = bool(getattr(p, "has_table", False))
        any_table = any_table or has_table
        src_dump.append({
            "page":              p.page_number,
            "content_type":      p.content_type.value if hasattr(p.content_type, "value") else str(p.content_type),
            # Keep enough text that a table appearing AFTER intro prose is still
            # visible to the picker (tables often sit below a paragraph).
            "main_text":         (p.main_text or "")[:2500],
            "diagrams":          (p.diagrams_described or "")[:200],
            "has_table":         has_table,
            "table_description": getattr(p, "table_description", None) or "",
        })

    table_signal = ""
    if any_table:
        table_signal = (
            "\n⚠️ TABLE SIGNAL: the source page(s) for this slide contain a TABLE "
            "(see has_table / table_description / the ' | ' pipe-delimited rows in "
            "main_text). If THIS slide's title/points are about that tabular data, "
            "you MUST pick table_slide (table only) or theory_table_slide (≤3 "
            "bullets + small table). Do NOT leave it as theory_slide — a prosified "
            "table is unreadable.\n"
        )

    return f"""You are a layout reviewer for a teaching slide deck.
Your job: pick the BEST layout for ONE slide based on its source content.

Slide #{slide.slide_number} of {deck_size}
Planner's choice : {slide.template.value}
Planner's title  : "{slide.title}"
Planner's points : {json.dumps(slide.key_points, ensure_ascii=False)}
{table_signal}
Neighbour slides (for flow context):
{chr(10).join(neighbour_summaries) if neighbour_summaries else "(none)"}

Source page content for THIS slide:
{json.dumps(src_dump, indent=2, ensure_ascii=False)}

Available layouts:
  - theory_slide        : explanation / definitions / formulas (numbered points)
  - table_slide         : page whose primary content is a TABLE (rows × columns of
                          values that would lose meaning if prosified)
  - theory_table_slide  : short theory (≤ 3 bullets) PLUS a small table (≤ 6 rows ×
                          5 cols) that explain each other and fit on one slide
  - mcq_slide           : MCQ with LONG options (full sentences / phrases)
  - mcq_grid_slide      : MCQ with SHORT options (1-3 words / single answer)
  - question_only       : subjective / long-answer Q without 4 options
  - pyq_slide           : MCQ with exam-year tag (long options)
  - pyq_grid_slide      : PYQ MCQ with short options
  - pyq_question_only   : PYQ subjective question
  - section_heading     : a page that is just a topic divider / chapter title
  - recap_slide         : "Recap of previous lecture" content
  - topics_slide        : "Topics to be covered" / agenda content
  - homework_slide      : practice / home-assignment tasks

DECISION RULES:
1. If the source page has a 4-option MCQ:
   • count words in the LONGEST option text;
   • if every option is ≤ 3 words → mcq_grid_slide (or pyq_grid_slide)
   • otherwise                    → mcq_slide      (or pyq_slide)
   • use pyq_* only if the page mentions a year / exam name explicitly.
2. If the page is a subjective question with no options → question_only / pyq_question_only.
3. TABLE HANDLING — judge by what THIS slide is about, not just the page:
   • If this slide's title/points are ABOUT the tabular data (e.g. "Discount
     Factors", "PV Factors", "Comparison Table") AND the source has a table
     (has_table=true or ' | ' rows in main_text):
        - table is the whole point, little/no theory needed → table_slide
        - ≤3 short bullets explain a small table (≤6 rows × 5 cols) → theory_table_slide
     Pick this with HIGH confidence (≥ 0.85) even if the planner said
     theory_slide — a prosified table is unreadable and must be fixed.
   • If this slide is about THEORY/explanation and merely sits on the same page
     as a table that another slide already covers → keep theory_slide.
   • Never downgrade a real table slide back to theory_slide.
4. If the page is mostly definitions, formulas, theory and has NO table → theory_slide.
5. If the page is just a chapter / section title with little content → section_heading.
6. NEVER suggest title_slide, thank_you_slide, or summary here.

OUTPUT:
- suggested_layout : the BEST fit (may equal planner's choice).
- confidence       : 0.0..1.0
   • >= 0.8 = strong, orchestrator will apply
   • 0.5-0.8 = mild, orchestrator may ignore
   • < 0.5  = weak / unsure, do not change
- reason           : one short sentence.

Always set slide_number = {slide.slide_number} and
current_layout = "{slide.template.value}".
Return JSON only.
"""


async def _review_one(
    slide:    SlideOutline,
    sources:  list[ExtractedPage],
    deck_size: int,
    neighbour_summaries: list[str],
    semaphore: asyncio.Semaphore,
) -> LayoutSuggestion:
    """Run the picker for one slide."""
    if slide.template in _LOCKED_LAYOUTS:
        # Skip locked layouts — they're structural.
        return LayoutSuggestion(
            slide_number=slide.slide_number,
            current_layout=slide.template,
            suggested_layout=slide.template,
            confidence=1.0,
            reason="locked structural layout",
        )

    async with semaphore:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=LayoutSuggestion,
        )
        response = None
        try:
            record_api_attempt("critics", LAYOUT_MODEL)
            response = await client.aio.models.generate_content(
                model=LAYOUT_MODEL,
                contents=_build_picker_prompt(
                    slide, sources, deck_size, neighbour_summaries
                ),
                config=config,
            )
            record_usage("critics", response.usage_metadata, model=LAYOUT_MODEL)
            out = response.parsed
            out.slide_number = slide.slide_number
            out.current_layout = slide.template
            return out
        except Exception as e:
            if response is None:
                record_api_failure("critics", LAYOUT_MODEL)
            print(f"  Layout picker — slide {slide.slide_number} skipped ({e})")
            return LayoutSuggestion(
                slide_number=slide.slide_number,
                current_layout=slide.template,
                suggested_layout=slide.template,
                confidence=0.0,
                reason=f"picker failed: {e}",
            )


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────

async def review_layouts(
    plan: FullSlidePlan,
    extracted_pages: list[ExtractedPage],
    context: PDFContext,
) -> list[LayoutSuggestion]:
    """
    Run the layout picker for every slide in parallel.
    Returns suggestions in slide_number order.
    """
    by_num = {p.page_number: p for p in extracted_pages}
    deck_size = plan.total_slides

    # Build short neighbour summaries for context
    def _neighbours(idx: int) -> list[str]:
        out = []
        for off in (-1, 1):
            j = idx + off
            if 0 <= j < len(plan.slides):
                s = plan.slides[j]
                out.append(
                    f"  slide {s.slide_number} [{s.template.value}] — "
                    f"{s.title[:80]}"
                )
        return out

    sem = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)
    tasks = []
    for i, s in enumerate(plan.slides):
        sources = [by_num[pg] for pg in s.source_pages if pg in by_num]
        tasks.append(_review_one(s, sources, deck_size, _neighbours(i), sem))

    print(f"  Layout picker — reviewing {len(tasks)} slides in parallel...")
    results = await asyncio.gather(*tasks, return_exceptions=True)

    out: list[LayoutSuggestion] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            print(f"  Layout picker — slide {i + 1} errored: {r}")
            s = plan.slides[i]
            out.append(LayoutSuggestion(
                slide_number=s.slide_number,
                current_layout=s.template,
                suggested_layout=s.template,
                confidence=0.0,
                reason=f"error: {r}",
            ))
        else:
            out.append(r)
    return out


def render_picker_report(suggestions: list[LayoutSuggestion]) -> str:
    """Pretty-print for orchestrator logs."""
    lines = []
    for s in suggestions:
        if s.suggested_layout != s.current_layout and s.confidence >= 0.5:
            lines.append(
                f"    Slide {s.slide_number:2d}  "
                f"{s.current_layout.value:18s} → {s.suggested_layout.value:18s}  "
                f"conf {s.confidence:.2f}  — {s.reason}"
            )
    return "\n".join(lines) if lines else "    (no layout changes suggested)"
