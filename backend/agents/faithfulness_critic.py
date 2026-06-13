"""
Faithfulness Critic Agent

After the Writer fills each slide with content, this agent runs in parallel
across all slides and asks Gemini: "Does every bullet / claim on this slide
actually appear in the source PDF pages this slide was drawn from?"

It returns a per-slide verdict that the orchestrator uses to:
  - SILENTLY STRIP a couple of fabricated bullets, OR
  - REQUEST A REWRITE for a heavily hallucinated slide

This is purely a text-on-text agent (no images) so it's fast and cheap.

Layouts where bullets are not the main content (title_slide, thank_you,
section_heading, question_only) are skipped — there's nothing to fact-check.
"""

import asyncio
import json
from google.genai import types

from agents.gemini_client import client
from schemas.slide_content   import SlideContent
from schemas.slide_plan      import TemplateType
from schemas.extracted_page  import ExtractedPage
from schemas.faithfulness    import FaithfulnessReport, BulletVerdict
from config import (
    SLIDE_CRITIC_MODEL,
    FAITHFULNESS_PROGRESS_EVERY,
    FAITHFULNESS_TIMEOUT_SECONDS,
    MAX_CONCURRENT_AGENTS,
)
from pipeline.token_tracker import record_api_attempt, record_api_failure, record_usage


# Layouts where there's nothing meaningful to fact-check
_SKIP_LAYOUTS = {
    TemplateType.title_slide,
    TemplateType.thank_you_slide,
    TemplateType.section_heading,
    TemplateType.question_only,
    TemplateType.pyq_question_only,
    # passage_slide is a VERBATIM copy of the source passage (blanks intact) —
    # by definition faithful, and stripping/rewriting would damage the cloze.
    TemplateType.passage_slide,
    # table_slide has no bullets to fact-check (its truth is in table_data,
    # which we trust the writer to extract verbatim from the source image).
    # theory_table_slide has only 2-3 framing bullets that the renderer already
    # bounds tightly — skipping keeps the critic from forcing rewrites that
    # would drift the table caption.
    TemplateType.table_slide,
    TemplateType.theory_table_slide,
}


# ──────────────────────────────────────────────────────────────────────────
# Prompt
# ──────────────────────────────────────────────────────────────────────────

def _build_prompt(slide: SlideContent, sources: list[ExtractedPage]) -> str:
    """Per-slide faithfulness check prompt."""
    src_dump = []
    for p in sources:
        src_dump.append({
            "page":         p.page_number,
            "main_text":    (p.main_text or "").strip(),
            "diagrams":     (p.diagrams_described or "").strip(),
            "instructor":   (p.instructor_notes or "").strip(),
        })

    bullets_dump = [
        {"index": i, "text": b}
        for i, b in enumerate(slide.bullets)
    ]

    return f"""You are a strict but FAIR fact-checking editor for a teaching
slide. Your job is to confirm that the slide does NOT contain INVENTED
specifics — names, dates, numbers, attribution — that aren't in the source.

Slide #{slide.slide_number} — layout: {slide.layout.value}
  title:         "{slide.title}"
  bullets:       {json.dumps(bullets_dump, ensure_ascii=False)}
  speaker_notes: "{slide.speaker_notes[:600]}"

Source pages this slide was drawn from:
{json.dumps(src_dump, indent=2, ensure_ascii=False)}

CLASSIFICATION — for title, EACH bullet, and speaker_notes pick one:
  • "supported"   — text is present in / directly derived from the source
  • "paraphrased" — faithful reword of source, OR a generic pedagogical
                    extension (everyday example, "let's now learn...",
                    real-world analogy) that DOES NOT contradict source
  • "unsupported" — text states a SPECIFIC fact (name, date, number,
                    attribution, formula) that is NOT in the source
  • "contradicts" — text directly contradicts the source

CRITICAL GUIDANCE — read carefully:
  1. Speaker notes are allowed to ADD pedagogical context (real-world
     examples, analogies, "this is why we feel a jerk in a bus")
     PROVIDED they do not contradict the source. Mark as "paraphrased",
     NOT "unsupported".
  2. Section labels / titles can rephrase source headings.
  3. For MCQ slides, the FOUR OPTIONS must match source options exactly
     in meaning. The CORRECT answer in speaker_notes must match source.
     Wrong answer in speaker_notes = "contradicts".
  4. A made-up SPECIFIC like "Galileo proposed F=ma in 1604" when the
     source says nothing about it = "unsupported" or "contradicts".
  5. General glue like "Let us begin", "We will study" → paraphrased.

DECIDE fix_action — BE CONSERVATIVE:
  - "ok"             : zero "contradicts" AND zero or one "unsupported"
                       across the whole slide.
  - "strip_bullets"  : 1-2 BULLETS are unsupported / contradicts AND the
                       title is fine. The orchestrator will drop those
                       bullets.
  - "rewrite"        : ≥3 unsupported, OR the TITLE contradicts source,
                       OR the speaker_notes for an MCQ slide states the
                       WRONG answer (contradicts source).

A clean slide (title + bullets + notes all 'supported' or 'paraphrased')
MUST get fix_action = "ok". Do not retry healthy slides.

If fix_action = "rewrite", give a SINGLE one-line fix_hint, e.g.
"Remove the Galileo-1604 attribution; F=ma is Newton's law per source."

Always set slide_number = {slide.slide_number}.
Return JSON only.
"""


