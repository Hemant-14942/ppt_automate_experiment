import asyncio
import json
import re
from dataclasses import dataclass
from typing import Optional
from google.genai import types
from agents.gemini_client import client
from schemas.extracted_page import ExtractedPage
from schemas.slide_plan import FullSlidePlan, SlideOutline, TemplateType
from schemas.slide_content import SlideContent
from schemas.request import PDFContext
from config import WRITING_MODEL, MAX_BULLETS, MAX_CONCURRENT_AGENTS
from pipeline.token_tracker import record_api_attempt, record_api_failure, record_usage


# ── AgentPayload — what every writer agent receives ──────────────────────────
#
# This pattern solves the "broken cross-reference" problem:
# Each agent knows what the WHOLE deck looks like (full_outline),
# what came just before its slide (prev_slide_summary),
# and only acts on its own assigned slide (my_slide).
#
# Without full_outline: agent writes "as shown in the diagram above" but
# that diagram lives in another agent's slide — broken reference.
# With full_outline: agent checks context, writes coherently.

@dataclass
class AgentPayload:
    my_slide:            SlideOutline           # the ONE slide this agent generates
    full_outline:        list[SlideOutline]     # entire deck — READ ONLY, for context
    prev_slide_summary:  Optional[str]          # 1-line summary of the slide just before
    style_rules:         dict                   # loaded from memory/style.yaml
    retry_hint:          Optional[str] = None   # feedback from visual critic on retry
    strategy:            object = None          # DeckStrategy from the Profiler (Phase 2)


# ── Payload builder ───────────────────────────────────────────────────────────

def _build_payloads(
    outline: list[SlideOutline],
    style_rules: dict,
    strategy=None,
) -> list[AgentPayload]:
    """Build one AgentPayload per slide. Each payload carries the full outline."""
    payloads = []
    for i, slide in enumerate(outline):
        prev_summary = None
        if i > 0:
            prev = outline[i - 1]
            pts = ", ".join(prev.key_points[:2])
            prev_summary = f"Slide {prev.slide_number} ({prev.title}): {pts}"

        payloads.append(AgentPayload(
            my_slide=slide,
            full_outline=outline,      # same list object shared — not copied
            prev_slide_summary=prev_summary,
            style_rules=style_rules,
            strategy=strategy,
        ))
    return payloads


def _max_bullets_for_layout(layout: TemplateType) -> int:
    if layout in {
        TemplateType.recap_slide,
        TemplateType.topics_slide,
        TemplateType.mcq_slide,
        TemplateType.mcq_grid_slide,
        TemplateType.pyq_slide,
        TemplateType.pyq_grid_slide,
    }:
        return 4
    if layout == TemplateType.table_slide:
        # Table-only slide — no body bullets. Anything the writer puts here
        # is dropped so the renderer can give the full canvas to the table.
        return 0
    if layout == TemplateType.theory_table_slide:
        # Short theory above a compact table. Cap bullets tight so they don't
        # crowd the table out of the bottom half of the slide.
        return 3
    if layout in {
        TemplateType.theory_slide,
        TemplateType.summary,
        TemplateType.homework_slide,
    }:
        # No hard cap — the writer produces as much as the content needs and the
        # fit/reflow engine paginates any overflow into continuation slides.
        return 9999
    return MAX_BULLETS


_THEORY_SUBBULLET_PREFIXES = ("(a)", "(b)", "(c)", "(d)", "(A)", "(B)", "(C)", "(D)")

_MCQ_LAYOUTS = {
    TemplateType.mcq_slide,
    TemplateType.mcq_grid_slide,
    TemplateType.pyq_slide,
    TemplateType.pyq_grid_slide,
}

_TABLE_LAYOUTS = {
    TemplateType.table_slide,
    TemplateType.theory_table_slide,
}


