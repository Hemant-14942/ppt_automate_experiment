"""
Interactive (human-in-the-loop) API.

Flow:
    1. POST   /session/start                       upload PDF + context → extract all pages
    2. GET    /session/{sid}/page-image/{n}        page render for the carousel
    3. POST   /session/{sid}/page/{n}/re-extract   correct one page with feedback
    4. POST   /session/{sid}/page/{n}/status       approve / skip a page
    5. POST   /session/{sid}/plan                  build slide plan from approved pages
    6. POST   /session/{sid}/slide/{n}/rewrite     AI-rewrite one planned slide
    7. PATCH  /session/{sid}/slide/{n}             direct edit (title/points/template)
    8. DELETE /session/{sid}/slide/{n}             remove a planned slide
    9. POST   /session/{sid}/slide/add             insert a slide from a page
   10. POST   /session/{sid}/generate             write slides + build the .pptx
   11. DELETE /session/{sid}                       drop the session

State lives in pipeline.session_store (in-memory, TTL-swept).
"""
import os
import re
import time
import uuid
import json
import base64
import asyncio

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from schemas.request import PDFContext, GenerateResponse
from schemas.slide_plan import FullSlidePlan, SlideOutline, TemplateType
from schemas.slide_content import SlideContent, SlideFigure
from schemas.session import (
    PageExtractionView,
    PageItemView,
    FigureView,
    FigureUpdateRequest,
    AddFigureRequest,
    StartSessionResponse,
    ReExtractRequest,
    PageStatusRequest,
    PageIntentRequest,
    SlideOutlineView,
    PlanResponse,
    SlideRewriteRequest,
    SlideEditRequest,
    AddSlideRequest,
    ReorderRequest,
    GalleryImageView,
    GalleryResponse,
    GallerySaveRequest,
    GalleryGenerateRequest,
    GalleryEditRequest,
)
from pipeline.session_store import (
    store,
    Session,
    PageState,
    PAGE_PENDING,
    PAGE_APPROVED,
    PAGE_SKIPPED,
    INTENT_ALL,
    INTENT_CHOOSE,
)
from pipeline.page_items import split_page_items
from pipeline.image_crop import crop_page_region
from pipeline.pdf_loader import pdf_to_base64_images
from agents.extractor import extract_single_page_async, extract_all_pages_async
from agents.profiler import profile_deck
from agents.planner import plan_slides, replan_single_slide
from agents.writer import write_all_slides_async
from pipeline.ppt_generator import generate_pptx
from pipeline.fit_engine import reflow_slides, label_continuation_titles
from pipeline.slide_cleanup import drop_placeholder_slides, dedupe_tables
from agents.qc_agent import run_qc, auto_fix
from pipeline.token_tracker import TokenTracker
from config import UPLOAD_DIR, OUTPUT_DIR, STORAGE_BACKEND, TEMPLATE_PPTX

_REFS_DIR = os.path.dirname(TEMPLATE_PPTX)

# Reuse the Drive download + s3 helpers already implemented in routes.py.
from api.routes import _download_public_drive_pdf
from storage.s3_storage import upload_file_to_s3, create_presigned_download_url


router = APIRouter(prefix="/session")

_VALID_STATUSES = {PAGE_PENDING, PAGE_APPROVED, PAGE_SKIPPED}

# Reused by the UI badge — quick count of numbered questions on a page.
_Q_NUMBER_RE = re.compile(r'(?:^|\n)\s*(?:Q\.?\s*)?(\d{1,3})[.)]\s+\S', re.MULTILINE)


def _count_questions(text: str | None) -> int:
    if not text:
        return 0
    return len({
        int(m.group(1)) for m in _Q_NUMBER_RE.finditer(text)
        if 1 <= int(m.group(1)) <= 500
    })


def _parse_context(context_json: str) -> PDFContext:
    try:
        return PDFContext(**json.loads(context_json))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid form data: {e}")


def _merge_analytics(existing: dict | None, update: dict) -> dict:
    """Merge TokenTracker.report_dict() output across separate session requests."""
    if existing is None:
        return update

    merged = {
        "elapsed_seconds": round(
            existing.get("elapsed_seconds", 0) + update.get("elapsed_seconds", 0),
            2,
        ),
        "pricing_note": update.get("pricing_note") or existing.get("pricing_note"),
        "totals": dict(existing.get("totals", {})),
        "rows": [],
    }

    total_keys = (
        "attempts", "responses", "failures", "input_tokens", "output_tokens",
        "thinking_tokens", "total_tokens", "cost_usd",
    )
    for key in total_keys:
        merged["totals"][key] = (
            existing.get("totals", {}).get(key, 0)
            + update.get("totals", {}).get(key, 0)
        )
    merged["totals"]["cost_usd"] = round(merged["totals"]["cost_usd"], 6)

    by_key: dict[tuple[str, str], dict] = {}
    for row in existing.get("rows", []) + update.get("rows", []):
        key = (row.get("stage", "other"), row.get("model", "unknown"))
        acc = by_key.setdefault(key, {
            "stage": key[0],
            "model": key[1],
            "attempts": 0,
            "responses": 0,
            "failures": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
        })
        for metric in total_keys:
            acc[metric] += row.get(metric, 0)
        acc["cost_usd"] = round(acc["cost_usd"], 6)

    merged["rows"] = sorted(by_key.values(), key=lambda r: (r["stage"], r["model"]))
    return merged


def _record_session_analytics(
    session: Session,
    tracker: TokenTracker,
    started: float,
    label: str,
) -> dict:
    elapsed = time.monotonic() - started
    print(tracker.summary(elapsed))
    session.analytics = _merge_analytics(session.analytics, tracker.report_dict(elapsed))
    print(
        f"  [session {session.session_id}] {label} cost so far: "
        f"${session.analytics['totals']['cost_usd']:.4f} USD"
    )
    return session.analytics


_DIAGRAM_TYPE_LABELS = {
    "circuit": "Circuit", "geometry": "Figure", "graph": "Graph",
    "formula": "Formula", "flowchart": "Flowchart", "figure": "Figure",
    "other": "Diagram",
}


