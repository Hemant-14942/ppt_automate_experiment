"""Schemas used by the Visual Critic agent."""
from typing import Optional
from pydantic import BaseModel
from schemas.slide_plan import TemplateType


class VisualIssue(BaseModel):
    """One specific defect found on a slide image."""
    type:     str   # "text_overflow" | "misalignment" | "wrong_layout" |
                    # "missing_content" | "off_screen" | "letter_option_mismatch" |
                    # "decorative_overlap" | "blank_area" | "other"
    severity: str   # "high" | "medium" | "low"
    where:    str   # short human description of where on the slide


class SlideCritique(BaseModel):
    """
    Visual critic's verdict for one slide.

    The critic looks at the rendered slide image and decides:
      - is the slide visually broken in some way?
      - if yes, should we retry (rewrite content / change layout)?
      - what hint to pass back to the writer for a better second attempt?
    """
    slide_number:      int
    overall_score:     int                       # 1 (broken) – 10 (perfect)
    issues:            list[VisualIssue] = []
    should_retry:      bool                       # true ⇒ trigger a rewrite
    suggested_layout:  Optional[TemplateType] = None   # if layout was wrong
    content_fix_hint:  Optional[str] = None            # plain-English hint
                                                       # to inject in writer prompt
