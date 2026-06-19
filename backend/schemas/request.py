"""Defines what the API expects from the client."""
from pydantic import BaseModel
from typing import Optional


class AnnotationItem(BaseModel):
    """What each annotation type means in this specific PDF."""
    id:          str
    type:        str                    # "circle", "tick", etc.
    label:       str
    selected:    bool
    reason:      Optional[str] = None
    customName:  Optional[str] = None   # only for 'other'


class PDFContext(BaseModel):
    """Everything the DPT person fills in the form."""
    batch:         str                              # "JEE 2025 Batch A"
    purpose:       str                              # "Revision" / "Lecture notes" / "DPP"
    subject:       str                              # "Physics" / "Chemistry"
    class_level:   str                              # "Class 11-12" / "Competitive exam"
    language:      str = "English"                  # "English" / "Hindi" / "Hinglish"
    annotations:   list[AnnotationItem] = []
    extra_context: Optional[str] = None             # free text


class GenerateResponse(BaseModel):
    """What the API returns after processing."""
    status:        str                   # "success" / "error"
    job_id:        Optional[str] = None
    filename:      Optional[str] = None
    download_url:  Optional[str] = None
    preview_url:   Optional[str] = None
    total_pages:   Optional[int] = None
    total_slides:  Optional[int] = None
    message:       Optional[str] = None
    # Which reference template file was used for this deck.
    template_used: Optional[str] = None
    # Token usage / cost report (model-aware) for the frontend analytics view.
    analytics:     Optional[dict] = None