def _default_figure_label(belongs_to: str | None, dtype: str | None) -> str:
    """Build a short, human label like 'Q.15 · Circuit' for a detected figure."""
    kind = _DIAGRAM_TYPE_LABELS.get((dtype or "").lower(), "Diagram")
    who = (belongs_to or "").strip()
    if who and who.lower() not in ("standalone", "theory", "passage"):
        return f"{who} · {kind}"
    if who:
        return f"{who.capitalize()} · {kind}"
    return kind


def _seed_figures_from_extraction(ps: PageState) -> None:
    """(Re)build ps.figures from the AI extraction's `figures` list."""
    ex = ps.extraction
    figs: list[dict] = []
    for i, f in enumerate(getattr(ex, "figures", None) or []):
        bbox = None
        if getattr(f, "bbox", None) is not None:
            bbox = {"x": f.bbox.x, "y": f.bbox.y, "w": f.bbox.w, "h": f.bbox.h}
        has_crop = bool(bbox and bbox.get("w", 0) > 0 and bbox.get("h", 0) > 0)
        figs.append({
            "id": f"p{ps.page_number}_fig{i}",
            "description": f.description or "",
            "belongs_to": f.belongs_to,
            "diagram_type": f.diagram_type,
            "bbox": bbox,
            "position": f.position,
            "label": _default_figure_label(f.belongs_to, f.diagram_type),
            # Default to showing the real image when we have a crop, else the
            # text description (Option A) is the only sensible choice.
            "use_mode": "image" if has_crop else "text",
            "source": "ai",
            "has_crop": has_crop,
            "included": True,
            "placement": "own_slide",
            "size": "medium",
            "align": "right",
            "attached_slide_uid": None,
            "rev": 0,
        })
    ps.figures = figs


def _figure_views(ps: PageState) -> list[FigureView]:
    return [FigureView(**f) for f in (ps.figures or [])]


def _page_view(ps: PageState) -> PageExtractionView:
    ex = ps.extraction
    if ex is None:
        return PageExtractionView(
            page_number=ps.page_number,
            status=ps.status,
            content_type="mostly_blank",
            main_text="",
            should_skip=True,
            last_feedback=ps.last_feedback,
            intent_mode=ps.intent_mode,
            selected_item_ids=list(ps.selected_item_ids),
            page_instruction=ps.page_instruction,
            figures=_figure_views(ps),
        )
    ct = ex.content_type.value if hasattr(ex.content_type, "value") else str(ex.content_type)
    items = split_page_items(ps.page_number, ex.main_text)
    return PageExtractionView(
        page_number=ps.page_number,
        status=ps.status,
        content_type=ct,
        main_text=ex.main_text or "",
        diagrams_described=ex.diagrams_described,
        table_description=ex.table_description,
        has_table=bool(ex.has_table),
        instructor_notes=ex.instructor_notes,
        detected_language=ex.detected_language,
        should_skip=bool(ex.should_skip),
        annotations=list(ex.annotations or []),
        last_feedback=ps.last_feedback,
        question_count=_count_questions(ex.main_text),
        items=[PageItemView(**it) for it in items],
        intent_mode=ps.intent_mode,
        selected_item_ids=list(ps.selected_item_ids),
        page_instruction=ps.page_instruction,
        figures=_figure_views(ps),
    )


def _outline_view(o: SlideOutline, analytics: dict | None = None) -> SlideOutlineView:
    return SlideOutlineView(
        slide_number=o.slide_number,
        title=o.title,
        template=o.template.value if hasattr(o.template, "value") else str(o.template),
        uid=getattr(o, "uid", "") or "",
        source_pages=list(o.source_pages or []),
        key_points=list(o.key_points or []),
        include_diagram=bool(o.include_diagram),
        emphasis=list(o.emphasis or []),
        analytics=analytics,
    )


def _require(session_id: str) -> Session:
    s = store.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return s


# ── 1. start ──────────────────────────────────────────────────────────────────

