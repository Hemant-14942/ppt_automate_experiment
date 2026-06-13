"""
Plan Critic Agent

After the planner produces a draft deck, this single agent reviews the WHOLE
deck flow and proposes structural fixes. Unlike the Layout Picker (which
runs per-slide on layout choice), the Plan Critic looks at the macro shape
of the deck — narrative arc, balance, missing dividers, redundancy.

Typical fixes it suggests:
  - Insert a section_heading before a new topic block
  - Drop a duplicate / empty slide
  - Reorder slides for a more logical learning flow
  - Change a layout if the planner mis-grouped content
"""

import json
from google.genai import types

from agents.gemini_client import client
from schemas.extracted_page import ExtractedPage
from schemas.slide_plan   import FullSlidePlan
from schemas.plan_review  import PlanReview
from schemas.request      import PDFContext
from config import PLAN_CRITIC_MODEL
from pipeline.token_tracker import record_api_attempt, record_api_failure, record_usage


def _build_critic_prompt(
    plan: FullSlidePlan,
    extracted_pages: list[ExtractedPage],
    context: PDFContext,
) -> str:
    """One-shot review of the whole plan."""
    plan_dump = [{
        "slide_number":  s.slide_number,
        "title":         s.title,
        "template":      s.template.value,
        "source_pages":  s.source_pages,
        "key_points":    s.key_points,
    } for s in plan.slides]

    # Compact extraction summary — just enough for the critic to see what
    # content exists in the PDF without bloating the prompt.
    pages_summary = [{
        "page": p.page_number,
        "type": p.content_type,
        "text": p.main_text[:200],
    } for p in extracted_pages]

    return f"""You are a senior teaching-presentation editor reviewing a draft
slide plan before content is written. Your job is to spot structural problems
and propose SURGICAL fixes.

Context:
  Subject     : {context.subject}
  Purpose     : {context.purpose}
  Class level : {context.class_level}
  Language    : {context.language}
  Batch       : {context.batch}
  Annotation meanings:
{json.dumps([
    {
        "type": a.type,
        "label": a.label,
        "selected": a.selected,
        "reason": a.reason,
    }
    for a in context.annotations
    if a.selected
], indent=2, ensure_ascii=False)}

Draft slide plan (total {plan.total_slides} slides):
{json.dumps(plan_dump, indent=2, ensure_ascii=False)}

PDF page summaries:
{json.dumps(pages_summary, indent=2, ensure_ascii=False)}

REVIEW CHECKLIST — flag a fix only if you'd genuinely improve the deck:

A. STRUCTURE
   • Do NOT require or insert a title_slide; the design team provides it separately.
   • Do NOT require or insert a summary slide; the generated deck should stay content-only.
   • Last slide must be thank_you_slide.
   • A homework_slide is OPTIONAL — include only if the PDF actually lists
     practice tasks.
   • recap_slide / topics_slide are OPTIONAL — include only when relevant.

B. NARRATIVE FLOW
   • Use section_heading SPARINGLY to separate major topic shifts.
   • NEVER insert a section_heading between two consecutive MCQs of the
     same exercise. Multiple MCQs in a row are FINE.
   • If a long MCQ block follows pure theory, insert ONE heading.

C. LAYOUT BALANCE
   • Two theory_slides covering the SAME concept → suggest merge.
   • A planned section_heading whose content is actually a regular topic
     → change_layout to theory_slide.
   • Empty / duplicate slides → remove_slide.

D. DO NOT
   • Insert headings just to add visual variety.
   • Split a single MCQ across slides.
   • Reorder MCQs from the source PDF — keep their original order.
   • If an annotation meaning says ONLY marked/ticked items should go into
     the PPT, NEVER add slides for unmarked questions.
   • NEVER remove or merge MCQ/PYQ/question slides — each annotated
     question MUST keep its own dedicated slide. The instructor explicitly
     marked these items and their count must not decrease.
   • NEVER reduce the total number of body slides below what the planner
     produced for annotated content.

OUTPUT format (PlanReview):
  overall_ok : true ONLY if NO fixes are needed.
  fixes      : ordered list of PlanFixAction.
               Use only these action_type values:
                 - "change_layout"   (set target_layout)
                 - "insert_heading"  (set title; heading goes BEFORE slide_number)
                 - "remove_slide"
                 - "reorder"         (set target_index — 1-based new position)
                 - "merge_with_next" (use sparingly)
               Each fix must have a 1-line `reason`.
  narrative_note : ONE sentence describing the deck's intended arc.

Be conservative — empty fixes list is a valid (and preferred) answer when the plan is fine.
Return JSON only.
"""


def critique_plan(
    plan: FullSlidePlan,
    extracted_pages: list[ExtractedPage],
    context: PDFContext,
) -> PlanReview:
    """Single Gemini call — full-deck review."""
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=PlanReview,
    )
    response = None
    try:
        record_api_attempt("critics", PLAN_CRITIC_MODEL)
        response = client.models.generate_content(
            model=PLAN_CRITIC_MODEL,
            contents=_build_critic_prompt(plan, extracted_pages, context),
            config=config,
        )
        record_usage("critics", response.usage_metadata, model=PLAN_CRITIC_MODEL)
        review = response.parsed
        return review
    except Exception as e:
        if response is None:
            record_api_failure("critics", PLAN_CRITIC_MODEL)
        print(f"  Plan critic — failed ({e}); skipping review")
        return PlanReview(
            overall_ok=True,
            fixes=[],
            narrative_note="(critic failed — proceeding with original plan)",
        )


def render_review_report(review: PlanReview) -> str:
    """Pretty-print for orchestrator logs."""
    if review.overall_ok and not review.fixes:
        return f"    Plan OK — {review.narrative_note}"
    lines = [f"    Narrative : {review.narrative_note}",
             f"    {len(review.fixes)} fix(es) proposed:"]
    for f in review.fixes:
        line = f"      • {f.action_type:18s} slide {f.slide_number}"
        if f.target_layout:
            line += f" → {f.target_layout.value}"
        if f.target_index:
            line += f" → pos {f.target_index}"
        if f.title:
            line += f"  title=\"{f.title}\""
        line += f"  — {f.reason}"
        lines.append(line)
    return "\n".join(lines)
