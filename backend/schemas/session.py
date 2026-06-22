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


class FigureView(BaseModel):
    """A detected diagram/figure/formula on a page, in a UI-friendly shape.

    Seeded from the AI extraction, then user-editable (label, question link,
    image-vs-text choice). `bbox` is {"x","y","w","h"} in 0-100 percentages.
    """
    id:           str
    description:  str
    belongs_to:   Optional[str] = None
    diagram_type: Optional[str] = None
    bbox:         Optional[dict] = None
    position:     Optional[str] = None
    label:        str = ""                 # short user-facing label
    use_mode:     str = "image"            # "image" (crop) | "text" (description)
    source:       str = "ai"               # "ai" | "manual" | "gallery"
    has_crop:     bool = False             # true when a usable bbox exists
    included:     bool = True              # false = excluded, won't reach the deck
    placement:    str = "own_slide"        # "own_slide" | "on_slide" (with question)
    size:         str = "medium"           # "small" | "medium" | "large" render size
    align:        str = "right"            # "left" | "center" | "right" position
    attached_slide_uid: Optional[str] = None  # pin to a specific slide (SlideOutline.uid)
    gallery_id:   Optional[str] = None     # set when source == "gallery"
    rev:          int = 0                  # bumps when the bbox changes (cache-bust)


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
    # Detected diagrams / figures / standalone formulas on this page.
    figures:            list[FigureView] = []


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


class FigureBBox(BaseModel):
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0


class FigureUpdateRequest(BaseModel):
    """User edits to a detected figure (all optional — only sent fields change)."""
    label:       Optional[str] = None
    belongs_to:  Optional[str] = None
    use_mode:    Optional[str] = None       # "image" | "text"
    included:    Optional[bool] = None      # exclude/include from the deck
    placement:   Optional[str] = None       # "own_slide" | "on_slide"
    size:        Optional[str] = None       # "small" | "medium" | "large"
    align:       Optional[str] = None       # "left" | "center" | "right"
    # Pin/unpin to a specific slide. "" or null detaches; any other value attaches.
    attached_slide_uid: Optional[str] = None
    bbox:        Optional[FigureBBox] = None # user-adjusted crop region (0-100 %)


class AddFigureRequest(BaseModel):
    """Manually add a figure the AI missed, by drawing a box on the page."""
    bbox:         FigureBBox
    label:        Optional[str] = None
    belongs_to:   Optional[str] = None
    diagram_type: Optional[str] = None
    description:  Optional[str] = None
    use_mode:     Optional[str] = None       # defaults to "image"
    placement:    Optional[str] = None       # defaults to "own_slide"


# ── slide plan views ──────────────────────────────────────────────────────────

class SlideOutlineView(BaseModel):
    slide_number:    int
    title:           str
    template:        str
    uid:             str = ""
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


# ── image gallery ─────────────────────────────────────────────────────────────

class GalleryImageView(BaseModel):
    """One image in the session gallery (stored as base64 in session memory)."""
    id:          str
    label:       str
    source:      str            # "crop" | "generated" | "edited"
    mime:        str            # "image/png"
    prompt:      Optional[str] = None
    parent_id:   Optional[str] = None   # edit history chain
    figure_ref:  Optional[dict] = None  # {"page": int, "id": str} for PDF crops
    created_at:  float


class GalleryResponse(BaseModel):
    images: list[GalleryImageView]


class GallerySaveRequest(BaseModel):
    """Save a detected figure crop to the gallery."""
    page:       int
    figure_id:  str
    label:      Optional[str] = None


class GalleryGenerateRequest(BaseModel):
    """Generate a brand-new image from a text prompt (Imagen 3)."""
    prompt:  str
    label:   Optional[str] = None


class GalleryEditRequest(BaseModel):
    """Edit an existing gallery image with a natural-language instruction."""
    image_id:  str
    prompt:    str
    label:     Optional[str] = None