def _recover_table_from_text(source_content: list[dict]):
    """
    Deterministic safety net for table_slide / theory_table_slide.

    The writer LLM sometimes returns a table layout WITHOUT structured
    `table_data` (or drops the table to prose), so the renderer silently falls
    back to a bullets-only theory slide and the table vanishes. When that
    happens we reparse the table straight from the source page text.

    Recognises three delimiters, in order of confidence:
      1. " | " pipes      → "Indian | Western"
      2. TAB separators   → "Indian\tWestern"
      3. runs of 2+ spaces → "Indian Civilization    Western Civilization"

    Returns a TableBlock (headers + rows) or None if nothing table-shaped is
    found. The first consistent row is treated as the header row.
    """
    from collections import Counter
    from schemas.slide_content import TableBlock

    blob = "\n".join((s.get("main_text") or "") for s in source_content)
    if not blob.strip():
        return None

    splitters = (
        lambda s: [c.strip() for c in s.split(" | ")] if " | " in s else None,
        lambda s: [c.strip() for c in s.split("\t")] if "\t" in s else None,
        lambda s: (
            [c.strip() for c in re.split(r"\s{2,}", s.strip())]
            if len(re.split(r"\s{2,}", s.strip())) >= 2
            else None
        ),
    )

    best: Optional[tuple[list[str], list[list[str]]]] = None
    for split in splitters:
        block: list[list[str]] = []
        captured: list[list[str]] = []
        for ln in blob.splitlines():
            cells = split(ln) if ln.strip() else None
            if cells and len(cells) >= 2 and all(c for c in cells):
                block.append(cells)
            else:
                if len(block) > len(captured):
                    captured = block
                block = []
        if len(block) > len(captured):
            captured = block

        # Keep only rows whose width matches the modal (most common) width.
        if len(captured) >= 3:
            ncol = Counter(len(r) for r in captured).most_common(1)[0][0]
            if ncol >= 2:
                kept = [r for r in captured if len(r) == ncol]
                if len(kept) >= 3:
                    best = (kept[0], kept[1:])
                    break  # pipes/tabs are high-confidence; stop at first hit

    if not best:
        return None
    headers, rows = best
    return TableBlock(headers=headers, rows=rows)

# Captures "(a) <text>" option groups, where <text> runs until the next
# "(b)"/"(c)"/… marker or end of string. Handles both inline and multi-line.
_OPTION_PAT = re.compile(
    r"\(?\b([a-dA-D])\b[\)\.]\s*(.+?)(?=\s*\(?\b[a-dA-D]\b[\)\.]|$)",
    re.DOTALL,
)


def _recover_mcq_options(title: str, source_content: list[dict]) -> list[str]:
    """
    Deterministic safety net for MCQ/PYQ slides.

    The writer LLM occasionally returns an MCQ with EMPTY options (the user
    saw "A B C D" with no text). The four options ARE present in the source
    page text, so we parse them directly: locate the question stem, then grab
    the first (a)/(b)/(c)/(d) group that follows it.

    Returns up to 4 option strings (without the "(a)" prefix — the renderer
    strips prefixes anyway), or [] if nothing parseable is found.
    """
    blob = "\n".join((s.get("main_text") or "") for s in source_content)
    if not blob.strip():
        return []

    norm = re.sub(r"[ \t]+", " ", blob)
    # Try to start scanning from the question stem so we grab THIS question's
    # options (a page can hold several MCQs).
    key = re.sub(r"\s+", " ", (title or "")).strip().lower()
    key = re.sub(r"^[0-9]+[\).]\s*", "", key)[:30]
    region = norm
    if key:
        pos = norm.lower().find(key)
        if pos >= 0:
            region = norm[pos:]

    seen: dict[str, str] = {}
    for label, val in _OPTION_PAT.findall(region):
        label = label.lower()
        # Drop any trailing "Answer: ..." / "Ans ..." that follows the option.
        val = re.split(r"\b(?:answer|ans)\b", val, flags=re.IGNORECASE)[0]
        val = " ".join(val.split()).strip(" .;,")
        # Stop if we wandered into the next question (a long sentence ending
        # in '?' that isn't an option value).
        if not val or len(val) > 60:
            continue
        if label not in seen:
            seen[label] = val
        if len(seen) == 4:
            break

    return [seen[l] for l in ("a", "b", "c", "d") if l in seen]


def _normalize_theory_bullets(bullets: list[str]) -> list[str]:
    """
    Tag every theory bullet with the "-> " marker EXCEPT (a)/(b)/(c)/(d)
    sub-bullets — those are detected by the renderer and indented without
    an arrow. The "-> " is a writer-side signal that the renderer strips
    before drawing the visual ➤ arrow.
    """
    normalized = []
    for b in bullets:
        text = b.strip()
        if not text:
            continue
        if text.startswith(_THEORY_SUBBULLET_PREFIXES):
            normalized.append(text)
            continue
        if not text.startswith("-> "):
            text = f"-> {text}"
        normalized.append(text)
    return normalized


# ── Context rules helpers ─────────────────────────────────────────────────────

def _language_rule(context: PDFContext) -> str:
    rules = {
        "Same as source":  "PRESERVE THE SOURCE LANGUAGE EXACTLY. Reproduce each "
                           "point in the SAME language and script as it appears in "
                           "the source — keep Hindi in Devanagari and English in "
                           "Latin. If a sentence mixes Hindi and English, keep it "
                           "mixed exactly as written. Do NOT translate, "
                           "transliterate, or convert one language into the other.",
        "English":         "Write all content in clear English.",
        "Hindi":           "Write all content in Hindi using Devanagari script. "
                           "Keep widely-used English technical terms (formulas, "
                           "proper nouns, units) as-is rather than forcing awkward "
                           "translations.",
        "Hinglish":        "Write in Hinglish — a natural mix of Hindi (Devanagari) "
                           "and English as teachers actually speak, keeping technical "
                           "terms in English.",
        "Regional language": "Write in simple language mixing English technical terms where needed.",
    }
    return rules.get(context.language, "Write in clear English.")


