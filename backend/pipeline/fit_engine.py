"""
Fit & Reflow engine  (Phase 1 of the adaptive-layout redesign)

WHY THIS EXISTS
───────────────
The old pipeline enforced hard caps (MAX_BULLETS = 5, MAX_BULLET_WORDS = 12)
and the QC step *truncated* any bullet that was too long ("… and the rest is
lost"). That destroys content and ignores the fact that a dense theory page
and a one-line DPP hint need very different amounts of text per slide.

This engine replaces "truncate to fit" with "measure, then PAGINATE":

  • Each body layout has a CAPACITY model derived from the real template box
    geometry (width × height in inches) and an acceptable font range.
  • For every slide we estimate how tall the rendered bullet block would be.
  • If it fits → keep one slide, and the generator renders at the largest
    font that fits (bigger = more readable).
  • If it overflows → SPLIT the bullets across continuation slides
    ("Topic (1/2)", "Topic (2/2)", …). No words are ever dropped.

The estimate is a deterministic heuristic (no LLM, no rendering): we approximate
characters-per-line from the box width and font size, then sum line heights.
It is intentionally a little CONSERVATIVE (assumes a slightly wide font) so we
err toward splitting / smaller fonts rather than overflow.

DESIGN CONTRACT
───────────────
`pick_body_font()` is the single source of truth for body font size and is
imported by ppt_generator so the generator and the engine always agree: the
engine guarantees a chunk fits at >= the smallest acceptable font, and the
generator then renders it at the largest font that fits.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import dataclass

from schemas.slide_content import SlideContent
from schemas.slide_plan import TemplateType
from schemas.deck_strategy import DeckStrategy, Density


# ─────────────────────────────────────────────────────────────────────────────
# Capacity model — per layout
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Capacity:
    """
    How much a layout's body region can hold.

    mode:
      "free"  — a free-flowing textbox we control (theory / summary / homework).
                Bullets paginate by measured height.
      "slots" — a fixed number of template slots (recap / topics).
                Bullets paginate by count.
      "skip"  — no reflowable body (title / section / mcq / question_only / …).
                MCQ options are atomic (must stay together) so we never split them.
    """
    mode: str
    width_in: float = 0.0          # usable text width of the body box
    height_in: float = 0.0         # usable text height of the body box
    font_min: int = 0              # smallest acceptable body font (pt)
    font_max: int = 0              # largest body font (pt)
    pack_font: int = 0             # font used to DECIDE splits (readable target)
    slots: int = 0                 # for "slots" mode
    continuation_suffix: bool = True   # add " (i/n)" to split titles


# Geometry below matches the body boxes built in ppt_generator:
#   • theory_slide body box ≈ L1.5  W37.0  and ~17.8 in tall (see _fill_theory_slide)
#   • summary / homework body box   = _add_bullets_textbox → L1.5 T6.0 W37 H15
#   • recap / topics                = 4 fixed numbered slots in the template
_CAPACITY: dict[TemplateType, Capacity] = {
    # The canvas is 40 × 22.5 in (≈3× a normal 16:9 deck), so body fonts must be
    # large (≈48-72pt) to look proportionate and FILL the slide — small fonts
    # leave a hand-made deck looking empty. pick_body_font then chooses the
    # largest size in range that fits, so sparse slides render big and dense
    # slides render smaller (and paginate) automatically.
    TemplateType.theory_slide: Capacity(
        mode="free", width_in=37.0, height_in=17.8,
        font_min=40, font_max=72, pack_font=50,
    ),
    TemplateType.summary: Capacity(
        mode="free", width_in=37.0, height_in=15.0,
        font_min=32, font_max=60, pack_font=40,
    ),
    TemplateType.homework_slide: Capacity(
        mode="free", width_in=37.0, height_in=15.0,
        font_min=32, font_max=60, pack_font=40,
    ),
    TemplateType.recap_slide: Capacity(
        mode="slots", slots=4, continuation_suffix=False,
    ),
    TemplateType.topics_slide: Capacity(
        mode="slots", slots=4, continuation_suffix=False,
    ),
}

# Tuning constants for the height heuristic.
_LINE_FACTOR = 1.3        # line height ≈ font_pt × 1.3
_SPACE_AFTER_PT = 20      # vertical gap after each bullet
_CHAR_W = 0.0095          # avg char advance ≈ 0.0095 in per pt (calibrated to render)
_MARKER_CHARS = 4         # the "➤   " arrow marker eats ~4 chars of width

# Density → pack-font delta. A HIGHER pack font means we decide to split sooner,
# so each slide holds less and renders bigger (more readable). Verbose decks
# therefore paginate more eagerly; terse decks pack a little tighter.
_DENSITY_PACK_DELTA = {
    Density.terse:    -2,
    Density.balanced:  0,
    Density.verbose:  +6,
}


def _pack_font_for(cap: "Capacity", strategy: DeckStrategy | None) -> int:
    """Resolve the split-decision font, nudged by the deck's density."""
    if strategy is None or cap.mode != "free":
        return cap.pack_font
    delta = _DENSITY_PACK_DELTA.get(strategy.density, 0)
    return max(cap.font_min, min(cap.font_max, cap.pack_font + delta))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _strip_marker(text: str) -> str:
    """Drop the writer's '-> ' / '➤ ' marker so length reflects real content."""
    t = (text or "").strip()
    for pfx in ("-> ", "->", "➤ ", "➤", "• ", "•"):
        if t.startswith(pfx):
            return t[len(pfx):].lstrip()
    return t