@router.post("/start", response_model=StartSessionResponse)
async def start_session(
    context_json: str = Form(...),
    pdf_file: UploadFile | None = File(None),
    pdf_url: str | None = Form(None),
):
    """Upload a PDF (file or public Drive URL) + context, render pages, extract all."""
    context = _parse_context(context_json)

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    session_id = str(uuid.uuid4())
    pdf_path = os.path.join(UPLOAD_DIR, f"{session_id}.pdf")

    if pdf_file is not None:
        if not (pdf_file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are accepted")
        with open(pdf_path, "wb") as f:
            f.write(await pdf_file.read())
    elif pdf_url and pdf_url.strip():
        await asyncio.to_thread(_download_public_drive_pdf, pdf_url.strip(), pdf_path)
    else:
        raise HTTPException(status_code=400, detail="Provide a pdf_file or pdf_url")

    # Render every page to an image (kept in memory for the carousel).
    pages = await asyncio.to_thread(pdf_to_base64_images, pdf_path)
    if not pages:
        _safe_remove(pdf_path)
        raise HTTPException(status_code=400, detail="Could not read any pages from the PDF")

    session = Session(session_id=session_id, pdf_path=pdf_path, context=context)
    for p in pages:
        session.pages[p["page_number"]] = PageState(
            page_number=p["page_number"],
            base64=p["base64"],
            mime_type=p["mime_type"],
        )

    # First-pass extraction of ALL pages in parallel (keep skipped so the user
    # can still see & decide). We re-run extraction here rather than calling the
    # batch helper so blank pages aren't silently dropped from the review.
    tracker = TokenTracker()
    tracker.activate()
    started = time.monotonic()
    extractions = await extract_all_pages_async(pages, context)
    by_num = {e.page_number: e for e in extractions}
    for n, ps in session.pages.items():
        ps.extraction = by_num.get(n)
        # Pre-suggest skip for pages the model flagged blank; user can override.
        if ps.extraction is None:
            ps.status = PAGE_PENDING  # no extraction yet → user reviews/re-extracts
        else:
            _seed_figures_from_extraction(ps)
    _record_session_analytics(session, tracker, started, "extraction")

    store.put(session)
    print(f"  [session {session_id}] started — {len(pages)} pages")

    return StartSessionResponse(
        session_id=session_id,
        total_pages=len(pages),
        pages=[_page_view(session.pages[n]) for n in sorted(session.pages)],
        analytics=session.analytics,
    )


# ── 2. page image ──────────────────────────────────────────────────────────────

@router.get("/{session_id}/page-image/{page_number}")
async def page_image(session_id: str, page_number: int):
    s = _require(session_id)
    ps = s.pages.get(page_number)
    if ps is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return Response(content=base64.b64decode(ps.base64), media_type=ps.mime_type)


# ── 3. re-extract one page ───────────────────────────────────────────────────

@router.post("/{session_id}/page/{page_number}/re-extract", response_model=PageExtractionView)
async def re_extract_page(session_id: str, page_number: int, body: ReExtractRequest):
    s = _require(session_id)
    ps = s.pages.get(page_number)
    if ps is None:
        raise HTTPException(status_code=404, detail="Page not found")

    tracker = TokenTracker()
    tracker.activate()
    started = time.monotonic()
    page_dict = {"page_number": ps.page_number, "base64": ps.base64, "mime_type": ps.mime_type}
    result = await extract_single_page_async(page_dict, s.context, feedback=body.feedback)

    ps.extraction = result
    ps.last_feedback = body.feedback
    ps.status = PAGE_PENDING  # needs re-approval after a change
    # Item ids are derived from the text, so a re-extract invalidates any
    # previous per-item selection — reset to "include all" for a clean review.
    ps.intent_mode = INTENT_ALL
    ps.selected_item_ids = []
    # Figures are re-derived from the fresh extraction (drops stale user edits
    # for this page, which is correct — the page content just changed).
    if result is not None:
        _seed_figures_from_extraction(ps)
    else:
        ps.figures = []
    _record_session_analytics(s, tracker, started, "re-extraction")
    s.touch()
    return _page_view(ps)


# ── 4. approve / skip ────────────────────────────────────────────────────────

@router.post("/{session_id}/page/{page_number}/status", response_model=PageExtractionView)
async def set_page_status(session_id: str, page_number: int, body: PageStatusRequest):
    s = _require(session_id)
    ps = s.pages.get(page_number)
    if ps is None:
        raise HTTPException(status_code=404, detail="Page not found")
    if body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")
    ps.status = body.status
    s.touch()
    return _page_view(ps)


# ── 4b. per-page intent (what goes into the PPT) ─────────────────────────────

@router.post("/{session_id}/page/{page_number}/intent", response_model=PageExtractionView)
async def set_page_intent(session_id: str, page_number: int, body: PageIntentRequest):
    s = _require(session_id)
    ps = s.pages.get(page_number)
    if ps is None:
        raise HTTPException(status_code=404, detail="Page not found")

    mode = body.mode if body.mode in (INTENT_ALL, INTENT_CHOOSE) else INTENT_ALL
    ps.intent_mode = mode
    ps.selected_item_ids = list(body.selected_item_ids) if mode == INTENT_CHOOSE else []
    instruction = (body.instruction or "").strip()
    ps.page_instruction = instruction or None
    s.touch()
    return _page_view(ps)


# ── 4c. diagrams / figures — crop preview + user edits ───────────────────────

def _find_figure(ps: PageState, figure_id: str) -> dict:
    for f in ps.figures or []:
        if f.get("id") == figure_id:
            return f
    raise HTTPException(status_code=404, detail="Figure not found")


@router.get("/{session_id}/page/{page_number}/figure/{figure_id}/crop")
async def figure_crop(session_id: str, page_number: int, figure_id: str):
    """Return the cropped diagram region as a PNG for the review UI preview.

    Gallery-sourced figures (source='gallery', gallery_id set) are served directly
    from the session gallery instead of re-cropping from the PDF page.
    """
    s = _require(session_id)
    ps = s.pages.get(page_number)
    if ps is None:
        raise HTTPException(status_code=404, detail="Page not found")
    fig = _find_figure(ps, figure_id)

    # Gallery figure — serve from in-memory gallery bytes
    gallery_id = fig.get("gallery_id")
    if gallery_id:
        gal = next((g for g in (s.gallery or []) if g["id"] == gallery_id), None)
        if not gal:
            raise HTTPException(status_code=404, detail="Gallery image not found")
        return Response(
            content=base64.b64decode(gal["base64"]),
            media_type=gal["mime"],
            headers={"Cache-Control": "no-store"},
        )

    png = await asyncio.to_thread(crop_page_region, ps.base64, fig.get("bbox"))
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.patch(
    "/{session_id}/page/{page_number}/figure/{figure_id}",
    response_model=PageExtractionView,
)
async def update_figure(
    session_id: str, page_number: int, figure_id: str, body: FigureUpdateRequest
):
    """Apply user edits to one detected figure (label / question link / mode)."""
    s = _require(session_id)
    ps = s.pages.get(page_number)
    if ps is None:
        raise HTTPException(status_code=404, detail="Page not found")
    fig = _find_figure(ps, figure_id)

    if body.label is not None:
        fig["label"] = body.label.strip()
    if body.belongs_to is not None:
        fig["belongs_to"] = body.belongs_to.strip() or None
    # A bbox edit can enable image mode (now there's a crop), so apply it first.
    if body.bbox is not None:
        bb = {"x": body.bbox.x, "y": body.bbox.y, "w": body.bbox.w, "h": body.bbox.h}
        usable = bb["w"] > 0.5 and bb["h"] > 0.5
        fig["bbox"] = bb
        fig["has_crop"] = bool(usable)
        fig["rev"] = int(fig.get("rev", 0)) + 1  # cache-bust the crop preview
    if body.use_mode is not None:
        mode = body.use_mode.strip().lower()
        if mode not in ("image", "text"):
            raise HTTPException(status_code=400, detail="use_mode must be 'image' or 'text'")
        # Can't choose the image if there's no crop to show.
        if mode == "image" and not fig.get("has_crop"):
            raise HTTPException(
                status_code=400,
                detail="No diagram crop available for this figure; use 'text'.",
            )
        fig["use_mode"] = mode
    if body.included is not None:
        fig["included"] = bool(body.included)
    if body.placement is not None:
        place = body.placement.strip().lower()
        if place not in ("own_slide", "on_slide"):
            raise HTTPException(status_code=400, detail="placement must be 'own_slide' or 'on_slide'")
        fig["placement"] = place
    if body.size is not None:
        size = body.size.strip().lower()
        if size not in ("small", "medium", "large"):
            raise HTTPException(status_code=400, detail="size must be 'small', 'medium' or 'large'")
        fig["size"] = size
    if body.align is not None:
        align = body.align.strip().lower()
        if align not in ("left", "center", "right"):
            raise HTTPException(status_code=400, detail="align must be 'left', 'center' or 'right'")
        fig["align"] = align
    if body.attached_slide_uid is not None:
        uid = body.attached_slide_uid.strip()
        # Empty string detaches; any non-empty value pins to that slide and the
        # figure must be included to actually reach the deck.
        fig["attached_slide_uid"] = uid or None
        if uid:
            fig["included"] = True

    s.touch()
    return _page_view(ps)


@router.post(
    "/{session_id}/page/{page_number}/figure",
    response_model=PageExtractionView,
)
async def add_figure(session_id: str, page_number: int, body: AddFigureRequest):
    """Manually add a figure the AI missed by drawing a box on the page image."""
    s = _require(session_id)
    ps = s.pages.get(page_number)
    if ps is None:
        raise HTTPException(status_code=404, detail="Page not found")

    bb = {"x": body.bbox.x, "y": body.bbox.y, "w": body.bbox.w, "h": body.bbox.h}
    has_crop = bb["w"] > 0.5 and bb["h"] > 0.5
    if not has_crop:
        raise HTTPException(status_code=400, detail="Drawn region is too small")

    # Stable unique id for manual figures on this page.
    existing = {f.get("id") for f in (ps.figures or [])}
    k = 0
    while f"p{page_number}_manual{k}" in existing:
        k += 1
    fig_id = f"p{page_number}_manual{k}"

    dtype = (body.diagram_type or "figure").strip().lower()
    label = (body.label or "").strip() or _default_figure_label(body.belongs_to, dtype)
    mode = (body.use_mode or "image").strip().lower()
    if mode not in ("image", "text"):
        mode = "image"
    place = (body.placement or "own_slide").strip().lower()
    if place not in ("own_slide", "on_slide"):
        place = "own_slide"

    ps.figures.append({
        "id": fig_id,
        "description": (body.description or "").strip(),
        "belongs_to": (body.belongs_to or "").strip() or None,
        "diagram_type": dtype,
        "bbox": bb,
        "position": "standalone",
        "label": label,
        "use_mode": mode if has_crop else "text",
        "source": "manual",
        "has_crop": has_crop,
        "included": True,
        "placement": place,
        "size": "medium",
        "align": "right",
        "attached_slide_uid": None,
        "rev": 0,
    })
    s.touch()
    return _page_view(ps)


@router.delete(
    "/{session_id}/page/{page_number}/figure/{figure_id}",
    response_model=PageExtractionView,
)
async def delete_figure(session_id: str, page_number: int, figure_id: str):
    """Permanently remove a figure from the page (vs. just excluding it)."""
    s = _require(session_id)
    ps = s.pages.get(page_number)
    if ps is None:
        raise HTTPException(status_code=404, detail="Page not found")
    before = len(ps.figures or [])
    ps.figures = [f for f in (ps.figures or []) if f.get("id") != figure_id]
    if len(ps.figures) == before:
        raise HTTPException(status_code=404, detail="Figure not found")
    s.touch()
    return _page_view(ps)


# ── image gallery ─────────────────────────────────────────────────────────────

@router.get("/{session_id}/gallery", response_model=GalleryResponse)
async def list_gallery(session_id: str):
    """Return all gallery images for a session (metadata only, no base64)."""
    s = _require(session_id)
    return GalleryResponse(images=[GalleryImageView(**g) for g in (s.gallery or [])])


@router.get("/{session_id}/gallery/{image_id}")
async def get_gallery_image(session_id: str, image_id: str):
    """Serve a gallery image as PNG bytes."""
    s = _require(session_id)
    img = next((g for g in (s.gallery or []) if g["id"] == image_id), None)
    if not img:
        raise HTTPException(status_code=404, detail="Gallery image not found")
    return Response(
        content=base64.b64decode(img["base64"]),
        media_type=img["mime"],
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.post("/{session_id}/gallery/from-figure", response_model=GalleryImageView)
async def save_figure_to_gallery(session_id: str, body: GallerySaveRequest):
    """Crop a detected figure and save it to the session gallery."""
    s = _require(session_id)
    ps = s.pages.get(body.page)
    if ps is None:
        raise HTTPException(status_code=404, detail="Page not found")
    fig = _find_figure(ps, body.figure_id)
    if not fig.get("has_crop") or not fig.get("bbox"):
        raise HTTPException(status_code=400, detail="This figure has no crop region")

    png = await asyncio.to_thread(crop_page_region, ps.base64, fig.get("bbox"))
    gid = str(uuid.uuid4())[:8]
    label = (body.label or fig.get("label") or "Cropped image").strip()
    entry = {
        "id": f"gal_{gid}",
        "label": label,
        "source": "crop",
        "base64": base64.b64encode(png).decode(),
        "mime": "image/png",
        "prompt": None,
        "parent_id": None,
        "figure_ref": {"page": body.page, "id": body.figure_id},
        "created_at": time.time(),
    }
    s.gallery.append(entry)
    s.touch()
    return GalleryImageView(**entry)


@router.post("/{session_id}/gallery/generate", response_model=GalleryImageView)
async def generate_gallery_image(session_id: str, body: GalleryGenerateRequest):
    """Generate a brand-new image from a text prompt (Imagen 3)."""
    from agents.image_studio import generate_image_from_prompt

    s = _require(session_id)
    try:
        png = await generate_image_from_prompt(body.prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image generation failed: {e}")

    gid = str(uuid.uuid4())[:8]
    label = (body.label or body.prompt[:60]).strip()
    entry = {
        "id": f"gal_{gid}",
        "label": label,
        "source": "generated",
        "base64": base64.b64encode(png).decode(),
        "mime": "image/png",
        "prompt": body.prompt,
        "parent_id": None,
        "figure_ref": None,
        "created_at": time.time(),
    }
    s.gallery.append(entry)
    s.touch()
    return GalleryImageView(**entry)


@router.post("/{session_id}/gallery/edit", response_model=GalleryImageView)
async def edit_gallery_image(session_id: str, body: GalleryEditRequest):
    """Edit an existing gallery image with a natural-language instruction."""
    from agents.image_studio import edit_image_with_gemini

    s = _require(session_id)
    parent = next((g for g in (s.gallery or []) if g["id"] == body.image_id), None)
    if not parent:
        raise HTTPException(status_code=404, detail="Gallery image not found")

    src_bytes = base64.b64decode(parent["base64"])
    try:
        edited = await edit_image_with_gemini(src_bytes, body.prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image editing failed: {e}")

    gid = str(uuid.uuid4())[:8]
    label = (body.label or parent["label"]).strip()
    entry = {
        "id": f"gal_{gid}",
        "label": label,
        "source": "edited",
        "base64": base64.b64encode(edited).decode(),
        "mime": "image/png",
        "prompt": body.prompt,
        "parent_id": parent["id"],
        "figure_ref": parent.get("figure_ref"),
        "created_at": time.time(),
    }
    s.gallery.append(entry)
    s.touch()
    return GalleryImageView(**entry)


@router.delete("/{session_id}/gallery/{image_id}", response_model=GalleryResponse)
async def delete_gallery_image(session_id: str, image_id: str):
    """Remove an image from the gallery."""
    s = _require(session_id)
    before = len(s.gallery)
    s.gallery = [g for g in s.gallery if g["id"] != image_id]
    if len(s.gallery) == before:
        raise HTTPException(status_code=404, detail="Gallery image not found")
    s.touch()
    return GalleryResponse(images=[GalleryImageView(**g) for g in s.gallery])


@router.post("/{session_id}/gallery/{image_id}/use-in-deck", response_model=PageExtractionView)
async def use_gallery_image_in_deck(session_id: str, image_id: str):
    """Add a gallery image as a figure on the first approved page.

    Creates a figure entry with source='gallery' and gallery_id pointing back to
    the gallery entry.  The figure then appears in the Images modal where the user
    can pin it to any slide.  At generation time _build_session_figures() uses the
    gallery base64 directly instead of cropping from the PDF page.
    """
    s = _require(session_id)
    gal = next((g for g in (s.gallery or []) if g["id"] == image_id), None)
    if not gal:
        raise HTTPException(status_code=404, detail="Gallery image not found")

    # Find first non-skipped page with an extraction
    approved = sorted(
        n for n, ps in s.pages.items()
        if ps.status != "skipped" and ps.extraction is not None
    )
    if not approved:
        raise HTTPException(status_code=400, detail="No approved pages — review pages first")

    target_page = approved[0]
    ps = s.pages[target_page]

    # Avoid duplicate — if this gallery image is already attached, return as-is
    existing = next((f for f in ps.figures if f.get("gallery_id") == image_id), None)
    if existing:
        return _page_view(ps)

    fig_id = f"p{target_page}_gal_{image_id[-8:]}"
    fig: dict = {
        "id":                 fig_id,
        "description":        gal["label"],
        "belongs_to":         None,
        "diagram_type":       "figure",
        "bbox":               None,
        "position":           "standalone",
        "label":              gal["label"],
        "use_mode":           "image",
        "source":             "gallery",
        "has_crop":           True,   # served via gallery bytes
        "gallery_id":         image_id,
        "included":           True,
        "placement":          "own_slide",
        "size":               "medium",
        "align":              "right",
        "attached_slide_uid": None,
        "rev":                0,
    }
    ps.figures.append(fig)
    s.touch()
    return _page_view(ps)


# ── figure → slide helpers (used at generation) ──────────────────────────────

def _build_session_figures(
    session: Session,
) -> tuple[dict[int, list[SlideFigure]], dict[str, list[SlideFigure]], list[SlideFigure]]:
    """
    Turn each page's INCLUDED figures into SlideFigure objects, cropping the
    image-mode ones to PNG files on disk.

    Returns (page_figures, uid_figures, deck_figures):
      • page_figures : {page_number: [SlideFigure]} — PDF figures placed by page.
      • uid_figures  : {slide_uid:   [SlideFigure]} — explicitly pinned by the user.
      • deck_figures : [SlideFigure] — gallery/studio images with no slide pin;
                       each gets its own slide just before the thank-you slide.
    A figure pinned to a slide is ONLY in uid_figures, never page_figures.
    """
    out: dict[int, list[SlideFigure]] = {}
    pinned: dict[str, list[SlideFigure]] = {}
    deck: list[SlideFigure] = []
    fig_dir = os.path.join(OUTPUT_DIR, "_figures", session.session_id)

    for n in sorted(session.pages):
        ps = session.pages[n]
        chosen = [f for f in (ps.figures or []) if f.get("included", True)]
        if not chosen:
            continue

        page_figs: list[SlideFigure] = []
        for f in chosen:
            label = (f.get("label") or "").strip() or "Diagram"
            want_image = f.get("use_mode") == "image" and f.get("has_crop")
            place = f.get("placement", "own_slide")
            if place not in ("own_slide", "on_slide"):
                place = "own_slide"
            size = f.get("size", "medium")
            if size not in ("small", "medium", "large"):
                size = "medium"
            align = f.get("align", "right")
            if align not in ("left", "center", "right"):
                align = "right"
            attached_uid = (f.get("attached_slide_uid") or "").strip() or None
            sf = SlideFigure(
                kind="image" if want_image else "text",
                label=label,
                belongs_to=f.get("belongs_to"),
                diagram_type=f.get("diagram_type"),
                description=f.get("description") or None,
                placement=place,
                size=size,
                align=align,
                attached_uid=attached_uid,
            )
            if want_image:
                try:
                    os.makedirs(fig_dir, exist_ok=True)
                    path = os.path.join(fig_dir, f"{f['id']}.png")
                    # Gallery-sourced figures use the stored base64 directly
                    # instead of re-cropping from the PDF page.
                    gallery_id = f.get("gallery_id")
                    if gallery_id:
                        gal = next(
                            (g for g in (session.gallery or []) if g["id"] == gallery_id),
                            None,
                        )
                        if gal:
                            png = base64.b64decode(gal["base64"])
                        else:
                            raise ValueError(f"Gallery image {gallery_id} not found")
                    else:
                        png = crop_page_region(ps.base64, f.get("bbox"))
                    with open(path, "wb") as fh:
                        fh.write(png)
                    sf.image_path = path
                except Exception as e:
                    # Cropping/lookup failed — degrade to text description.
                    print(f"  [session {session.session_id}] crop failed for {f.get('id')}: {e}")
                    sf.kind = "text"
                    sf.image_path = None

            if attached_uid:
                pinned.setdefault(attached_uid, []).append(sf)
            elif f.get("source") == "gallery":
                deck.append(sf)
            else:
                page_figs.append(sf)

        if page_figs:
            out[n] = page_figs
    return out, pinned, deck


def _figure_to_slide(sf: SlideFigure) -> SlideContent:
    return SlideContent(
        slide_number=0,  # renumbered after injection
        title=sf.label or "Diagram",
        bullets=[],
        diagram_description=sf.description,
        speaker_notes=(sf.description or ""),
        layout=TemplateType.figure_slide,
        figure=sf,
    )


def _thank_you_index(slides: list[SlideContent]) -> int | None:
    for i, sc in enumerate(slides):
        if sc.layout == TemplateType.thank_you_slide:
            return i
    return None


def _is_thank_you(sc: SlideContent) -> bool:
    return sc.layout == TemplateType.thank_you_slide


def _inject_figure_slides(
    slide_contents: list[SlideContent],
    page_figures: dict[int, list[SlideFigure]],
    uid_figures: dict[str, list[SlideFigure]] | None = None,
    deck_figures: list[SlideFigure] | None = None,
) -> list[SlideContent]:
    """
    Place each chosen figure relative to its target slide:

      • Figures pinned to a slide (uid_figures) go to the exact slide whose
        source_uid matches — surviving reflow/renumbering.
      • PDF figures are placed by page heuristics (page_figures).
      • Gallery/studio images without a pin become own slides before thank-you.

    For each figure:
      • placement == "on_slide" → embed on the matched slide (inline_figures).
      • placement == "own_slide" → a companion `figure_slide` right after it.

    Nothing is embedded on or inserted after the thank-you slide.
    """
    uid_figures = uid_figures or {}
    deck_figures = deck_figures or []
    if not page_figures and not uid_figures and not deck_figures:
        return slide_contents

    # Clear any LLM-produced inline figures (only we attach these).
    for sc in slide_contents:
        sc.inline_figures = []

    thank_idx = _thank_you_index(slide_contents)

    # Last slide index that references each page (page heuristic anchor).
    last_idx: dict[int, int] = {}
    for i, sc in enumerate(slide_contents):
        for p in (sc.source_pages or []):
            last_idx[p] = i

    # First/last slide index for each stable uid. Embedded figures go on the
    # FIRST slide of a (possibly split) run; companion slides after the LAST.
    first_uid_idx: dict[str, int] = {}
    last_uid_idx: dict[str, int] = {}
    for i, sc in enumerate(slide_contents):
        u = getattr(sc, "source_uid", "") or ""
        if not u:
            continue
        if u not in first_uid_idx:
            first_uid_idx[u] = i
        last_uid_idx[u] = i

    inserts: dict[int, list[SlideContent]] = {}
    before_thank_you: list[SlideContent] = [
        _figure_to_slide(sf) for sf in deck_figures
    ]

    def _companion_after(idx: int, sf: SlideFigure) -> None:
        if _is_thank_you(slide_contents[idx]):
            before_thank_you.append(_figure_to_slide(sf))
        else:
            inserts.setdefault(idx, []).append(_figure_to_slide(sf))

    # 1) Explicitly pinned figures — anchored by slide uid.
    for uid, figs in uid_figures.items():
        for sf in figs:
            if sf.placement == "on_slide" and uid in first_uid_idx:
                target = slide_contents[first_uid_idx[uid]]
                if _is_thank_you(target):
                    before_thank_you.append(_figure_to_slide(sf))
                else:
                    slide_contents[first_uid_idx[uid]].inline_figures.append(sf)
            elif uid in last_uid_idx:
                _companion_after(last_uid_idx[uid], sf)
            else:
                before_thank_you.append(_figure_to_slide(sf))

    # 2) Page-heuristic figures (PDF crops only — gallery goes via deck_figures).
    for page, figs in page_figures.items():
        idx = last_idx.get(page)
        for sf in figs:
            if idx is not None and sf.placement == "on_slide":
                if _is_thank_you(slide_contents[idx]):
                    before_thank_you.append(_figure_to_slide(sf))
                else:
                    slide_contents[idx].inline_figures.append(sf)
            elif idx is not None:
                _companion_after(idx, sf)
            else:
                before_thank_you.append(_figure_to_slide(sf))

    new_list: list[SlideContent] = []
    for i, sc in enumerate(slide_contents):
        if thank_idx is not None and i == thank_idx and before_thank_you:
            new_list.extend(before_thank_you)
            before_thank_you = []
        new_list.append(sc)
        if i in inserts:
            new_list.extend(inserts[i])

    if before_thank_you:
        new_list.extend(before_thank_you)

    for i, sc in enumerate(new_list, start=1):
        sc.slide_number = i
    return new_list


# ── 5. build plan ────────────────────────────────────────────────────────────

@router.post("/{session_id}/plan", response_model=PlanResponse)
async def build_plan(session_id: str):
    s = _require(session_id)
    # Curated pages apply each page's "what goes into the PPT" selection so the
    # planner only ever sees the content the user chose to include.
    approved = s.curated_pages()
    if not approved:
        raise HTTPException(
            status_code=400,
            detail="No pages approved. Approve at least one page before planning.",
        )

    tracker = TokenTracker()
    tracker.activate()
    started = time.monotonic()

    # Profile + plan run off the event loop (they use the sync Gemini client).
    s.strategy = await asyncio.to_thread(profile_deck, approved, s.context, None)
    s.slide_plan = await asyncio.to_thread(plan_slides, approved, s.context, s.strategy)
    _record_session_analytics(s, tracker, started, "planning")
    s.touch()

    return PlanResponse(
        session_id=session_id,
        total_slides=s.slide_plan.total_slides,
        slides=[_outline_view(o) for o in s.slide_plan.slides],
        analytics=s.analytics,
    )


@router.get("/{session_id}/plan", response_model=PlanResponse)
async def get_plan(session_id: str):
    s = _require(session_id)
    if s.slide_plan is None:
        raise HTTPException(status_code=400, detail="Plan not built yet")
    return PlanResponse(
        session_id=session_id,
        total_slides=s.slide_plan.total_slides,
        slides=[_outline_view(o) for o in s.slide_plan.slides],
        analytics=s.analytics,
    )


def _find_slide(s: Session, n: int) -> SlideOutline:
    if s.slide_plan is None:
        raise HTTPException(status_code=400, detail="Plan not built yet")
    for o in s.slide_plan.slides:
        if o.slide_number == n:
            return o
    raise HTTPException(status_code=404, detail=f"Slide {n} not found")


def _renumber(s: Session) -> None:
    for i, o in enumerate(s.slide_plan.slides, start=1):
        o.slide_number = i
    s.slide_plan.total_slides = len(s.slide_plan.slides)


# ── 6. AI rewrite one slide ──────────────────────────────────────────────────

@router.post("/{session_id}/slide/{slide_number}/rewrite", response_model=SlideOutlineView)
async def rewrite_slide(session_id: str, slide_number: int, body: SlideRewriteRequest):
    s = _require(session_id)
    outline = _find_slide(s, slide_number)
    tracker = TokenTracker()
    tracker.activate()
    started = time.monotonic()
    revised = await asyncio.to_thread(
        replan_single_slide, outline, s.curated_pages(), s.context, body.feedback
    )
    # Keep the stable uid so any figures attached to this slide stay attached
    # after an AI rewrite (replan returns a fresh outline with a new uid).
    revised.uid = outline.uid
    # Replace in place.
    idx = s.slide_plan.slides.index(outline)
    s.slide_plan.slides[idx] = revised
    _record_session_analytics(s, tracker, started, "slide rewrite")
    s.touch()
    return _outline_view(revised, analytics=s.analytics)


# ── 7. direct edit ───────────────────────────────────────────────────────────

@router.patch("/{session_id}/slide/{slide_number}", response_model=SlideOutlineView)
async def edit_slide(session_id: str, slide_number: int, body: SlideEditRequest):
    s = _require(session_id)
    outline = _find_slide(s, slide_number)
    if body.title is not None:
        outline.title = body.title
    if body.key_points is not None:
        outline.key_points = body.key_points
    if body.template is not None:
        try:
            outline.template = TemplateType(body.template)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid template: {body.template}")
    s.touch()
    return _outline_view(outline)


# ── 8. delete slide ──────────────────────────────────────────────────────────

@router.delete("/{session_id}/slide/{slide_number}", response_model=PlanResponse)
async def delete_slide(session_id: str, slide_number: int):
    s = _require(session_id)
    outline = _find_slide(s, slide_number)
    s.slide_plan.slides.remove(outline)
    _renumber(s)
    s.touch()
    return PlanResponse(
        session_id=session_id,
        total_slides=s.slide_plan.total_slides,
        slides=[_outline_view(o) for o in s.slide_plan.slides],
        analytics=s.analytics,
    )


# ── 9. add slide ─────────────────────────────────────────────────────────────

@router.post("/{session_id}/slide/add", response_model=PlanResponse)
async def add_slide(session_id: str, body: AddSlideRequest):
    s = _require(session_id)
    if s.slide_plan is None:
        raise HTTPException(status_code=400, detail="Plan not built yet")

    new_outline = SlideOutline(
        slide_number=body.after_slide_number + 1,
        title=body.title or "New slide",
        template=TemplateType.theory_slide,
        source_pages=[body.source_page],
        key_points=[],
        include_diagram=False,
        emphasis=[],
    )
    # If the user gave feedback, let the AI fill the new slide from the page.
    tracker = None
    started = None
    if body.feedback and body.feedback.strip():
        tracker = TokenTracker()
        tracker.activate()
        started = time.monotonic()
        try:
            new_outline = await asyncio.to_thread(
                replan_single_slide, new_outline, s.curated_pages(), s.context, body.feedback
            )
        except Exception as e:
            print(f"  [session] add-slide AI fill skipped ({e})")
        _record_session_analytics(s, tracker, started, "add-slide AI fill")

    # Insert after the requested slide. after_slide_number == 0 means "at the
    # very start"; an unknown number falls back to appending at the end.
    if body.after_slide_number <= 0:
        insert_at = 0
    else:
        insert_at = len(s.slide_plan.slides)
        for i, o in enumerate(s.slide_plan.slides):
            if o.slide_number == body.after_slide_number:
                insert_at = i + 1
                break
    s.slide_plan.slides.insert(insert_at, new_outline)
    _renumber(s)
    s.touch()
    return PlanResponse(
        session_id=session_id,
        total_slides=s.slide_plan.total_slides,
        slides=[_outline_view(o) for o in s.slide_plan.slides],
        analytics=s.analytics,
    )


# ── 9b. reorder slides ───────────────────────────────────────────────────────

@router.post("/{session_id}/slides/reorder", response_model=PlanResponse)
async def reorder_slides(session_id: str, body: ReorderRequest):
    s = _require(session_id)
    if s.slide_plan is None:
        raise HTTPException(status_code=400, detail="Plan not built yet")

    by_num = {o.slide_number: o for o in s.slide_plan.slides}
    if set(body.order) != set(by_num.keys()):
        raise HTTPException(
            status_code=400,
            detail="Reorder list must contain exactly the current slide numbers",
        )
    s.slide_plan.slides = [by_num[n] for n in body.order]
    _renumber(s)
    s.touch()
    return PlanResponse(
        session_id=session_id,
        total_slides=s.slide_plan.total_slides,
        slides=[_outline_view(o) for o in s.slide_plan.slides],
        analytics=s.analytics,
    )


# ── 10a. set chosen template ─────────────────────────────────────────────────

class TemplateSelectRequest(BaseModel):
    filename: str  # e.g. "Clat evening format.pptx"


@router.post("/{session_id}/template")
async def set_template(session_id: str, body: TemplateSelectRequest):
    """Store the user's chosen template filename in the session."""
    s = _require(session_id)
    candidate = os.path.join(_REFS_DIR, body.filename)
    if not os.path.exists(candidate):
        raise HTTPException(status_code=400, detail=f"Template not found: {body.filename}")
    s.chosen_template = body.filename
    s.touch()
    return {"status": "ok", "chosen_template": body.filename}


# ── 10. generate ─────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    template_filename: str | None = None


@router.post("/{session_id}/generate", response_model=GenerateResponse)
async def generate(session_id: str, body: GenerateRequest | None = None):
    s = _require(session_id)
    if s.slide_plan is None or not s.slide_plan.slides:
        raise HTTPException(status_code=400, detail="Build and approve a plan first")

    tracker = TokenTracker()
    tracker.activate()
    started = time.monotonic()

    approved = s.curated_pages()
    context = s.context

    safe_batch = (context.batch or "deck").replace(" ", "_").replace("/", "-")
    safe_subject = (context.subject or "slides").replace(" ", "_")
    output_filename = f"{safe_subject}_{safe_batch}_{context.purpose}_slides.pptx"

    # Make sure numbering is contiguous before writing.
    _renumber(s)

    # Write → cleanup → reflow → QC → build the .pptx (reuses pipeline modules).
    slide_contents = await write_all_slides_async(
        s.slide_plan, approved, context, {}, s.strategy
    )

    # Stamp each written slide with its plan outline's stable uid. The writer
    # keys slides by slide_number (matching the plan), so map back here. This
    # survives cleanup/reflow (deepcopy) and anchors per-slide figure attach.
    uid_by_num = {o.slide_number: o.uid for o in s.slide_plan.slides}
    for sc in slide_contents:
        sc.source_uid = uid_by_num.get(sc.slide_number, "")

    slide_contents, _ = drop_placeholder_slides(slide_contents)
    slide_contents, _ = dedupe_tables(slide_contents)
    slide_contents, _ = reflow_slides(slide_contents, s.strategy)
    slide_contents, _ = label_continuation_titles(slide_contents)
    slide_contents = auto_fix(slide_contents, run_qc(slide_contents))

    # Inject companion slides for the diagrams/figures the user kept, each placed
    # right after the question/section it belongs to (image crop or text).
    page_figures, uid_figures, deck_figures = await asyncio.to_thread(_build_session_figures, s)
    slide_contents = _inject_figure_slides(
        slide_contents, page_figures, uid_figures, deck_figures
    )

    # Resolve chosen template — body.template_filename takes priority,
    # then session.chosen_template (set via /template endpoint), else default.
    tpl_fname = (body.template_filename if body else None) or s.chosen_template
    chosen_tpl_path: str | None = None
    if tpl_fname:
        candidate = os.path.join(_REFS_DIR, tpl_fname)
        if os.path.exists(candidate):
            chosen_tpl_path = candidate
            # Persist to session so re-generates keep the same template
            s.chosen_template = tpl_fname
        else:
            # Template file was requested but is missing on disk — fail loudly
            # so the user knows exactly what went wrong instead of silently
            # generating a deck with the wrong (default) template.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Template file '{tpl_fname}' was not found on this server. "
                    "Please re-select a template or contact support."
                ),
            )

    tpl_used = os.path.basename(chosen_tpl_path) if chosen_tpl_path else "Common Template.pptx (default)"
    print(f"  [generate] template → {tpl_used}")

    output_path = await asyncio.to_thread(
        generate_pptx, slide_contents, context, output_filename, s.strategy,
        chosen_tpl_path,
    )
    s.output_filename = output_filename
    s.touch()

    analytics = _record_session_analytics(s, tracker, started, "generation")

    result = {
        "status": "success",
        "filename": output_filename,
        "template_used": tpl_used,
        "total_pages": len(s.pages),
        "total_slides": len(slide_contents),
        "analytics": analytics,
    }

    # Optional S3 upload (parity with the one-shot /generate route).
    if STORAGE_BACKEND == "s3":
        s3_key = f"outputs/{session_id}/{output_filename}"
        try:
            upload_file_to_s3(
                local_path=output_path,
                s3_key=s3_key,
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "presentationml.presentation"
                ),
            )
            result["job_id"] = session_id
            result["download_url"] = create_presigned_download_url(s3_key)
            _safe_remove(output_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PPT generated but S3 upload failed: {e}")

    print(f"  [session {session_id}] generated {output_filename} ({len(slide_contents)} slides)")
    return GenerateResponse(**result)


# ── 11. delete session ───────────────────────────────────────────────────────

@router.delete("/{session_id}")
async def end_session(session_id: str):
    store.delete(session_id)
    return {"status": "ok"}


# ── 12. heartbeat — is this session still alive? ─────────────────────────────

@router.get("/{session_id}/status")
async def get_session_status(session_id: str):
    """
    Lightweight liveness check used by the frontend generating screen.
    Returns 404 if the session has expired or been deleted so the UI can
    surface a helpful "session expired" message instead of spinning forever.
    """
    s = store.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return {
        "alive": True,
        "has_plan": s.slide_plan is not None,
        "has_output": s.output_filename is not None,
        "page_count": len(s.pages),
        "updated_at": s.updated_at,
    }


def _safe_remove(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass
