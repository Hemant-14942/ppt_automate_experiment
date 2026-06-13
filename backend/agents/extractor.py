import asyncio
import base64
from google.genai import types
from agents.gemini_client import client
from schemas.extracted_page import ExtractedPage
from schemas.request import PDFContext
from config import (
    EXTRACTION_MODEL,
    EXTRACTION_RETRY_MODEL,
    MAX_CONCURRENT_AGENTS,
    MAX_EXTRACTION_RETRIES,
    MAX_EXTRACTION_OUTPUT_TOKENS,
)
from pipeline.token_tracker import record_api_attempt, record_api_failure, record_usage


# Substrings that mark a TRANSIENT (worth-retrying) failure: rate limits,
# server hiccups, timeouts. Anything else (bad request, parse error) is not
# retried — retrying would just waste an API call.
_TRANSIENT_MARKERS = (
    "429", "resource_exhausted", "rate limit", "quota",
    "503", "500", "unavailable", "deadline", "timeout", "servererror",
)


def _is_transient(err: Exception) -> bool:
    """True if the error looks transient and a retry might succeed."""
    blob = f"{type(err).__name__} {err!r}".lower()
    return any(m in blob for m in _TRANSIENT_MARKERS)


def _log_extraction_failure(page_no: int, err: Exception | None, response) -> None:
    """
    Print the REAL reason a page failed — never a blank line.

    Shows the exception type + repr AND Gemini's own finish_reason /
    prompt_feedback, which is what distinguishes a rate limit (429) from a
    truncated dense page (MAX_TOKENS) from a safety block.
    """
    if err is not None:
        print(f"  Page {page_no} — FAILED [{type(err).__name__}]: {err!r}")
    else:
        print(f"  Page {page_no} — FAILED: empty/blocked response (nothing to parse)")

    if response is not None:
        fb = getattr(response, "prompt_feedback", None)
        if fb:
            print(f"      prompt_feedback: {fb}")
        for cand in (getattr(response, "candidates", None) or []):
            fr = getattr(cand, "finish_reason", None)
            if fr is not None:
                print(f"      finish_reason: {fr}")


def build_extraction_prompt(context: PDFContext, feedback: str | None = None) -> str:
    """Build extraction prompt. Annotation meanings from the instructor are injected here.

    `feedback` (interactive mode): when the user reviewed a page's extraction and
    asked for a correction (e.g. "Q15 text is wrong, you missed Q16"), we inject
    that instruction at the TOP so the model fixes exactly what they flagged on
    the SAME page image.
    """

    annotation_rules = []
    for ann in context.annotations:
        if ann.selected:
            name = ann.customName if ann.type == "other" and ann.customName else ann.label
            reason = ann.reason if ann.reason else "emphasize this on the slide"
            annotation_rules.append(f"- {ann.type} ({name}) means: {reason}")

    if not annotation_rules:
        annotation_rules = [
            "- circle / highlight = emphasize this on the slide",
            "- tick = include this as a key point",
            "- handwritten = treat as an instructor note",
        ]

    annotations_text = "\n".join(annotation_rules)

    feedback_block = ""
    if feedback and feedback.strip():
        feedback_block = f"""
═════════════════════════════════════════════════════════════════════════════
⚠️ USER CORRECTION — HIGHEST PRIORITY (re-extraction request)
═════════════════════════════════════════════════════════════════════════════
A human reviewed your previous extraction of THIS page and asked you to fix it:

  "{feedback.strip()}"

Re-read the page image carefully and produce a CORRECTED extraction that
addresses this feedback exactly. Keep everything else that was already correct.
Do not drop content the user did not ask you to remove.

"""

    return f"""
You are analysing ONE page of a teaching document. A downstream planner will
turn your output into PowerPoint slides, so your output must be COMPLETE and
PRECISE — not a summary.
{feedback_block}

Subject     : {context.subject}
Purpose     : {context.purpose}
Class level : {context.class_level}
Language    : {context.language}

═════════════════════════════════════════════════════════════════════════════
TASK 1 — Extract ALL textual content into `main_text`
═════════════════════════════════════════════════════════════════════════════

VERBATIM TRANSCRIPTION — ABSOLUTE RULE:
  Your ONLY job is faithful transcription. You are NOT allowed to:
    ✗ Paraphrase, reword, simplify, or "improve" any text
    ✗ Summarise or shorten any question, option, formula, or theorem
    ✗ Change any number, value, unit, symbol, or punctuation
    ✗ Fix grammar, spelling, or notation errors — if the source has a typo,
      keep the typo exactly as printed
    ✗ Translate or convert between languages/scripts
  A student will compare the extracted text against the original PDF.
  Any difference — even a single changed word — is an extraction error.

• Preserve EVERY question, every option, every definition, every formula,
  every paragraph of theory verbatim. Do NOT paraphrase, do NOT summarise,
  do NOT drop anything.
• Keep the natural READING ORDER. If the page is in two columns, read the
  LEFT column top-to-bottom first, then the RIGHT column top-to-bottom.
  Do not interleave columns.
• For MCQ-style content, keep the question stem, the exam tag (if any),
  and all four options together as a single chunk in the order they appear.
  Use clean newlines between question number, stem, exam tag, and options
  so the planner can split them later. Example shape:

      Q.661. A large number of fish swimming together
      SSC CPO Tier-II (27/09/2019)
      (a) herd  (b) shoal  (c) brood  (d) cache

• For numbered problems (e.g. "1. The sum of two numbers is 50…"),
  preserve the EXACT wording — including the question number, every clause,
  every given value, and every asked quantity. Do not merge, shorten, or
  split questions unless they are genuinely separate.
• If the page has solutions / explanations / answer keys, include them too
  but clearly after a `Solutions:-` marker so the planner can identify them.
• Ignore obvious noise: page numbers, app-promo footers ("Download …"),
  watermarks, and any text that's clearly bleed-through from an adjacent
  page or column.

LANGUAGE / SCRIPT PRESERVATION (critical):
  • Transcribe text in the EXACT language and script shown on the page.
    If the page is in Hindi (Devanagari), keep it in Devanagari. If it mixes
    Hindi and English, keep BOTH exactly as written — do NOT translate,
    transliterate, or "normalise" one into the other.
  • NEVER translate Hindi → English or English → Hindi during extraction.
    Your job is faithful transcription, not translation. A downstream agent
    decides the output language; you must preserve the original verbatim.
  • Set `detected_language` to "hi" if the page is mostly Hindi/Devanagari,
    "en" if mostly English/Latin, or "mixed" if it contains a meaningful
    amount of both.

CURRENCY / SYMBOL ORDERING (critical):
  Currency symbols (₹, $, €, £) ALWAYS go BEFORE the number:
    ✓  ₹25 Crore      ✓  ₹71.375 Crore     ✓  $5,000
    ✗  25 Crore ₹     ✗  71.375 Crore ₹     ✗  5,000 $
  Even if the PDF renders them in a weird position (due to text boxes / RTL
  quirks), ALWAYS output them in the correct natural order: SYMBOL + NUMBER.

CONTROL CHARACTERS:
  NEVER output raw control character escapes like _x000D_, _x0008_, etc.
  These are Word XML artefacts — silently drop them. Write clean text only.

═════════════════════════════════════════════════════════════════════════════
TASK 2 — Detect TABLES
═════════════════════════════════════════════════════════════════════════════

If the page contains a visual TABLE (a grid of rows × columns — discount
factor tables, comparison charts, score grids, schedules, financial data),
you MUST:
  • Set `has_table = true`
  • Set `content_type = "table"` (or "mixed" if the page also has
    substantial non-table text like theory paragraphs around the table)
  • Set `table_description` to a short description: e.g.
    "PV discount factors table: 5 columns (Year, 15%, 14%, 13%, 12%),
     5 rows (Year 1-4 + PVAF)"
  • ALSO include the table data in `main_text` as a plaintext rendering:
    "Year | 15% | 14% | 13% | 12%\n1 | 0.870 | 0.877 | 0.885 | 0.893\n..."
    Use " | " pipe separators between columns and newlines between rows.

This is CRITICAL: tables turned into prose bullets ("the factors are 0.869,
0.877…") become unreadable. The planner MUST know a table exists so it can
use `table_slide` and preserve the grid structure.

═════════════════════════════════════════════════════════════════════════════
TASK 3 — Identify EVERY SINGLE visual annotation (CRITICAL — DO NOT MISS ANY)
═════════════════════════════════════════════════════════════════════════════

Annotation interpretation rules provided by the instructor:
{annotations_text}

Rules for the `annotations` list you return:
• For EACH visible mark on the page produce ONE annotation entry.
• `target` must precisely identify WHAT is marked:
    - If a question number is circled / boxed, set target to that number
      with its prefix, e.g. "Q.661" or "30" or "Q.6". Be exact.
    - If a tick / check mark is beside a question, set target to the NEAREST
      exact question number and/or stem, NOT the exercise heading. Example:
      use "1. The sum of two numbers is 50..." rather than "Exercise 6".
      This lets the UI show the exact PPT-selected question after extraction.
    - If an option is underlined (likely the correct answer), set target to
      "option (b) of Q.661" or similar.
    - If an exam tag is struck-through, set target to the exam tag text.
• `instruction` is the meaning of the mark in this context. Use the
  instructor's reason VERBATIM when it applies (e.g. copy "INCLUDE this
  question on a dedicated slide" exactly so the planner can pattern-match).
• Do NOT invent annotations that aren't visible.
• Do NOT skip annotations because they are repetitive — if 16 question
  numbers are circled, return 16 annotation entries (one per circle).
• COMMON MISTAKE: returning only 5-8 annotations when there are actually
  15-20+ marks on the page. Carefully scan the ENTIRE page from top to
  bottom. Count every circle, every tick, every highlight. If you see a
  pattern (e.g. many question numbers circled), make sure you catch ALL
  of them, not just the first few.
• When in doubt, include it. Missing an annotation is worse than including
  a borderline one.

═════════════════════════════════════════════════════════════════════════════
Skip rule
═════════════════════════════════════════════════════════════════════════════

Set `should_skip = true` ONLY when the page is genuinely useless:
a blank page, a pure cover/title page, an advert, or a table of contents
with no teaching content. A page with even ONE MCQ or ONE definition is
NOT skippable.
"""


