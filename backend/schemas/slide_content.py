"""This is the final content for each slide — actual title, bullets,
diagram description, speaker notes, and the layout template ready to be
placed into the PPT."""
import re
from pydantic import BaseModel, field_validator
from typing import Optional
from schemas.slide_plan import TemplateType
from schemas.text_sanitize import restore_symbols, strip_control_chars


_CURRENCY_SWAP_RE = re.compile(
    r'(\d[\d,.]*)\s*(Crore|Lakh|crore|lakh)?\s*(₹|\$|€|£)'
)


def _sanitize_slide_text(text: str | None) -> str | None:
    if not text:
        return text
    # Restore mangled symbols (₹, ×, …) BEFORE stripping control chars, so a
    # Word-escaped "_x20B9_" becomes ₹ instead of being deleted.
    t = restore_symbols(text)
    t = strip_control_chars(t)
    t = _CURRENCY_SWAP_RE.sub(lambda m: f"{m.group(3)}{m.group(1)}{' ' + m.group(2) if m.group(2) else ''}", t)
    # Tidy "₹ 71.375" → "₹71.375" (symbol hugs the number).
    t = re.sub(r'([₹$€£])\s+(\d)', r'\1\2', t)
    return t.strip()


class TableBlock(BaseModel):
    """
    Structured rendition of a table found in the source PDF.

    Used by `table_slide` (table-only) and `theory_table_slide` (theory bullets
    above a table). The renderer turns this into a real PowerPoint table — not
    bullet text — so columns line up and the data stays scannable.

    Field rules for the writer:
      • headers    : column titles, exactly as in the source. First entry may
                     be a row-label column header (e.g. "Year", "n"); leave it
                     empty string "" if the source's top-left cell is blank.
      • rows       : list of rows; every row MUST have len(row) == len(headers).
                     Cells should be the raw value (e.g. "0.869", "$5,000",
                     "Yes") with no markdown or bullet markers. Use "" for
                     genuinely empty cells.
      • caption    : optional short caption shown above the table (e.g.
                     "Discount factors for n = 1..4"). Keep ≤ 80 chars.
      • column_alignments (optional) : per-column alignment hints — one of
                     "left" / "center" / "right". If omitted the renderer
                     left-aligns text and right-aligns numbers heuristically.
    """
    headers:            list[str]
    rows:               list[list[str]]
    caption:            Optional[str] = None
    column_alignments:  Optional[list[str]] = None


class SlideContent(BaseModel):
    slide_number:        int
    title:               str
    bullets:             list[str]
    diagram_description: Optional[str] = None
    speaker_notes:       str
    layout:              TemplateType

    # ── passage_slide (cloze / reading-comprehension) only ───────────────────
    directions:          Optional[str] = None
    passage_text:        Optional[str] = None

    # ── table_slide / theory_table_slide only ────────────────────────────────
    table_data:          Optional[TableBlock] = None

    @field_validator('title', mode='before')
    @classmethod
    def clean_title(cls, v):
        return _sanitize_slide_text(v) or ''

    @field_validator('bullets', mode='before')
    @classmethod
    def clean_bullets(cls, v):
        if not v:
            return v
        return [_sanitize_slide_text(b) or b for b in v]

    @field_validator('speaker_notes', mode='before')
    @classmethod
    def clean_notes(cls, v):
        return _sanitize_slide_text(v) or ''

    @field_validator('passage_text', 'directions', mode='before')
    @classmethod
    def clean_passage(cls, v):
        return _sanitize_slide_text(v)