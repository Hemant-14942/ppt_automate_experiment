"""
Plan Revisor

Given the planner's draft and the suggestions from:
  - Layout Picker  (per-slide layout changes)
  - Plan Critic    (deck-level structural fixes)

this module applies the agreed-upon edits and returns a CLEAN FullSlidePlan
with slide numbers renumbered. Kept deterministic so a stray bad suggestion
can't blow up the deck.
"""

from copy import deepcopy
from schemas.slide_plan   import FullSlidePlan, SlideOutline, TemplateType
from schemas.plan_review  import (
    LayoutSuggestion,
    PlanReview,
    PlanFixAction,
)


# ── Confidence threshold for accepting a Layout Picker suggestion ─────────
LAYOUT_CONFIDENCE_THRESHOLD = 0.8


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────

def apply_revisions(
    plan: FullSlidePlan,
    layout_suggestions: list[LayoutSuggestion],
    plan_review: PlanReview,
) -> tuple[FullSlidePlan, list[str]]:
    """
    Apply (a) layout-picker changes, then (b) plan-critic actions.
    Returns the revised plan and a human-readable change log.
    """
    new_slides = [deepcopy(s) for s in plan.slides]
    log: list[str] = []

    # ── (a) per-slide layout overrides ─────────────────────────────────────
    by_num = {s.slide_number: s for s in new_slides}
    for sug in layout_suggestions:
        if sug.suggested_layout == sug.current_layout:
            continue
        if sug.confidence < LAYOUT_CONFIDENCE_THRESHOLD:
            continue
        target = by_num.get(sug.slide_number)
        if target is None:
            continue
        log.append(
            f"layout: slide {sug.slide_number} "
            f"{target.template.value} → {sug.suggested_layout.value} "
            f"(conf {sug.confidence:.2f}; {sug.reason})"
        )
        target.template = sug.suggested_layout

    # ── (b) deck-level structural fixes ────────────────────────────────────
    for fix in plan_review.fixes:
        new_slides, change = _apply_one_fix(new_slides, fix)
        if change:
            log.append(change)

    # ── (c) split long theory slides into multiple 4-point slides ─────────
    new_slides = _split_theory_slides(new_slides)

    # ── renumber slide_numbers 1..N to stay consistent ─────────────────────
    for i, s in enumerate(new_slides, start=1):
        s.slide_number = i

    return (
        FullSlidePlan(total_slides=len(new_slides), slides=new_slides),
        log,
    )


# ──────────────────────────────────────────────────────────────────────────
# Internal — atomic actions
# ──────────────────────────────────────────────────────────────────────────

def _apply_one_fix(
    slides: list[SlideOutline],
    fix:    PlanFixAction,
) -> tuple[list[SlideOutline], str | None]:
    """Apply one PlanFixAction. Bad / unknown actions are silently skipped."""
    idx = _find_idx(slides, fix.slide_number)

    if fix.action_type == "change_layout":
        if idx is None or fix.target_layout is None:
            return slides, None
        old = slides[idx].template
        if old == fix.target_layout:
            return slides, None
        slides[idx].template = fix.target_layout
        return slides, (
            f"critic: slide {fix.slide_number} layout "
            f"{old.value} → {fix.target_layout.value}  ({fix.reason})"
        )

    if fix.action_type == "insert_heading":
        if idx is None or not fix.title:
            return slides, None
        heading = SlideOutline(
            slide_number=0,                            # renumbered later
            title=fix.title,
            template=TemplateType.section_heading,
            source_pages=[],
            key_points=[],
            include_diagram=False,
            emphasis=[],
        )
        slides.insert(idx, heading)
        return slides, (
            f"critic: insert section_heading \"{fix.title}\" "
            f"before slide {fix.slide_number}  ({fix.reason})"
        )

    if fix.action_type == "remove_slide":
        if idx is None:
            return slides, None
        # Never remove the first or the last slide — those are structural.
        if idx == 0 or idx == len(slides) - 1:
            return slides, None
        # Never remove MCQ/question slides — these are annotated content
        _protected_templates = {
            TemplateType.mcq_slide, TemplateType.mcq_grid_slide,
            TemplateType.question_only, TemplateType.pyq_slide,
            TemplateType.pyq_grid_slide, TemplateType.pyq_question_only,
        }
        if slides[idx].template in _protected_templates:
            return slides, None
        removed = slides.pop(idx)
        return slides, (
            f"critic: removed slide {fix.slide_number} "
            f"[{removed.template.value}]  ({fix.reason})"
        )

    if fix.action_type == "reorder":
        if idx is None or fix.target_index is None:
            return slides, None
        new_idx = max(1, min(len(slides), fix.target_index)) - 1
        if new_idx == idx:
            return slides, None
        # Don't reorder past the title or thank-you sentinels.
        if idx == 0 or new_idx == 0:
            return slides, None
        if idx == len(slides) - 1 or new_idx == len(slides) - 1:
            return slides, None
        moved = slides.pop(idx)
        slides.insert(new_idx, moved)
        return slides, (
            f"critic: moved slide {fix.slide_number} → position "
            f"{fix.target_index}  ({fix.reason})"
        )

    if fix.action_type == "merge_with_next":
        if idx is None or idx + 1 >= len(slides):
            return slides, None
        a = slides[idx]
        b = slides[idx + 1]
        # Don't merge structural slides
        if a.template in {TemplateType.title_slide,
                          TemplateType.thank_you_slide,
                          TemplateType.summary}:
            return slides, None
        # Don't merge MCQ/question slides — each annotated question needs its own slide
        _question_templates = {
            TemplateType.mcq_slide, TemplateType.mcq_grid_slide,
            TemplateType.question_only, TemplateType.pyq_slide,
            TemplateType.pyq_grid_slide, TemplateType.pyq_question_only,
        }
        if a.template in _question_templates or b.template in _question_templates:
            return slides, None
        # Don't merge table slides — their key_points don't capture the table
        # data and merging would silently drop the table on render.
        _table_templates = {
            TemplateType.table_slide, TemplateType.theory_table_slide,
        }
        if a.template in _table_templates or b.template in _table_templates:
            return slides, None
        merged = SlideOutline(
            slide_number=0,
            title=a.title or b.title,
            template=b.template,
            source_pages=list(dict.fromkeys(a.source_pages + b.source_pages)),
            key_points=(a.key_points + b.key_points)[:6],
            include_diagram=a.include_diagram or b.include_diagram,
            emphasis=list(dict.fromkeys(a.emphasis + b.emphasis)),
        )
        slides[idx:idx + 2] = [merged]
        return slides, (
            f"critic: merged slide {fix.slide_number} into next "
            f"({fix.reason})"
        )

    return slides, None


def _find_idx(slides: list[SlideOutline], slide_number: int) -> int | None:
    for i, s in enumerate(slides):
        if s.slide_number == slide_number:
            return i
    return None


def _split_theory_slides(slides: list[SlideOutline]) -> list[SlideOutline]:
    """Split theory slides into multiple slides if they have >4 key_points."""
    out: list[SlideOutline] = []
    for slide in slides:
        if slide.template != TemplateType.theory_slide:
            out.append(slide)
            continue
        if len(slide.key_points) <= 4:
            out.append(slide)
            continue

        chunks = [slide.key_points[i:i + 4] for i in range(0, len(slide.key_points), 4)]
        for i, chunk in enumerate(chunks):
            out.append(SlideOutline(
                slide_number=0,
                title=slide.title,
                template=slide.template,
                source_pages=slide.source_pages,
                key_points=chunk,
                include_diagram=slide.include_diagram if i == 0 else False,
                emphasis=slide.emphasis,
            ))
    return out
