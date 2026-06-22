"""
In-memory session store for the interactive (human-in-the-loop) pipeline.

The interactive flow keeps intermediate state between user actions:

    upload → review per-page extraction → review slide plan → generate

Each browser flow owns one Session, keyed by a UUID. State lives in process
memory only — it is ephemeral by design (a refresh / server restart clears it).
A background sweeper drops sessions older than SESSION_TTL_SECONDS so long-lived
servers don't leak memory or temp PDFs.

This is intentionally simple (a dict + a lock). For multi-worker / horizontal
scaling this would move to Redis, but a single uvicorn worker is the current
deployment shape.
"""
from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass, field
from typing import Optional

from schemas.extracted_page import ExtractedPage
from schemas.slide_plan import FullSlidePlan, SlideOutline
from schemas.request import PDFContext


SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(60 * 60)))  # 1 hour
_SWEEP_EVERY_SECONDS = 300


# Per-page review status set by the user as they walk the carousel.
PAGE_PENDING = "pending"
PAGE_APPROVED = "approved"
PAGE_SKIPPED = "skipped"


# How the user wants this page reflected in the PPT.
INTENT_ALL = "all"        # include everything the AI read
INTENT_CHOOSE = "choose"  # include only selected_item_ids


@dataclass
class PageState:
    """Everything we hold for one source PDF page during review."""
    page_number: int
    base64: str
    mime_type: str
    extraction: Optional[ExtractedPage] = None
    status: str = PAGE_PENDING
    # Free-text the user typed to correct this page's extraction (latest only).
    last_feedback: Optional[str] = None
    # Per-page "what goes into the PPT" decision.
    intent_mode: str = INTENT_ALL
    selected_item_ids: list[str] = field(default_factory=list)
    page_instruction: Optional[str] = None
    # Detected diagrams / figures for this page, as user-editable dicts. Seeded
    # from the AI extraction (extraction.figures) and then mutated by the user
    # (label, question attachment, image-vs-text choice). Kept as plain dicts so
    # the in-memory store stays simple and JSON-friendly. See session_routes for
    # the dict shape and the FigureView it maps to.
    figures: list[dict] = field(default_factory=list)


@dataclass
class Session:
    session_id: str
    pdf_path: str
    context: PDFContext
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    pages: dict[int, PageState] = field(default_factory=dict)

    # Populated at the planning stage.
    strategy: object = None
    slide_plan: Optional[FullSlidePlan] = None

    # Populated at generation.
    output_filename: Optional[str] = None
    # Template chosen by the user in the template-picker step (filename, not full path).
    # None → falls back to the default Common Template.
    chosen_template: Optional[str] = None
    # Cumulative TokenTracker.report_dict() data across this multi-request flow.
    analytics: Optional[dict] = None

    # Image gallery — cropped, generated, and AI-edited images stored as base64
    # in session memory (no disk writes needed; same pattern as page images).
    # Each entry is a dict matching the GalleryImageView schema.
    gallery: list[dict] = field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = time.time()

    # ── convenience views ────────────────────────────────────────────────────
    def approved_pages(self) -> list[ExtractedPage]:
        """Extractions for pages the user kept (approved & not skipped)."""
        out: list[ExtractedPage] = []
        for n in sorted(self.pages):
            ps = self.pages[n]
            if ps.status != PAGE_SKIPPED and ps.extraction is not None:
                out.append(ps.extraction)
        return out

    def curated_pages(self) -> list[ExtractedPage]:
        """
        Kept pages, with the user's per-page selection applied.

        For pages in CHOOSE mode we replace main_text with ONLY the selected
        items so the planner and writer never see — and therefore never build
        slides from — content the user excluded. A free-text page instruction
        is folded into instructor_notes so downstream agents respect it.
        """
        # Local import avoids a circular import at module load time.
        from pipeline.page_items import split_page_items

        out: list[ExtractedPage] = []
        for n in sorted(self.pages):
            ps = self.pages[n]
            if ps.status == PAGE_SKIPPED or ps.extraction is None:
                continue

            ex = ps.extraction
            new_text = ex.main_text
            note = ex.instructor_notes or ""
            annotations = list(ex.annotations or [])

            if ps.intent_mode == INTENT_CHOOSE and ps.selected_item_ids:
                items = split_page_items(ps.page_number, ex.main_text)
                chosen = [it for it in items if it["id"] in set(ps.selected_item_ids)]
                if chosen:
                    new_text = "\n\n".join(it["text"] for it in chosen)
                    # The human's page-review choice is the final source of truth.
                    # Old PDF marks from extraction must not bring deselected items
                    # back into the plan or override the selected question count.
                    annotations = []
                    note = (
                        note
                        + "\nUSER_SELECTED_ITEMS_OVERRIDE: The human selected the "
                        "items for this page after AI extraction. Ignore extracted "
                        "PDF annotations for this page; plan only from main_text."
                    ).strip()

            if ps.page_instruction and ps.page_instruction.strip():
                note = (note + "\n" + ps.page_instruction.strip()).strip()

            if (
                new_text != ex.main_text
                or note != (ex.instructor_notes or "")
                or annotations != list(ex.annotations or [])
            ):
                ex = ex.model_copy(update={
                    "main_text": new_text,
                    "instructor_notes": note or None,
                    "annotations": annotations,
                })
            out.append(ex)
        return out

    def all_pages_reviewed(self) -> bool:
        return all(ps.status != PAGE_PENDING for ps in self.pages.values())


class SessionStore:
    """Thread-safe in-memory session registry with TTL sweeping."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._last_sweep = time.time()

    def put(self, session: Session) -> None:
        with self._lock:
            self._sessions[session.session_id] = session
            self._maybe_sweep_locked()

    def get(self, session_id: str) -> Optional[Session]:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is not None:
                s.touch()
            return s

    def delete(self, session_id: str) -> None:
        with self._lock:
            s = self._sessions.pop(session_id, None)
        if s is not None:
            _safe_remove(s.pdf_path)

    def _maybe_sweep_locked(self) -> None:
        now = time.time()
        if now - self._last_sweep < _SWEEP_EVERY_SECONDS:
            return
        self._last_sweep = now
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.updated_at > SESSION_TTL_SECONDS
        ]
        for sid in expired:
            s = self._sessions.pop(sid, None)
            if s is not None:
                _safe_remove(s.pdf_path)
        if expired:
            print(f"  [session] swept {len(expired)} expired session(s)")


def _safe_remove(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


# Module-level singleton used by the API routes.
store = SessionStore()
