"""
Slide cleanup — drop empty / placeholder slides before generation.

When the planner mints a dedicated slide for an annotated target (e.g. a circled
"Q.32") that the extractor never actually captured, the writer has nothing real
to put on it and may emit placeholder text ("Content missing", "full text not
available", "this question was marked for inclusion …"). Such slides are never
acceptable output.

This deterministic pass removes any BODY/question slide whose real content is
empty or placeholder, then renumbers 1..N. Structural slides (title, section,
summary, thank-you, recap, topics, homework) are never touched, and a slide
that has a genuine title/question is kept even if its body is thin.
"""
import re
from schemas.slide_content import SlideContent
from schemas.slide_plan import TemplateType


# Substrings that mark fabricated "no content" text.
_PLACEHOLDER_SNIPPETS = (
    "content missing", "missing content", "content not found",
    "not available", "was not available", "no content",
    "marked for inclusion", "full text for this question",
    "could not be found", "not found in the source",
    "type option here", "type question here", "type heading here",
)

# Layouts allowed to carry little/no body content — never dropped here.
_STRUCTURAL = {
    TemplateType.title_slide, TemplateType.section_heading,
    TemplateType.summary, TemplateType.thank_you_slide,
    TemplateType.recap_slide, TemplateType.topics_slide,
    TemplateType.homework_slide,
}

# A title that carries no information of its own (e.g. "Question 34", "Q.32").
_GENERIC_TITLE_RE = re.compile(r'^(question|ques|q\.?|slide|passage)\s*\.?\s*\d*\s*$',
                               re.IGNORECASE)


def _is_placeholder(text) -> bool:
    s = (text or "").strip().lower()
    if not s:
        return True
    return any(snip in s for snip in _PLACEHOLDER_SNIPPETS)


def _has_real_content(c: SlideContent) -> bool:
    real_bullets = [
        b for b in (c.bullets or [])
        if b and b.strip() and not _is_placeholder(b)
    ]
    passage = (getattr(c, "passage_text", None) or "").strip()
    has_passage = bool(passage) and not _is_placeholder(passage)
    table = getattr(c, "table_data", None)
    has_table = bool(table and table.headers and table.rows)
    return bool(real_bullets) or has_passage or has_table


def _is_droppable(c: SlideContent) -> bool:
    """A non-structural slide with no real body AND a weak/placeholder title."""
    if c.layout in _STRUCTURAL:
        return False
    if _has_real_content(c):
        return False
    title = (c.title or "").strip()
    title_is_weak = (
        not title
        or _is_placeholder(title)
        or bool(_GENERIC_TITLE_RE.match(title))
    )
    return title_is_weak


def drop_placeholder_slides(
    contents: list[SlideContent],
) -> tuple[list[SlideContent], list[str]]:
    """
    Remove empty/placeholder slides and renumber. Returns (kept, change_log).
    """
    kept: list[SlideContent] = []
    log: list[str] = []
    for c in contents:
        if _is_droppable(c):
            log.append(
                f"slide {c.slide_number} [{c.layout.value}] "
                f"'{(c.title or '').strip()[:40]}' — empty/placeholder, dropped"
            )
        else:
            kept.append(c)
    for i, c in enumerate(kept, start=1):
        c.slide_number = i
    return kept, log


def render_cleanup_report(log: list[str]) -> str:
    if not log:
        return "    No empty/placeholder slides found."
    return (f"    Dropped {len(log)} empty/placeholder slide(s):\n"
            + "\n".join(f"      • {line}" for line in log))


# ── Duplicate-table dedupe ──────────────────────────────────────────────────

_TABLE_LAYOUTS = {TemplateType.table_slide, TemplateType.theory_table_slide}


def _table_signature(tb) -> str | None:
    """A normalized fingerprint of a table's headers + cells, or None."""
    if not tb or not getattr(tb, "headers", None) or not getattr(tb, "rows", None):
        return None
    parts = [str(h).strip().lower() for h in tb.headers]
    for row in tb.rows:
        parts.extend(str(c).strip().lower() for c in row)
    sig = "|".join(parts)
    return sig if sig.strip("|") else None


def _table_match_score(content: SlideContent, tb) -> int:
    """How well a slide's title describes this table — higher = better home."""
    title = (content.title or "").lower()
    tokens: set[str] = set()
    for h in tb.headers:
        tokens.update(re.findall(r"[a-z]{3,}", str(h).lower()))
    if getattr(tb, "caption", None):
        tokens.update(re.findall(r"[a-z]{3,}", tb.caption.lower()))
    score = sum(1 for t in tokens if t in title)
    # A dedicated table-only slide is the natural home for the table.
    if content.layout == TemplateType.table_slide:
        score += 2
    return score


def dedupe_tables(
    contents: list[SlideContent],
) -> tuple[list[SlideContent], list[str]]:
    """
    Remove the SAME table repeated across multiple slides.

    The planner sometimes attaches one source table to two slides (e.g. an
    intro "case study" slide AND a dedicated "discount factors" slide), so the
    audience sees the identical grid twice. We keep the table on the slide that
    best describes it and downgrade the others to a plain theory slide,
    preserving their bullets. A slide left with neither table nor bullets is
    dropped. Slides are renumbered 1..N.
    """
    groups: dict[str, list[int]] = {}
    for idx, c in enumerate(contents):
        if c.layout in _TABLE_LAYOUTS:
            sig = _table_signature(getattr(c, "table_data", None))
            if sig:
                groups.setdefault(sig, []).append(idx)

    strip_idx: set[int] = set()
    for sig, idxs in groups.items():
        if len(idxs) < 2:
            continue
        keeper = max(
            idxs,
            key=lambda i: (
                _table_match_score(contents[i], contents[i].table_data),
                -len([b for b in (contents[i].bullets or []) if b and b.strip()]),
                i,
            ),
        )
        strip_idx.update(i for i in idxs if i != keeper)

    if not strip_idx:
        return contents, []

    kept: list[SlideContent] = []
    log: list[str] = []
    for idx, c in enumerate(contents):
        if idx not in strip_idx:
            kept.append(c)
            continue
        has_bullets = any(b and b.strip() for b in (c.bullets or []))
        if has_bullets:
            c.table_data = None
            c.layout = TemplateType.theory_slide
            kept.append(c)
            log.append(
                f"slide {c.slide_number} '{(c.title or '').strip()[:40]}' — "
                f"duplicate table removed, kept as theory slide"
            )
        else:
            log.append(
                f"slide {c.slide_number} '{(c.title or '').strip()[:40]}' — "
                f"duplicate table-only slide dropped"
            )

    for i, c in enumerate(kept, start=1):
        c.slide_number = i
    return kept, log


def render_dedupe_report(log: list[str]) -> str:
    if not log:
        return "    No duplicate tables found."
    return (f"    Resolved {len(log)} duplicate table(s):\n"
            + "\n".join(f"      • {line}" for line in log))