def _language_directive(context: PDFContext) -> str:
    """Short imperative used in the GLOBAL RULES block (avoids 'Write in Same as source')."""
    if context.language == "Same as source":
        return ("Preserve the source language(s) and script(s) verbatim — do NOT "
                "translate Hindi to English or vice-versa.")
    return f"Write in {context.language}."


def _level_rule(context: PDFContext) -> str:
    rules = {
        "Class 1-5":        "Use very simple words. Short sentences. No jargon.",
        "Class 6-8":        "Use simple language. Define technical terms. Give relatable examples.",
        "Class 9-10":       "Use standard academic language. Can use technical terms briefly.",
        "Class 11-12":      "Use proper academic language. Technical terms are fine.",
        "UG / College":     "Use advanced academic language. Assume strong foundation.",
        "Competitive exam": "Be precise and exam-focused. Include tips, shortcuts, common mistakes.",
    }
    return rules.get(context.class_level, "Use clear academic language.")


def _purpose_rule(context: PDFContext) -> str:
    rules = {
        "Revision":     "Be extremely concise. Only key points. No long sentences.",
        "DPP":          "Format as problem statement + key hints. Do not give full solutions.",
        "Formula sheet":"Just the formula, variable definitions, and one usage example.",
        "Quick recap":  "Maximum 3 bullets per slide. Ultra concise.",
        "Lecture notes":"Full explanations. Include examples where helpful.",
    }
    return rules.get(context.purpose, "Balance detail and clarity.")


def _strategy_rule(strategy) -> str:
    """Translate the Profiler's DeckStrategy into writer verbosity guidance."""
    if strategy is None:
        return ""
    density_text = {
        "terse":    "Write SHORT point-form phrases (~8-12 words). Few bullets. No filler.",
        "balanced": "Write clear 1-sentence points (~12-18 words). Moderate detail.",
        "verbose":  "Write thorough 1-2 sentence points (~15-28 words). Cover every "
                    "key idea from the source — the system paginates long slides, "
                    "so favour completeness over brevity.",
    }
    style_text = {
        "phrase":     "bullet_style = phrase (telegraphic).",
        "sentence":   "bullet_style = sentence (one complete idea each).",
        "paragraph":  "bullet_style = paragraph (full, explanatory).",
    }
    d = strategy.density.value if hasattr(strategy.density, "value") else str(strategy.density)
    return (
        "DECK STRATEGY (Profiler) — shapes how much to write:\n"
        f"  - Profile: {strategy.profile.value if hasattr(strategy.profile, 'value') else strategy.profile}\n"
        f"  - {density_text.get(d, density_text['balanced'])}\n"
        f"  - {style_text.get(strategy.bullet_style, style_text['sentence'])}\n"
        f"  - Aim for ~{strategy.target_bullets_per_theory_slide} points on a theory "
        f"slide (overflow auto-paginates — never drop source content to fit)."
    )


# ── Prompt builder — includes full deck context ───────────────────────────────

