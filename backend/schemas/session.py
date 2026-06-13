"""Request / response models for the interactive (human-in-the-loop) flow."""
from pydantic import BaseModel
from typing import Optional

from schemas.extracted_page import Annotation


# ── per-page extraction views ────────────────────────────────────────────────

class PageItemView(BaseModel):
    """One selectable chunk of a page (typically a single question)."""
    id:      str
    label:   str
    preview: str
    text:    str
    kind:    str          # "question" | "intro"


class PageExtractionView(BaseModel):
    """A review-friendly projection of one page's extraction for the UI."""
    page_number:        int
    status:             str                       # pending / approved / skipped
    content_type:       str
    main_text:          str
    diagrams_described: Optional[str] = None
    table_description:  Optional[str] = None
    has_table:          bool = False
    instructor_notes:   Optional[str] = None
    detected_language:  Optional[str] = None
    should_skip:        bool = False
    annotations:        list[Annotation] = []
    last_feedback:      Optional[str] = None
    # Convenience: detected question count (helps the UI show "10 questions").
    question_count:     int = 0
    # Per-page selection (human-in-the-loop "what goes into the PPT").
    items:              list[PageItemView] = []   # empty = all-or-nothing page
    intent_mode:        str = "all"               # "all" | "choose"
    selected_item_ids:  list[str] = []
    page_instruction:   Optional[str] = None


class StartSessionResponse(BaseModel):
    session_id:  str
    total_pages: int
    pages:       list[PageExtractionView]
    analytics:   Optional[dict] = None


class ReExtractRequest(BaseModel):
    feedback: str


class PageStatusRequest(BaseModel):
    status: str   # "approved" | "skipped" | "pending"


class PageIntentRequest(BaseModel):
    """What the user decided should go into the PPT from this page."""
    mode:              str = "all"          # "all" | "choose"
    selected_item_ids: list[str] = []
    instruction:       Optional[str] = None


# ── slide plan views ──────────────────────────────────────────────────────────

class SlideOutlineView(BaseModel):
    slide_number:    int
    title:           str
    template:        str
    source_pages:    list[int] = []
    key_points:      list[str] = []
    include_diagram: bool = False
    emphasis:        list[str] = []
    analytics:       Optional[dict] = None


class PlanResponse(BaseModel):
    session_id:   str
    total_slides: int
    slides:       list[SlideOutlineView]
    analytics:    Optional[dict] = None


class SlideRewriteRequest(BaseModel):
    feedback: str


class SlideEditRequest(BaseModel):
    """Direct, non-AI edits the user makes to a planned slide."""
    title:       Optional[str] = None
    key_points:  Optional[list[str]] = None
    template:    Optional[str] = None


class AddSlideRequest(BaseModel):
    """Insert a new slide drawn from a given source page."""
    after_slide_number: int
    source_page:        int
    title:              Optional[str] = None
    feedback:           Optional[str] = None   # what to put on it


class ReorderRequest(BaseModel):
    """New slide order, given as the current slide_numbers in the desired order."""
    order: list[int]
