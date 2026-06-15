"""Defines what Gemini Vision returns for each PDF page."""

import re
from pydantic import BaseModel, field_validator
from typing import Optional
from enum import Enum
from schemas.text_sanitize import restore_symbols, strip_control_chars


class ContentType(str, Enum):
    text_heavy   = "text_heavy"
    diagram      = "diagram"
    mixed        = "mixed"
    table        = "table"
    mostly_blank = "mostly_blank"


class AnnotationType(str, Enum):
    circle      = "circle"
    underline   = "underline"
    tick        = "tick"
    cross       = "cross"
    highlight   = "highlight"
    handwritten = "handwritten"
    other       = "other"


class Annotation(BaseModel):
    type:        AnnotationType
    target:      str
    instruction: str


# ── Diagram / figure detection (Phase 1 — diagrams & formulas) ────────────────
#
# A page image is already sent to Gemini Vision during extraction. In addition
# to the text, we now ask the model to locate every diagram / figure / standalone
# formula on the page and report:
#   • a short description (what it shows)
#   • which question/section it belongs to (so the UI can link figure → question)
#   • a rough bounding box (so we can CROP that region out of the page image)
#
# IMPORTANT: Gemini bounding boxes are APPROXIMATE (±5-10%). They are a guide for
# cropping, never pixel-exact — the UI surfaces them as an editable estimate.


class DiagramKind(str, Enum):
    circuit   = "circuit"     # electrical / electronic circuit
    geometry  = "geometry"    # shapes, angles, constructions
    graph     = "graph"       # plotted axes / bar / pie / line
    formula   = "formula"     # standalone equation / expression block
    flowchart = "flowchart"   # boxes + arrows / process flow
    figure    = "figure"      # generic labelled illustration (biology, maps, …)
    other     = "other"


class BoundingBox(BaseModel):
    """Region on the page as PERCENTAGES of page width/height (0-100).

    (x, y) is the TOP-LEFT corner; (w, h) is the size. Percentages keep the box
    resolution-independent so the same numbers work whether the page was rendered
    at 150 or 250 DPI.
    """
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0


class DiagramRegion(BaseModel):
    description:  str
    # Which question/section this figure illustrates, e.g. "Q.15", "theory",
    # "Passage". Left as a free string because source numbering varies wildly.
    belongs_to:   Optional[str] = None
    # One of DiagramKind values; kept as a plain string so a slightly off label
    # from the model never fails JSON parsing (normalised downstream).
    diagram_type: Optional[str] = None
    bbox:         Optional[BoundingBox] = None
    # Where it sits relative to the question: "below_stem" | "above_options" |
    # "standalone" | "inline". Hint for slide layout in later phases.
    position:     Optional[str] = None

    @field_validator('description', mode='before')
    @classmethod
    def clean_description(cls, v):
        return _sanitize_text(v) or ''


def _sanitize_text(text: str | None) -> str | None:
    """Strip control-character artifacts that leak from docx-sourced PDFs.

    Symbols the model mangles (₹, ×, …) are restored FIRST so a Word-escaped
    "_x20B9_" becomes ₹ rather than being deleted as a control sequence.
    """
    if not text:
        return text
    cleaned = restore_symbols(text)
    cleaned = strip_control_chars(cleaned)
    cleaned = re.sub(r'[ \t]{3,}', '  ', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


class ExtractedPage(BaseModel):
    page_number:        int
    content_type:       ContentType
    main_text:          str
    diagrams_described: Optional[str] = None
    annotations:        list[Annotation] = []
    instructor_notes:   Optional[str] = None
    should_skip:        bool
    has_table:          bool = False
    table_description:  Optional[str] = None
    detected_language:  Optional[str] = None   # "hi" / "en" / "mixed"
    # Diagrams / figures / standalone formulas detected on the page, each with a
    # rough bounding box for cropping. Defaults to empty so text-only pages and
    # any older callers are unaffected.
    figures:            list[DiagramRegion] = []

    @field_validator('main_text', mode='before')
    @classmethod
    def clean_main_text(cls, v):
        return _sanitize_text(v) or ''

    @field_validator('diagrams_described', 'instructor_notes', 'table_description', mode='before')
    @classmethod
    def clean_optional_text(cls, v):
        return _sanitize_text(v)