# ──────────────────────────────────────────────────────────────────────────
# Per-slide check
# ──────────────────────────────────────────────────────────────────────────

async def _check_one(
    slide:   SlideContent,
    sources: list[ExtractedPage],
    semaphore: asyncio.Semaphore,
) -> FaithfulnessReport:
    """Run the critic for ONE slide."""
    if slide.layout in _SKIP_LAYOUTS:
        return FaithfulnessReport(
            slide_number=slide.slide_number,
            bullet_verdicts=[],
            title_status="supported",
            speaker_notes_status="supported",
            fix_action="ok",
        )
    if not sources:
        # No source pages to fact-check against — leave the slide alone.
        return FaithfulnessReport(
            slide_number=slide.slide_number,
            bullet_verdicts=[],
            title_status="supported",
            speaker_notes_status="supported",
            fix_action="ok",
        )

    async with semaphore:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=FaithfulnessReport,
        )
        response = None
        try:
            record_api_attempt("critics", SLIDE_CRITIC_MODEL)
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=SLIDE_CRITIC_MODEL,
                    contents=_build_prompt(slide, sources),
                    config=config,
                ),
                timeout=FAITHFULNESS_TIMEOUT_SECONDS,
            )
            record_usage("critics", response.usage_metadata, model=SLIDE_CRITIC_MODEL)
            report = response.parsed
            report.slide_number = slide.slide_number   # trust our numbering
            return report
        except Exception as e:
            if response is None:
                record_api_failure("critics", SLIDE_CRITIC_MODEL)
            print(f"  Faithfulness — slide {slide.slide_number} skipped "
                  f"[{type(e).__name__}]: {e!r}")
            return FaithfulnessReport(
                slide_number=slide.slide_number,
                bullet_verdicts=[],
                title_status="supported",
                speaker_notes_status="supported",
                fix_action="ok",
            )


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────

async def check_faithfulness(
    contents: list[SlideContent],
    slide_plan,            # FullSlidePlan — needed for source_pages mapping
    extracted_pages: list[ExtractedPage],
) -> list[FaithfulnessReport]:
    """Parallel fact-check of every slide. Returns one report per slide."""
    page_by_num = {p.page_number: p for p in extracted_pages}
    sources_by_slide = {
        s.slide_number: [
            page_by_num[pg] for pg in s.source_pages if pg in page_by_num
        ]
        for s in slide_plan.slides
    }

    sem = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)

    async def _run_one(idx: int, content: SlideContent):
        return idx, await _check_one(
            content, sources_by_slide.get(content.slide_number, []), sem
        )

    tasks = [
        asyncio.create_task(_run_one(i, c))
        for i, c in enumerate(contents)
    ]
    total = len(tasks)
    print(f"  Faithfulness critic — checking {total} slides in parallel "
          f"(max {MAX_CONCURRENT_AGENTS}, timeout {FAITHFULNESS_TIMEOUT_SECONDS}s)...")

    out: list[FaithfulnessReport] = []
    done = 0
    for task in asyncio.as_completed(tasks):
        done += 1
        try:
            i, r = await task
        except Exception as e:
            # Hard fallback — should be rare because _check_one fail-opens.
            i = min(done - 1, len(contents) - 1)
            print(f"  Faithfulness — slide {contents[i].slide_number} errored "
                  f"[{type(e).__name__}]: {e!r}")
            out.append(FaithfulnessReport(
                slide_number=contents[i].slide_number,
                bullet_verdicts=[],
                title_status="supported",
                speaker_notes_status="supported",
                fix_action="ok",
            ))
        else:
            out.append(r)

        if done == total or done % FAITHFULNESS_PROGRESS_EVERY == 0:
            print(f"  Faithfulness progress — {done}/{total} slides checked")

    out.sort(key=lambda r: r.slide_number)
    return out


def render_faithfulness_report(reports: list[FaithfulnessReport]) -> str:
    """Pretty-print for orchestrator logs."""
    lines = []
    for r in reports:
        if r.fix_action == "ok":
            continue
        flagged = [v for v in r.bullet_verdicts
                   if v.status in ("unsupported", "contradicts")]
        tag = "✂ strip " if r.fix_action == "strip_bullets" else "↻ rewrite"
        lines.append(
            f"    Slide {r.slide_number:2d}  {tag}  "
            f"{len(flagged)} bullet(s) flagged"
        )
        for v in flagged[:4]:
            lines.append(f"        [{v.status}] bullet #{v.bullet_index}"
                         + (f"  ev: {v.evidence[:80]}" if v.evidence else ""))
        if r.fix_action == "rewrite" and r.fix_hint:
            lines.append(f"        hint → {r.fix_hint}")
    return "\n".join(lines) if lines else "    All slides faithful to source."