# ── ASYNC — all pages in parallel ────────────────────────────────────────────

async def _extract_page_async(
    page_dict: dict,
    context: PDFContext,
    semaphore: asyncio.Semaphore,
    feedback: str | None = None,
    keep_skipped: bool = False,
) -> ExtractedPage | None:
    """
    Async: one page → Gemini Vision → ExtractedPage.
    Semaphore limits concurrent calls to stay within Gemini rate limits.

    `feedback` (interactive re-extraction) is injected into the prompt so the
    model corrects exactly what the user flagged for this page.
    """
    async with semaphore:
        page_no = page_dict["page_number"]
        prompt = build_extraction_prompt(context, feedback=feedback)
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExtractedPage,
            max_output_tokens=MAX_EXTRACTION_OUTPUT_TOKENS,
        )
        contents = [
            prompt,
            types.Part.from_bytes(
                data=base64.b64decode(page_dict["base64"]),
                mime_type=page_dict["mime_type"],
            ),
        ]

        # 1 initial attempt + at most MAX_EXTRACTION_RETRIES retries, but ONLY
        # for transient errors (rate limit / server / timeout). A retry uses one
        # more API call, so it's also reflected in the final cost summary.
        response = None
        for attempt in range(MAX_EXTRACTION_RETRIES + 1):
            model = EXTRACTION_RETRY_MODEL if attempt > 0 else EXTRACTION_MODEL
            try:
                record_api_attempt("extraction", model)
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                break
            except Exception as e:
                record_api_failure("extraction", model)
                if attempt < MAX_EXTRACTION_RETRIES and _is_transient(e):
                    wait = 2.0 * (attempt + 1)
                    print(f"  Page {page_no} — transient error [{type(e).__name__}], "
                          f"retry {attempt + 1}/{MAX_EXTRACTION_RETRIES} "
                          f"with {EXTRACTION_RETRY_MODEL} in {wait:.0f}s")
                    await asyncio.sleep(wait)
                    continue
                # Out of retries (or non-transient): log the REAL reason.
                _log_extraction_failure(page_no, e, None)
                return None

        # Record token usage for EVERY response we received — even one that
        # later fails to parse still consumed (billable) tokens, so it must
        # show up in the terminal cost / API-call summary.
        if response is not None:
            record_usage("extraction", response.usage_metadata, model=model)

        extracted = response.parsed if response is not None else None
        if extracted is None:
            # Truncated (MAX_TOKENS), blocked, or otherwise unparseable — the
            # finish_reason printed here tells us which.
            _log_extraction_failure(page_no, None, response)
            return None

        # trust our page numbering, not Gemini's
        extracted.page_number = page_no

        if extracted.should_skip and not keep_skipped:
            print(f"  Page {page_no} — skipped (blank/irrelevant)")
            return None

        print(f"  Page {page_no} — extracted OK")
        return extracted