def _build_agent_prompt(
    payload: AgentPayload,
    source_content: list[dict],
    context: PDFContext
) -> str:
    """
    Build the complete prompt for one slide agent.
    Crucially includes:
    - Full deck outline (so agent writes coherently with the rest)
    - Previous slide summary (prevents broken "as shown above" references)
    - Style rules from memory
    """

    # compact deck overview — agent knows what every other slide covers
    outline_str = "\n".join([
        f"  {s.slide_number}. {s.title} — {', '.join(s.key_points[:2])}"
        + (" [DIAGRAM]" if s.include_diagram else "")
        for s in payload.full_outline
    ])

    # learned rules from style.yaml (flat key-value only)
    style_str = ""
    if payload.style_rules:
        flat = {k: v for k, v in payload.style_rules.items() if not isinstance(v, (list, dict))}
        if flat:
            style_str = "Learned style rules:\n" + "\n".join(f"  - {k}: {v}" for k, v in flat.items())

    s = payload.my_slide

    retry_block = ""
    if payload.retry_hint:
        retry_block = (
            "\nIMPORTANT — RETRY ATTEMPT:\n"
            "Your previous version of this slide had a visual problem. "
            "Fix it this time. Hint from the visual reviewer:\n"
            f"  → {payload.retry_hint}\n"
        )

    return f"""You are writing content for ONE slide of a teaching presentation.
{retry_block}

Subject: {context.subject} | Class: {context.class_level} | Purpose: {context.purpose}
Language rule: {_language_rule(context)}
Level rule: {_level_rule(context)}
Purpose style: {_purpose_rule(context)}
{style_str}

PER-TEMPLATE RULES (apply ONLY the rule for YOUR template below):

  title_slide:
    - title          = lecture title (short, e.g. "Newton's Laws of Motion")
    - bullets        = []
    - speaker_notes  = ""

  recap_slide:
    - title          = "Recap of <topic>" — keep it 2-3 words after "Recap of"
    - bullets        = 3-5 SHORT topic names from previous lecture (max 6 words each)
    - NOT full explanations — just the topic labels

  topics_slide:
    - title          = "Topics to be covered" or similar 2-3 word heading
    - bullets        = 3-5 short topic names of THIS lecture
    - one phrase per topic, max 6 words

  section_heading:
    - title          = the upcoming topic / section name (display text)
    - bullets        = []

  table_slide:
    - title          = short caption / topic for the table (1-4 words). Renders
                       in the yellow tag, same as theory_slide.
    - bullets        = []     (do NOT add bullets — the slide is all table)
    - table_data     = REQUIRED. Extract the table directly from the source
                       page image and emit:
                         headers : list of column titles (use "" for any
                                   blank top-left cell)
                         rows    : list of rows; EVERY row must have the
                                   SAME length as headers. Use "" for empty
                                   cells. Do NOT add bullet markers, do NOT
                                   merge cells, do NOT paraphrase numbers.
                         caption : optional short caption (≤ 80 chars).
                         column_alignments : optional ["left"|"center"|"right"]
                                   per column. Default = numbers right-aligned,
                                   text left-aligned.
    - LOSSLESS RULE: every cell value visible in the source table must appear
      in `rows`, preserved verbatim (numbers exact, units intact). If the
      source has 4 columns × 4 rows, you emit headers (len 4) and rows
      (4 rows × 4 cells). Never collapse rows.
    - speaker_notes  = optional brief commentary on what the table shows.

  theory_table_slide:
    - title          = short topic heading (1-3 words). Renders in the yellow tag.
    - bullets        = 2-3 SHORT theory bullets that explain or set up the table
                       (each ≤ 18 words). Use "-> " prefix like theory_slide.
                       DO NOT describe the table cells in bullets — let the
                       table itself show the numbers.
    - table_data     = REQUIRED, same rules as `table_slide`. Keep the table
                       compact: aim for ≤ 6 rows × ≤ 5 columns so it fits below
                       the bullets on one slide. If the table is larger than
                       that, fall back to layout=table_slide (no bullets) on
                       a separate slide.

  theory_slide:
    - title          = topic heading (1-3 words). Will render in a yellow tag.
    - bullets        = teaching points written as 1-2 SENTENCES each
                       (~15-25 words). Paragraph-style, not telegram-short.
                       Use "-> " prefix on each main point (arrow rendered visually).
    - LENGTH IS CONTENT-DRIVEN: include EVERY teaching point the source
      genuinely needs — do NOT drop or over-compress to hit a count. If a
      passage has 8 important points, write all 8. The system automatically
      paginates a long slide into "(1/2)", "(2/2)" continuation slides, so you
      never need to truncate to make things fit. Prefer completeness over
      brevity, but keep each individual bullet focused (one idea per bullet).
    - Optional SUB-BULLETS for enumerations: when a main bullet lists named
      methods / cases / types, follow it with lines prefixed "(a) ...",
      "(b) ...", "(c) ...", "(d) ...". These do NOT get the "-> " prefix. Example:
          -> There are two methods for determining producer's equilibrium:
          (a) Total Revenue and Total Cost approach (TR-TC)
          (b) Marginal Revenue and Marginal Cost approach (MR-MC)
    - FORMULA FORMATTING: when the source has a formula/equation, make it
      VISUALLY PROMINENT — dedicate a bullet to the formula itself:
          -> Formula: P₀ = E(1−b) / (Ke − br)
      Then follow with substitution and result in separate bullets:
          -> Substituting: 159.09 = 10(1−b) / (0.08 − 0.12b)
          -> Result: b = 0.30, so Dividend Payout = 1 − 0.30 = 70%
      NEVER bury formulas mid-sentence in a long prose paragraph.
    - SOLUTION SLIDES: if this slide presents a worked-out SOLUTION, structure
      it as step-by-step working, NOT as descriptive prose:
          ✓  -> Formula: Cost = Annual Outflow × PVAF
          ✓  -> Given: ₹25 Crore/year, PVAF (15%, 4yr) = 2.855
          ✓  -> Calculation: 25 × 2.855 = ₹71.375 Crore
          ✗  "The cost is determined by multiplying the annual cash outflow
              by the present value annuity factor, which yields the result."

  passage_slide:
    - This is a CLOZE / reading-comprehension passage. Reproduce it EXACTLY.
    - directions     = the instruction/banner line for this passage, e.g.
                       "Directions (Q. 22-24): Cloze Test – Passage 1". Copy it
                       verbatim from the source. If the source has no explicit
                       directions line, use a short label like "Passage 1".
    - passage_text   = the FULL passage paragraph(s), copied WORD-FOR-WORD from
                       the source, with EVERY blank preserved EXACTLY as printed
                       (e.g. "__X__", "__Y__", "__Z__", ".....(1).....",
                       "_____(2)_____"). 
    - title          = a short label (e.g. "Passage 1") — used only internally.
    - bullets        = []   (the passage goes in passage_text, NOT in bullets)
    - speaker_notes  = "" (or any teaching note — but NEVER the answers here)
    - ABSOLUTE RULES — do NOT violate:
        ✗ Do NOT fill in any blank.
        ✗ Do NOT paraphrase, summarise, shorten, or "correct" the passage.
        ✗ Do NOT turn the passage into bullet points.
        ✓ The blanks MUST remain visible exactly as in the source PDF so the
          student can see what to fill. The per-blank options live on the
          SEPARATE question slides that follow this one.

  mcq_slide / mcq_grid_slide:
    - title          = ONLY the question stem — no "Q:", no number, no "Question:" prefix,
                       NO exam tag, NO answer, NO explanation, NO year info.
                       Example: "A large number of fish swimming together"
    - bullets        = EXACTLY 4 options
                       For mcq_slide use "(a) full text", "(b) full text", ...
                       For mcq_grid_slide options should be ≤ 3 words each (no "(a)" prefix needed)
    - speaker_notes  = "Answer: (x) <correct>. <brief why>"
    - CRITICAL: Do NOT reveal answer in title or bullets. NEVER.
                If you have been asked to "shorten the title", shorten ONLY the
                question stem — do NOT move the answer into the title.

  pyq_slide / pyq_grid_slide:
    - title          = ONLY the question stem (same rule as mcq — no exam tag, no answer)
    - bullets        = EXACTLY 4 options (same rule as mcq)
    - speaker_notes  = TWO separate lines:
        Line 1: "Exam: <exam name> <year>"    (e.g. "Exam: SSC CGL Tier-II 11/09/2019")
        Line 2: "Answer: (x) <correct>. <brief why>"
      These MUST be on separate lines (newline between them). NEVER combine
      them on one line. NEVER put the answer on the Exam line.
    - CRITICAL: Do NOT put exam name, year, or answer in the title field.
                The exam tag goes ONLY in speaker_notes line 1.
                The answer goes ONLY in speaker_notes line 2.

  question_only / pyq_question_only:
    - title          = full question text (no answer, no exam tag)
    - bullets        = []
    - speaker_notes  = For plain: "Answer: <full solution>"
                       For pyq: line 1 "Exam: <name> <year>", line 2 "Answer: <solution>"

  summary:
    - title          = "Summary"
    - bullets        = 4-6 key takeaways of the whole lecture (max 12 words each)

  homework_slide:
    - title          = "Homework"
    - bullets        = 3-5 concrete practice tasks for the student

  thank_you_slide:
    - title          = "Thank You"
    - bullets        = []
    - speaker_notes  = ""

FULL DECK OUTLINE (read-only — for coherence, do NOT repeat all of this):
{outline_str}

PREVIOUS SLIDE: {payload.prev_slide_summary or "This is the first slide — no previous slide."}

YOUR SLIDE TO GENERATE:
  Number  : {s.slide_number}
  Title   : {s.title}
  Template: {s.template}
  Points  : {json.dumps(s.key_points)}
  Emphasis: {json.dumps(s.emphasis)}
  Diagram : {"Yes — write a diagram_description of what to draw" if s.include_diagram else "No"}

SOURCE CONTENT FROM PDF PAGES:
{json.dumps(source_content, indent=2, ensure_ascii=False)}

{_strategy_rule(payload.strategy)}

GLOBAL RULES:
- Honour the PER-TEMPLATE rule above first; it overrides defaults.
- Bullet count/length is CONTENT-DRIVEN per the deck strategy above — do not
  pad with filler, and never drop real content to fit (the system paginates).
- Only say "as shown above" if prev_slide_summary confirms that content exists.
- Match terminology used across the full outline.
- Do NOT introduce concepts outside your assigned key_points.
- Set `layout` in the output to the same template name shown above.
- {_language_directive(context)}

ANTI-HALLUCINATION — SOURCE FIDELITY (CRITICAL):
- Use ONLY facts, numbers, and formulas that appear in the SOURCE CONTENT below.
- NEVER generate generic filler like "A comprehensive risk assessment must
  consider factors such as market volatility, technological obsolescence…"
  unless those exact words appear in the source.
- If the source says "₹25 Crore" and "PVAF = 2.855", your slide must say
  exactly that — not a paraphrased version.
- Prefer the source's ACTUAL DATA (numbers, names, values) over generic
  descriptions of what the data represents.

VERBATIM QUESTION TEXT — ABSOLUTE RULE (applies to every question/problem template):
- For mcq_slide, mcq_grid_slide, pyq_slide, pyq_grid_slide, question_only,
  pyq_question_only — the question stem AND every answer option MUST be copied
  CHARACTER-FOR-CHARACTER from the source main_text. This means:
    ✗ Do NOT paraphrase or reword the question — not even slightly
    ✗ Do NOT simplify, improve, or "correct" the language
    ✗ Do NOT fix grammar, spelling, or punctuation (preserve source errors)
    ✗ Do NOT shorten, expand, or restructure the question stem
    ✗ Do NOT change any number, value, unit, or mathematical expression
    ✗ Do NOT reorder or rephrase answer options
    ✓ Copy the exact characters from source — the student will compare the
      slide against their PDF and any difference is a CONTENT ERROR.
- If the exact wording is not in SOURCE CONTENT, use the closest matching
  text exactly as it appears. Never invent or smooth missing text.

VERBATIM NUMBERS & FORMULAS — STRICT RULE:
- Every number, formula, equation, and defined term must appear EXACTLY as
  written in the source. Do NOT round, approximate, or restate differently.
  "2.855" stays "2.855" — never "≈ 2.86" or "about 2.9".
- Mathematical notation must match the source exactly (same variables,
  same subscripts, same operators).

CURRENCY SYMBOLS:
- Always place currency symbols BEFORE the number: ₹25 Crore, $5,000
- NEVER write "25 Crore ₹" or "5,000 $"

ABSOLUTE RULE — TITLE FIELD HYGIENE (applies to ALL mcq/pyq variants):
  The `title` field = ONLY the question stem (the phrase/sentence being asked).
  NEVER include any of these in the title:
    ✗ "Answer: (a) Dirge"
    ✗ "Exam: SSC CGL 2019"
    ✗ "(SSC CGL Tier-II 11/09/2019)"
    ✗ Question numbers like "Q.661"
    ✗ Definitions / explanations of the answer
  All exam info and answers go ONLY in speaker_notes, on separate lines.
  If a RETRY HINT says "shorten the title", trim the question stem wording —
  do NOT move the answer or exam info into the title to "shorten" it.

Output valid JSON only, no markdown fences.
"""


# ── Async single slide writer ─────────────────────────────────────────────────

async def _write_slide_async(
    payload: AgentPayload,
    relevant_pages: list[ExtractedPage],
    context: PDFContext,
    semaphore: asyncio.Semaphore,
) -> SlideContent:
    """Async: write one slide. Semaphore caps concurrent Gemini calls."""
    async with semaphore:
        source_content = [
            {
                "page_number":        p.page_number,
                "main_text":          p.main_text,
                "diagrams_described": p.diagrams_described,
                "instructor_notes":   p.instructor_notes,
                "has_table":          getattr(p, "has_table", False),
                "table_description":  getattr(p, "table_description", None),
                "annotations": [
                    {"type": a.type, "target": a.target, "instruction": a.instruction}
                    for a in p.annotations
                ]
            }
            for p in relevant_pages
        ]

        prompt = _build_agent_prompt(payload, source_content, context)
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SlideContent
        )

        response = None
        try:
            record_api_attempt("writing", WRITING_MODEL)
            response = await client.aio.models.generate_content(
                model=WRITING_MODEL,
                contents=prompt,
                config=config
            )
            record_usage("writing", response.usage_metadata, model=WRITING_MODEL)
            slide = response.parsed
            # Carry the source pages through so detected figures can be attached
            # to the right slide later; never let the LLM inject a figure itself.
            slide.source_pages = list(payload.my_slide.source_pages or [])
            slide.figure = None
            limit = _max_bullets_for_layout(slide.layout)
            slide.bullets = slide.bullets[:limit]
            if slide.layout in (TemplateType.theory_slide, TemplateType.theory_table_slide):
                slide.bullets = _normalize_theory_bullets(slide.bullets)

            # Safety net: MCQ/PYQ slides MUST carry their options. If the LLM
            # returned fewer than 4 non-empty options, recover them from the
            # source page text so we never render an empty A/B/C/D question.
            if slide.layout in _MCQ_LAYOUTS:
                have = [b for b in slide.bullets if b and b.strip()]
                if len(have) < 4:
                    recovered = _recover_mcq_options(slide.title, source_content)
                    if len(recovered) >= len(have) and len(recovered) >= 2:
                        slide.bullets = recovered[:4]
                        print(f"  Slide {payload.my_slide.slide_number} — "
                              f"recovered {len(recovered)} MCQ option(s) from source")

            # Table safety net. A table layout (from the LLM OR the plan) MUST
            # carry structured table_data, else the renderer degrades to a
            # bullets-only theory slide and the table is lost. Recover it from
            # the source page text when it's missing.
            plan_wants_table = payload.my_slide.template in _TABLE_LAYOUTS
            td = getattr(slide, "table_data", None)
            td_empty = not td or not td.headers or not td.rows
            if (slide.layout in _TABLE_LAYOUTS or plan_wants_table) and td_empty:
                recovered_tbl = _recover_table_from_text(source_content)
                if recovered_tbl is not None:
                    slide.table_data = recovered_tbl
                    if slide.layout not in _TABLE_LAYOUTS:
                        slide.layout = payload.my_slide.template
                    print(f"  Slide {payload.my_slide.slide_number} — "
                          f"recovered table ({len(recovered_tbl.rows)} rows) from source")
                elif slide.layout in _TABLE_LAYOUTS:
                    # No table to recover — degrade gracefully so we don't render
                    # a table layout with an empty grid.
                    slide.layout = TemplateType.theory_slide
                    if not [b for b in slide.bullets if b and b.strip()]:
                        slide.bullets = _normalize_theory_bullets(
                            payload.my_slide.key_points[:6]
                        )

            print(f"  Slide {payload.my_slide.slide_number} — written OK")
            return slide

        except Exception as e:
            if response is None:
                record_api_failure("writing", WRITING_MODEL)
            print(f"  Slide {payload.my_slide.slide_number} — failed ({e}), using fallback")
            s = payload.my_slide
            bullets = s.key_points[:_max_bullets_for_layout(s.template)]
            if s.template in (TemplateType.theory_slide, TemplateType.theory_table_slide):
                bullets = _normalize_theory_bullets(bullets)
            # Fallback can't synthesise a table from page text alone — drop the
            # table layout to theory_slide so we at least render the key_points.
            fallback_layout = s.template
            if s.template in (TemplateType.table_slide, TemplateType.theory_table_slide):
                fallback_layout = TemplateType.theory_slide
                if not bullets:
                    bullets = s.key_points[:6]
                bullets = _normalize_theory_bullets(bullets)
            return SlideContent(
                slide_number=s.slide_number,
                title=s.title,
                bullets=bullets,
                diagram_description=None,
                speaker_notes="",
                layout=fallback_layout,
                source_pages=list(s.source_pages or []),
            )