def estimate_block_height_in(bullets: list[str], font_pt: int, width_in: float) -> float:
    """
    Approximate the rendered height (inches) of a bullet block at `font_pt`.

    chars_per_line = width / (font_pt × char_advance)
    lines_per_bullet = ceil(effective_chars / chars_per_line)
    height = Σ (lines × line_height + space_after)
    """
    if not bullets or font_pt <= 0 or width_in <= 0:
        return 0.0
    line_h = font_pt * _LINE_FACTOR / 72.0
    space_after = _SPACE_AFTER_PT / 72.0
    chars_per_line = max(1, int(width_in / (font_pt * _CHAR_W)))

    total = 0.0
    for b in bullets:
        eff = len(_strip_marker(b)) + _MARKER_CHARS
        n_lines = max(1, math.ceil(eff / chars_per_line))
        total += n_lines * line_h + space_after
    return total


def pick_body_font(bullets: list[str], layout: TemplateType) -> int:
    """
    The largest font in [font_min, font_max] whose block fits the box height.
    Shared with ppt_generator so rendering matches the engine's fit decision.
    Falls back to a sane default for layouts without a free-body capacity.
    """
    cap = _CAPACITY.get(layout)
    if cap is None or cap.mode != "free":
        return 40
    for pt in range(cap.font_max, cap.font_min - 1, -2):
        if estimate_block_height_in(bullets, pt, cap.width_in) <= cap.height_in:
            return pt
    return cap.font_min


def consistent_body_font(layout: TemplateType, strategy: DeckStrategy | None = None) -> int:
    """
    A SINGLE body font size used for EVERY slide of `layout` in the deck.

    Unlike `pick_body_font` (which maximises per slide, so sparse slides render
    bigger than dense ones — a visible inconsistency across the deck), this
    returns the deck's fixed pack font. Reflow splits content so each chunk fits
    at exactly this size, so rendering here is guaranteed not to overflow while
    keeping every slide's bullets the same readable size.
    """
    cap = _CAPACITY.get(layout)
    if cap is None or cap.mode != "free":
        return 40
    return _pack_font_for(cap, strategy)


# ─────────────────────────────────────────────────────────────────────────────
# Splitting
# ─────────────────────────────────────────────────────────────────────────────