async def extract_all_pages_async(
    pages: list[dict],
    context: PDFContext,
) -> list[ExtractedPage]:
    """
    Extract ALL pages in PARALLEL.

    Speed comparison on a 50-page PDF:
      Sequential (old): 50 × ~2s = ~100 seconds
      Parallel   (new): ceil(50/10) × ~2s = ~10 seconds

    Uses asyncio.Semaphore to cap concurrent calls at MAX_CONCURRENT_AGENTS.
    """
    sem = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)
    print(f"  Extracting {len(pages)} pages in parallel (max {MAX_CONCURRENT_AGENTS} at once)...")

    tasks = [_extract_page_async(page, context, sem) for page in pages]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    extracted = []
    errored = 0
    for i, result in enumerate(raw_results):
        if isinstance(result, Exception):
            errored += 1
            print(f"  Page {pages[i]['page_number']} — error "
                  f"[{type(result).__name__}]: {result!r}")
        elif result is not None:
            extracted.append(result)

    # sort by page number — parallel calls return out of order
    extracted.sort(key=lambda p: p.page_number)

    dropped = len(pages) - len(extracted)
    print(f"\n  Extraction done — {len(extracted)} useful pages from {len(pages)} total")
    if dropped:
        # Skipped (blank) pages are expected; errored pages are real losses.
        print(f"  ⚠ {dropped} page(s) not extracted "
              f"({errored} hard error(s); rest skipped as blank/irrelevant)")
    return extracted


async def extract_single_page_async(
    page_dict: dict,
    context: PDFContext,
    feedback: str | None = None,
) -> ExtractedPage | None:
    """
    Interactive mode — extract ONE page on demand.

    Used by the per-page review UI: the first pass and every "re-extract with
    feedback" click route through here. Unlike the batch path, a page the model
    marks should_skip is still RETURNED (keep_skipped=True) so the user — not the
    model — decides whether to drop it.
    """
    sem = asyncio.Semaphore(1)
    return await _extract_page_async(
        page_dict, context, sem, feedback=feedback, keep_skipped=True
    )


# ── SYNC fallback ─────────────────────────────────────────────────────────────

def extract_page(page_dict: dict, context: PDFContext) -> ExtractedPage | None:
    """Sync single-page extraction — kept as fallback."""
    page_no = page_dict["page_number"]
    prompt = build_extraction_prompt(context)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ExtractedPage,
        max_output_tokens=MAX_EXTRACTION_OUTPUT_TOKENS,
    )
    response = None
    try:
        record_api_attempt("extraction", EXTRACTION_MODEL)
        response = client.models.generate_content(
            model=EXTRACTION_MODEL,
            contents=[
                prompt,
                types.Part.from_bytes(
                    data=base64.b64decode(page_dict["base64"]),
                    mime_type=page_dict["mime_type"]
                )
            ],
            config=config
        )
        record_usage("extraction", response.usage_metadata, model=EXTRACTION_MODEL)
    except Exception as e:
        record_api_failure("extraction", EXTRACTION_MODEL)
        _log_extraction_failure(page_no, e, None)
        return None

    extracted = response.parsed
    if extracted is None:
        _log_extraction_failure(page_no, None, response)
        return None

    extracted.page_number = page_no
    if extracted.should_skip:
        print(f"  Page {page_no} — skipped")
        return None
    return extracted


def extract_all_pages(pages: list[dict], context: PDFContext) -> list[ExtractedPage]:
    """Sync sequential extraction — fallback only, not used in main pipeline."""
    extracted_pages = []
    for page in pages:
        print(f"  Extracting page {page['page_number']} of {len(pages)}...")
        result = extract_page(page, context)
        if result is not None:
            extracted_pages.append(result)
    print(f"\n  Extraction done — {len(extracted_pages)} useful pages from {len(pages)} total")
    return extracted_pages
