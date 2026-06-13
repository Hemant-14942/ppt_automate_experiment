"""
Visual Critic Agent

After the writer + generator have produced a .pptx, this agent:
  1. Renders the pptx to PDF (via LibreOffice — already wired)
  2. Splits each PDF page into a PNG image (via PyMuPDF)
  3. Sends each image + the slide's intended layout/content to Gemini Vision
  4. Receives a structured critique: score, issues, retry recommendation

The orchestrator uses these critiques to decide which slides to rewrite, and
passes the `content_fix_hint` back into the writer's prompt for round 2.

Why this matters: a human looking at the deck can immediately tell when a slide
is broken (text overflow, wrong layout, misaligned options). Without a visual
critic, the pipeline is blind to its own output — it can only check rules on
text, never on the rendered result.
"""

import asyncio
import json
from google.genai import types

from agents.gemini_client import client
from schemas.slide_content import SlideContent
from schemas.critic_report import SlideCritique
from pipeline.pptx_to_pdf import convert_pptx_to_pdf
from pipeline.pdf_loader import pdf_pages_to_png_bytes
from config import SLIDE_CRITIC_MODEL, MAX_CONCURRENT_AGENTS, PDF_DPI
from pipeline.token_tracker import record_api_attempt, record_api_failure, record_usage


# ──────────────────────────────────────────────────────────────────────────
# Prompt
# ──────────────────────────────────────────────────────────────────────────

def _critique_prompt(content: SlideContent) -> str:
    """Per-slide critique instructions."""
    bullets_str = json.dumps(content.bullets[:6], ensure_ascii=False)
    return f"""You are a strict but FAIR visual QA reviewer for a teaching slide.

CONTEXT
The slide canvas is large (40 × 22.5 inches) — wide whitespace and
decorative graphics are INTENTIONAL design choices, NOT issues.
The deck uses a Physics-Wallah style template with a dark background,
orange/yellow headings, and small decorative pictures.

What the slide was supposed to be:
  layout  : {content.layout.value}
  title   : "{content.title[:200]}"
  bullets : {bullets_str}

YOUR JOB — be conservative. Only flag REAL problems a student would notice.

1. overall_score (1-10):
   • 10 = perfect, ready to publish
   • 7-9 = minor cosmetic only (do NOT retry)
   • 4-6 = noticeable issue but slide is still readable
   • 1-3 = badly broken: content unreadable, placeholders showing, etc.

2. List ONLY genuinely visible defects. Acceptable issue types:
   - text_overflow         : text actually clipped at the slide boundary
   - misalignment          : letter (A/B/C/D) and its option clearly not aligned
   - wrong_layout          : the layout is totally unsuitable for the content
   - missing_content       : a literal placeholder "Type option here" /
                             "Type question here" / "Type Heading Here"
                             is still visible
   - off_screen            : an element extends outside the slide
   - letter_option_mismatch: visual A,B,C,D order does NOT match the
                             bulleted option order above
   - decorative_overlap    : a decoration covers actual content text

3. DO NOT flag:
   - whitespace, padding, margins
   - "could be more colourful" / "looks plain"
   - any subjective styling preference
   - bullet count being smaller than the deck average
   - the slide having only a heading (section_heading / thank_you / title slides are SUPPOSED to be sparse)
   - the title slide having subtitle (subject · batch) and metadata
     (purpose · class · language) below the heading — these are INTENTIONAL
   - the small italic context footer at bottom of body slides
     (e.g. "Subject · Batch · Purpose") — INTENTIONAL
   - a decorative graphic (small logo / picture) overlapping the edge of a
     heading banner — that is the template design

4. should_retry — BE VERY CONSERVATIVE:
   • true ONLY if ALL of the following are true:
       (a) overall_score ≤ 3 (i.e. the slide is genuinely broken)
       (b) at least one HIGH severity defect exists from list (2)
       (c) the defect is fixable by rewriting CONTENT
           (e.g. a shorter title, fewer bullets, or a different layout)
   • false for every cosmetic, subjective, or "medium" severity case.
   • REMEMBER: the slide canvas is 40×22.5 inches; lots of empty space at
     the bottom of the slide is NORMAL, never flag it.

5. If retry=true, give a SINGLE one-line content_fix_hint the writer can act on
   (e.g. "shorten the title to ≤ 6 words", "use single-word options",
   "change layout to mcq_slide for long options"). Otherwise null.

6. suggested_layout: only fill if you'd recommend a different template.
   Must be one of: title_slide, recap_slide, topics_slide, section_heading,
   theory_slide, mcq_slide, mcq_grid_slide, question_only, pyq_slide,
   pyq_grid_slide, pyq_question_only, summary, homework_slide, thank_you_slide.

Always set slide_number = {content.slide_number}.
Return JSON only.
"""


# ──────────────────────────────────────────────────────────────────────────
# Per-slide critique
# ──────────────────────────────────────────────────────────────────────────