def _split_free(
    bullets: list[str],
    cap: Capacity,
    pack_font: int,
    eff_height_in: float,
) -> list[list[str]]:
    """
    Greedily pack bullets into chunks that each fit `eff_height_in` at the
    readable `pack_font`. A single over-long bullet is kept alone (we never
    split inside one bullet — the generator word-wraps / shrinks it).

    `eff_height_in` is the box height after applying overflow pressure: a
    higher pressure shrinks it, forcing more aggressive splitting.
    """
    chunks: list[list[str]] = []
    cur: list[str] = []
    for b in bullets:
        trial = cur + [b]
        if cur and estimate_block_height_in(trial, pack_font, cap.width_in) > eff_height_in:
            chunks.append(cur)
            cur = [b]
        else:
            cur = trial
    if cur:
        chunks.append(cur)
    return chunks or [bullets]


def _effective_height(cap: Capacity, overflow_pressure: int) -> float:
    """
    Shrink the usable box height as overflow pressure rises. Each pressure step
    removes ~18% of the height (floored at 45%) so when the visual critic
    confirms a real overflow, one or two steps comfortably re-split the slide.
    """
    factor = max(0.45, 1.0 - 0.18 * max(0, overflow_pressure))
    return cap.height_in * factor


def _split_slots(bullets: list[str], cap: Capacity) -> list[list[str]]:
    """Fixed-slot layouts: chunk by slot count (e.g. 4 numbered boxes)."""
    n = max(1, cap.slots)
    return [bullets[i:i + n] for i in range(0, len(bullets), n)] or [bullets]


def _make_chunk_slide(base: SlideContent, chunk: list[str],
                      idx: int, total: int, cap: Capacity) -> SlideContent:
    """Build one continuation SlideContent from a chunk of the original."""
    nc = deepcopy(base)
    nc.bullets = chunk
    if total > 1 and cap.continuation_suffix:
        nc.title = f"{base.title} ({idx}/{total})"
    if idx > 1:
        # keep notes/diagram only on the first slide of the run — avoids dupes
        nc.speaker_notes = ""
        nc.diagram_description = None
    return nc


# A continuation suffix we previously added, e.g. "Topic (2/3)".
_SUFFIX_RE = re.compile(r'^(.*?)\s*\(\s*(\d+)\s*/\s*(\d+)\s*\)\s*$')


def _strip_continuation_suffix(title: str) -> str:
    m = _SUFFIX_RE.match(title or "")
    return m.group(1).strip() if m else (title or "")


def _has_continuation_suffix(title: str) -> bool:
    return bool(_SUFFIX_RE.match(title or ""))