# ── Async all slides — PARALLEL ───────────────────────────────────────────────

async def write_all_slides_async(
    slide_plan: FullSlidePlan,
    extracted_pages: list[ExtractedPage],
    context: PDFContext,
    style_rules: dict = None,
    strategy=None,
) -> list[SlideContent]:
    """
    Write ALL slides in PARALLEL.

    Each agent gets:
    - my_slide        → its own slide to write
    - full_outline    → entire deck for context (prevents incoherence)
    - prev_summary    → what came just before (prevents broken references)
    - style_rules     → learned rules from memory/style.yaml

    Speed comparison on 12 slides:
      Sequential (old): 12 × ~3s = ~36 seconds
      Parallel   (new): ceil(12/10) × ~3s = ~6 seconds
    """
    style_rules = style_rules or {}
    payloads = _build_payloads(slide_plan.slides, style_rules, strategy)
    sem = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)

    print(f"  Writing {len(payloads)} slides in parallel (max {MAX_CONCURRENT_AGENTS} concurrent)...")

    tasks = []
    for payload in payloads:
        relevant = [
            p for p in extracted_pages
            if p.page_number in payload.my_slide.source_pages
        ]
        tasks.append(_write_slide_async(payload, relevant, context, sem))

    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    slides = []
    for i, result in enumerate(raw_results):
        if isinstance(result, Exception):
            # hard fallback — should rarely happen since _write_slide_async already handles errors
            s = slide_plan.slides[i]
            slides.append(SlideContent(
                slide_number=s.slide_number,
                title=s.title,
                bullets=s.key_points[:MAX_BULLETS],
                diagram_description=None,
                speaker_notes="",
                layout=s.template,
                source_pages=list(s.source_pages or []),
            ))
        else:
            slides.append(result)

    slides.sort(key=lambda s: s.slide_number)
    print(f"\n  Writing done — {len(slides)} slides")
    return slides