async def _critique_one(
    image_png: bytes,
    content: SlideContent,
    semaphore: asyncio.Semaphore,
) -> SlideCritique:
    """Send one slide image to Gemini Vision and parse the critique."""
    async with semaphore:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SlideCritique,
        )
        response = None
        try:
            record_api_attempt("critics", SLIDE_CRITIC_MODEL)
            response = await client.aio.models.generate_content(
                model=SLIDE_CRITIC_MODEL,
                contents=[
                    _critique_prompt(content),
                    types.Part.from_bytes(data=image_png, mime_type="image/png"),
                ],
                config=config,
            )
            record_usage("critics", response.usage_metadata, model=SLIDE_CRITIC_MODEL)
            critique = response.parsed
            critique.slide_number = content.slide_number   # trust our numbering
            return critique
        except Exception as e:
            if response is None:
                record_api_failure("critics", SLIDE_CRITIC_MODEL)
            # Fail open — assume slide is fine; we don't want a critic glitch
            # to block the pipeline.
            print(f"  Visual critic — slide {content.slide_number} skipped ({e})")
            return SlideCritique(
                slide_number=content.slide_number,
                overall_score=7,
                issues=[],
                should_retry=False,
            )


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────

def _merge_critiques(
    previous: list[SlideCritique] | None,
    fresh: list[SlideCritique],
) -> list[SlideCritique]:
    """Replace critiques for re-checked slides; keep scores for unchanged ones."""
    by_num = {c.slide_number: c for c in (previous or [])}
    for c in fresh:
        by_num[c.slide_number] = c
    return [by_num[n] for n in sorted(by_num)]


async def _critique_slide_batch(
    pptx_path: str,
    contents: list[SlideContent],
    slide_numbers: list[int],
) -> list[SlideCritique]:
    """Render + vision-critique a subset of slides (slide_number is 1-based)."""
    content_by_num = {c.slide_number: c for c in contents}
    ordered = [n for n in slide_numbers if n in content_by_num]
    if not ordered:
        return []

    pdf_path = convert_pptx_to_pdf(pptx_path)
    page_indices = [n - 1 for n in ordered]
    images = pdf_pages_to_png_bytes(pdf_path, dpi=PDF_DPI, page_indices=page_indices)

    if len(images) != len(ordered):
        print(
            f"  Visual critic — PNG count ({len(images)}) != requested slides "
            f"({len(ordered)}); zipping by min length"
        )

    n = min(len(images), len(ordered))
    sem = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)
    tasks = [
        _critique_one(images[i], content_by_num[ordered[i]], sem)
        for i in range(n)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    out: list[SlideCritique] = []
    for i, r in enumerate(results):
        sn = ordered[i]
        if isinstance(r, Exception):
            print(f"  Visual critic — slide {sn} errored: {r}")
            out.append(SlideCritique(
                slide_number=sn,
                overall_score=7,
                issues=[],
                should_retry=False,
            ))
        else:
            out.append(r)
    return out


async def critique_slides_visually(
    pptx_path: str,
    contents: list[SlideContent],
    slide_numbers: list[int],
    previous_critiques: list[SlideCritique] | None = None,
) -> list[SlideCritique]:
    """
    Critique only the given slide numbers and merge with any prior results.
    Slides that already passed and were not rewritten are left untouched.
    """
    if not slide_numbers:
        return list(previous_critiques or [])

    is_partial = bool(previous_critiques)
    if is_partial:
        print(
            f"  Visual critic — re-checking {len(slide_numbers)} slide(s): "
            f"{sorted(slide_numbers)}"
        )
    else:
        print(f"  Visual critic — rendering {pptx_path} to PNGs...")

    fresh = await _critique_slide_batch(pptx_path, contents, slide_numbers)
    print(f"  Visual critic — analysed {len(fresh)} slide(s)")
    return _merge_critiques(previous_critiques, fresh)


async def critique_deck_visually(
    pptx_path: str,
    contents: list[SlideContent],
) -> list[SlideCritique]:
    """
    First-pass full-deck visual QA — every slide is rendered and critiqued.
    """
    slide_numbers = [c.slide_number for c in contents]
    return await critique_slides_visually(
        pptx_path, contents, slide_numbers, previous_critiques=None
    )


def render_critique_report(critiques: list[SlideCritique]) -> str:
    """Pretty one-line-per-slide log for the pipeline output."""
    lines = []
    for c in critiques:
        flag = "↻ retry" if c.should_retry else "  ok   "
        issues_str = (
            "; ".join(f"{i.type}({i.severity})" for i in c.issues)
            if c.issues else "—"
        )
        lines.append(
            f"    Slide {c.slide_number:2d}  score {c.overall_score}/10  {flag}  "
            f"{issues_str}"
        )
        if c.should_retry and c.content_fix_hint:
            lines.append(f"        hint → {c.content_fix_hint}")
    return "\n".join(lines)