def _normalize_continuations(contents: list[SlideContent]) -> list[SlideContent]:
    """
    Reverse any *previous* pagination so reflow can be re-run cleanly at a new
    pressure without compounding suffixes ("(1/2) (1/2)"). Only coalesces
    consecutive free-body slides that we ourselves split — identified by the
    "(i/n)" suffix and a shared base title. Planner-made slides are untouched.
    """
    out: list[SlideContent] = []
    i = 0
    n = len(contents)
    while i < n:
        c = contents[i]
        cap = _CAPACITY.get(c.layout)
        if cap is None or cap.mode != "free" or not _has_continuation_suffix(c.title):
            out.append(c)
            i += 1
            continue

        base_title = _strip_continuation_suffix(c.title)
        group = [c]
        j = i + 1
        while j < n:
            d = contents[j]
            if (d.layout == c.layout
                    and _has_continuation_suffix(d.title)
                    and _strip_continuation_suffix(d.title) == base_title):
                group.append(d)
                j += 1
            else:
                break

        merged = deepcopy(group[0])
        merged.title = base_title
        merged.bullets = [b for g in group for b in g.bullets]
        out.append(merged)
        i = j
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def reflow_slides(
    contents: list[SlideContent],
    strategy: DeckStrategy | None = None,
    overflow_pressure: int = 0,
) -> tuple[list[SlideContent], list[str]]:
    """
    Paginate any slide whose body content overflows its box.

    `strategy` (optional) tunes how eagerly free-body layouts paginate via the
    deck's density — verbose decks split sooner for readability.

    `overflow_pressure` (Phase 3) is raised by the visual loop when the critic
    confirms a slide STILL overflows after rendering: it shrinks the assumed
    box so the slide splits into more pieces — never deletes content.

    Returns (new_contents, change_log). The result is renumbered 1..N so that
    `slide_number` matches list position — the visual critic relies on this to
    map slide_number → rendered PDF page.

    Idempotent in practice (at a fixed pressure): a second pass finds everything
    already fits and makes no further splits.
    """
    out: list[SlideContent] = []
    log: list[str] = []

    # Un-split any prior pagination first so re-running at a higher pressure
    # produces clean global "(i/n)" numbering instead of compounding suffixes.
    contents = _normalize_continuations(contents)

    for c in contents:
        cap = _CAPACITY.get(c.layout)
        if cap is None or cap.mode == "skip" or not c.bullets:
            out.append(c)
            continue

        if cap.mode == "slots":
            chunks = _split_slots(c.bullets, cap)
        else:
            chunks = _split_free(
                c.bullets, cap,
                _pack_font_for(cap, strategy),
                _effective_height(cap, overflow_pressure),
            )

        if len(chunks) <= 1:
            out.append(c)
            continue

        total = len(chunks)
        for i, chunk in enumerate(chunks, start=1):
            out.append(_make_chunk_slide(c, chunk, i, total, cap))
        log.append(
            f"slide {c.slide_number} [{c.layout.value}] '{c.title[:40]}' "
            f"→ split into {total} slides ({len(c.bullets)} bullets paginated)"
        )

    # renumber so slide_number == 1-based position (visual critic depends on it)
    for i, c in enumerate(out, start=1):
        c.slide_number = i

    return out, log


_CONT_STRUCTURAL = {
    TemplateType.title_slide, TemplateType.section_heading,
    TemplateType.thank_you_slide,
}

_CONT_SUFFIX_RE = re.compile(r'\s*\(cont\.(?:\s*\d+)?\)\s*$', re.IGNORECASE)


def _strip_cont_suffix(title: str) -> str:
    return _CONT_SUFFIX_RE.sub('', title or '').strip()


def label_continuation_titles(
    contents: list[SlideContent],
) -> tuple[list[SlideContent], list[str]]:
    """
    Make consecutive slides that share the SAME title visually distinct.

    Whether a long topic was paginated by reflow or the planner simply emitted
    two slides with the same heading, two identical titles in a row read like a
    glitch. We append " (cont.)" / " (cont. 2)" to the 2nd+ slide of each run so
    the audience knows it continues the previous slide.

    Idempotent: any existing "(cont.)" suffix is stripped first, so re-running
    (e.g. inside the visual loop) never compounds suffixes. Reflow's own "(i/n)"
    suffixes are left alone.
    """
    log: list[str] = []
    prev_base = None
    run_idx = 0
    for c in contents:
        # Normalise away any suffix we added on a previous pass.
        c.title = _strip_cont_suffix(c.title)
        if c.layout in _CONT_STRUCTURAL or _has_continuation_suffix(c.title):
            prev_base = None
            run_idx = 0
            continue
        base = (c.title or "").strip()
        if base and base.lower() == (prev_base or "").lower():
            run_idx += 1
            suffix = " (cont.)" if run_idx == 1 else f" (cont. {run_idx})"
            c.title = base + suffix
            log.append(f"slide {c.slide_number}: '{base[:40]}' → '{c.title[:48]}'")
        else:
            prev_base = base
            run_idx = 0
    return contents, log


def is_free_body_layout(layout: TemplateType) -> bool:
    """True if this layout's body paginates (theory / summary / homework)."""
    cap = _CAPACITY.get(layout)
    return cap is not None and cap.mode == "free"


def render_reflow_report(log: list[str]) -> str:
    """Pretty-print for the pipeline log."""
    if not log:
        return "    No slides needed splitting — all content fits."
    lines = [f"    Paginated {len(log)} overflowing slide(s):"]
    lines += [f"      • {line}" for line in log]
    return "\n".join(lines)
