"""
Split a page's extracted `main_text` into selectable items (one per question).

The interactive review UI lets the user pick which items on a page should go
into the PPT. To do that reliably we need a STABLE, deterministic split of the
raw extraction into individual question/problem chunks.

Heuristic: a new item begins wherever a question number marker appears — either
at the start of a line or after a sentence-ending boundary (". " / "? " / "! ")
when the text is run together as a single paragraph.

Everything before the first such marker is returned as an "intro" preamble
(e.g. an "Exercise 6" heading) so the user can include/exclude it separately.

The toggle is shown whenever at least one question is detected.
"""
from __future__ import annotations

import re
from typing import Optional, TypedDict


# ── question-start patterns ───────────────────────────────────────────────────
#
# Tries to detect a new question in two layouts:
#
#  Layout A — question number at the beginning of its own line:
#       "3. The sum of two numbers…"
#       "Q.12) If the ratio…"
#
#  Layout B — question number after a sentence boundary (inline / run-on):
#       "…find the numbers.4. The cost of 5 kg…"
#
# The regex uses an alternation: (line-start | sentence-end) so it catches both.

_ITEM_START_RE = re.compile(
    r'(?:'
    r'(?:^|\n)\s*'                          # Layout A: line boundary
    r'|'
    r'(?<=[.!?])\s*'                         # Layout B: after sentence punctuation (no space required)
    r')'
    r'((?:Q\.?\s*)?(\d{1,3}))\s*[.)]\s+\S',
    re.MULTILINE,
)

_MIN_QUESTIONS_FOR_SELECTION = 1           # show toggle even for 1-question pages


class PageItem(TypedDict):
    id: str
    label: str
    preview: str
    text: str
    kind: str          # "question" | "intro"


def _preview(text: str, limit: int = 140) -> str:
    """Single-line preview for the checkbox row."""
    flat = re.sub(r'\s+', ' ', text).strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def split_page_items(page_number: int, main_text: Optional[str]) -> list[PageItem]:
    """
    Return the selectable items on a page.

    Empty list means "no granular items" — the page is all-or-nothing and the
    UI should only offer Include / Skip (no per-item checkboxes).
    """
    text = (main_text or "").strip()
    if not text:
        return []

    matches = list(_ITEM_START_RE.finditer(text))
    if len(matches) < _MIN_QUESTIONS_FOR_SELECTION:
        return []

    items: list[PageItem] = []

    # Preamble before the first question (e.g. "Exercise 6" heading).
    # For inline layout the match starts mid-sentence; find the real split point
    # by going back to the sentence-end boundary.
    first_item_start = _item_start_pos(text, matches[0])
    preamble = text[:first_item_start].strip()
    if preamble:
        items.append(
            PageItem(
                id=f"p{page_number}-intro",
                label="Intro",
                preview=_preview(preamble),
                text=preamble,
                kind="intro",
            )
        )

    for i, m in enumerate(matches):
        start = _item_start_pos(text, m)
        next_start = (
            _item_start_pos(text, matches[i + 1])
            if i + 1 < len(matches)
            else len(text)
        )
        chunk = text[start:next_start].strip()
        if not chunk:
            continue
        number = m.group(2)
        items.append(
            PageItem(
                id=f"p{page_number}-q{number}-{i}",
                label=f"Q{number}",
                preview=_preview(chunk),
                text=chunk,
                kind="question",
            )
        )

    return items


def _item_start_pos(text: str, m: re.Match) -> int:
    """
    Return the index in `text` where the question *content* begins.

    For a line-start match the question starts at the first non-whitespace
    character matched by the pattern (e.g. "3" in "3. The sum…").
    For an inline match that starts after ". " we go back to the character
    right after the sentence-end period so the chunk begins at the number.
    """
    raw = m.group(0)
    # Find where the number label itself starts inside the full match.
    label = m.group(1)                  # e.g. "Q.12" or "3"
    label_offset = raw.index(label)
    return m.start() + label_offset
