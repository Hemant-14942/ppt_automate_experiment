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

    @field_validator('main_text', mode='before')
    @classmethod
    def clean_main_text(cls, v):
        return _sanitize_text(v) or ''

    @field_validator('diagrams_described', 'instructor_notes', 'table_description', mode='before')
    @classmethod
    def clean_optional_text(cls, v):
        return _sanitize_text(v)