async def rewrite_slides_with_hints(
    original_contents: list[SlideContent],
    slide_plan: FullSlidePlan,
    extracted_pages: list[ExtractedPage],
    context: PDFContext,
    style_rules: dict,
    fixes: dict[int, dict],
    strategy=None,
) -> list[SlideContent]:
    """
    Rewrite ONLY the slides flagged by the Visual Critic.

    `fixes` maps slide_number → dict with optional keys:
      - 'hint'         : str, content_fix_hint from critic
      - 'new_layout'   : TemplateType, if critic suggested a layout change

    Slides not in `fixes` are kept as-is. Slides in `fixes` are re-written
    with the hint injected into their writer prompt.
    """
    style_rules = style_rules or {}
    # Apply layout overrides first so the prompt builder sees the new template
    outline_by_num = {s.slide_number: s for s in slide_plan.slides}
    for sn, fx in fixes.items():
        if fx.get("new_layout") and sn in outline_by_num:
            outline_by_num[sn].template = fx["new_layout"]

    payloads = _build_payloads(list(outline_by_num.values()), style_rules, strategy)
    # filter to only those we want to rewrite
    target_payloads = [p for p in payloads if p.my_slide.slide_number in fixes]
    if not target_payloads:
        return original_contents

    # attach retry hint to each target
    for p in target_payloads:
        hint = fixes.get(p.my_slide.slide_number, {}).get("hint")
        p.retry_hint = hint or "Improve this slide so it renders cleanly."

    sem = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)
    print(f"  Rewriting {len(target_payloads)} flagged slide(s) with critic hints...")

    tasks = []
    for payload in target_payloads:
        relevant = [
            p for p in extracted_pages
            if p.page_number in payload.my_slide.source_pages
        ]
        tasks.append(_write_slide_async(payload, relevant, context, sem))

    new_results = await asyncio.gather(*tasks, return_exceptions=True)

    # merge: keep originals, overwrite rewritten ones
    rewritten_by_num: dict[int, SlideContent] = {}
    for r in new_results:
        if isinstance(r, SlideContent):
            rewritten_by_num[r.slide_number] = r

    merged: list[SlideContent] = []
    for c in original_contents:
        merged.append(rewritten_by_num.get(c.slide_number, c))
    return merged


# ── SYNC fallback ─────────────────────────────────────────────────────────────

def write_slide(
    slide_outline: SlideOutline,
    extracted_pages: list[ExtractedPage],
    context: PDFContext
) -> SlideContent:
    """Sync single-slide writer — kept for compatibility/testing."""
    relevant_pages = [p for p in extracted_pages if p.page_number in slide_outline.source_pages]
    source_content = [
        {
            "page_number": p.page_number,
            "main_text": p.main_text,
            "diagrams_described": p.diagrams_described,
            "instructor_notes": p.instructor_notes,
            "annotations": [{"type": a.type, "target": a.target, "instruction": a.instruction}
                            for a in p.annotations]
        }
        for p in relevant_pages
    ]

    payload = AgentPayload(
        my_slide=slide_outline,
        full_outline=[slide_outline],
        prev_slide_summary=None,
        style_rules={}
    )

    prompt = _build_agent_prompt(payload, source_content, context)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=SlideContent
    )

    response = None
    try:
        record_api_attempt("writing", WRITING_MODEL)
        response = client.models.generate_content(model=WRITING_MODEL, contents=prompt, config=config)
        record_usage("writing", response.usage_metadata, model=WRITING_MODEL)
        slide = response.parsed
        slide.source_pages = list(slide_outline.source_pages or [])
        slide.figure = None
        limit = _max_bullets_for_layout(slide.layout)
        slide.bullets = slide.bullets[:limit]
        if slide.layout in (TemplateType.theory_slide, TemplateType.theory_table_slide):
            slide.bullets = _normalize_theory_bullets(slide.bullets)
        return slide
    except Exception:
        if response is None:
            record_api_failure("writing", WRITING_MODEL)
        bullets = slide_outline.key_points[:_max_bullets_for_layout(slide_outline.template)]
        if slide_outline.template in (TemplateType.theory_slide, TemplateType.theory_table_slide):
            bullets = _normalize_theory_bullets(bullets)
        return SlideContent(
            slide_number=slide_outline.slide_number,
            title=slide_outline.title,
            bullets=bullets,
            diagram_description=None,
            speaker_notes="",
            layout=slide_outline.template,
            source_pages=list(slide_outline.source_pages or []),
        )


def write_all_slides(
    slide_plan: FullSlidePlan,
    extracted_pages: list[ExtractedPage],
    context: PDFContext
) -> list[SlideContent]:
    """Sync sequential writer — fallback only."""
    all_slide_contents = []
    for slide_outline in slide_plan.slides:
        print(f"  Writing slide {slide_outline.slide_number} — {slide_outline.title}...")
        content = write_slide(slide_outline, extracted_pages, context)
        all_slide_contents.append(content)
    print(f"\n  Writing done — {len(all_slide_contents)} slides written")
    return all_slide_contents
