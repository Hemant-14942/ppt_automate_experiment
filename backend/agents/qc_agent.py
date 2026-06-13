"""
QC Agent — programmatic quality gate after all slides are written.

No LLM needed here — these are deterministic rules:
  - too many bullets      → auto-fix: trim to MAX_BULLETS
  - bullet too long       → auto-fix: truncate at MAX_BULLET_WORDS
  - empty title           → flag for manual review
  - empty content         → flag for manual review

After auto-fixing, issues are logged.
Non-fixable issues are printed as warnings — pipeline continues regardless.
"""

from dataclasses import dataclass
from schemas.slide_content import SlideContent
from config import MAX_BULLETS, MAX_BULLET_WORDS
from schemas.slide_plan import TemplateType


# A bullet is only worth flagging (as a soft, non-destructive warning) on a
# NON-free-body layout when it is extremely long — usually a sign the planner
# picked the wrong layout, not something to truncate.
_RUNAWAY_BULLET_WORDS = 40


@dataclass
class QCIssue:
    slide_number: int
    issue_type:   str    # "too_many_bullets" | "bullet_too_long" | "empty_title" | "empty_content"
    detail:       str
    auto_fixable: bool


def run_qc(slides: list[SlideContent]) -> list[QCIssue]:
    """
    Run all quality checks across every slide.
    Returns list of issues found — auto-fixable and manual both.
    """
    issues = []

    for slide in slides:

        # 1. too many bullets
        max_bullets = _max_bullets_for_layout(slide.layout)
        if len(slide.bullets) > max_bullets:
            issues.append(QCIssue(
                slide_number=slide.slide_number,
                issue_type="too_many_bullets",
                detail=f"{len(slide.bullets)} bullets — max is {max_bullets}",
                auto_fixable=True
            ))

        # 2. empty or missing title
        if not slide.title or len(slide.title.strip()) < 3:
            issues.append(QCIssue(
                slide_number=slide.slide_number,
                issue_type="empty_title",
                detail="Slide title is missing or too short",
                auto_fixable=False
            ))

        # 3. no content on non-diagram, non-title slides
        no_bullets  = len(slide.bullets) == 0
        # passage_slide carries its content in passage_text, not bullets/diagram.
        no_diagram  = not slide.diagram_description and not slide.passage_text
        # Layouts that legitimately have no bullets — only a title or decoration
        title_only_layouts = (
            "title_slide", "diagram", "section_heading", "thank_you_slide",
            "question_only", "pyq_question_only", "passage_slide",
        )
        non_content = slide.layout.value not in title_only_layouts
        if no_bullets and no_diagram and non_content:
            issues.append(QCIssue(
                slide_number=slide.slide_number,
                issue_type="empty_content",
                detail="Slide has no bullets and no diagram description",
                auto_fixable=False
            ))

        # 4. individual bullets that are extremely long.
        #    NOTE: we NEVER truncate — that would destroy content. For free-body
        #    layouts the reflow engine paginates instead, so we skip them here.
        #    For other layouts we only LOG a runaway bullet as a soft warning.
        if slide.layout not in _FREE_BODY_LAYOUTS:
            for j, bullet in enumerate(slide.bullets):
                word_count = len(bullet.split())
                if word_count > _RUNAWAY_BULLET_WORDS:
                    issues.append(QCIssue(
                        slide_number=slide.slide_number,
                        issue_type="bullet_too_long",
                        detail=f"Bullet {j + 1} has {word_count} words — consider a different layout",
                        auto_fixable=False
                    ))

    return issues


def auto_fix(slides: list[SlideContent], issues: list[QCIssue]) -> list[SlideContent]:
    """
    Apply deterministic fixes for auto_fixable issues.
    Modifies slides in-place and returns them.
    """
    for issue in issues:
        if not issue.auto_fixable:
            continue

        slide = next((s for s in slides if s.slide_number == issue.slide_number), None)
        if slide is None:
            continue

        if issue.issue_type == "too_many_bullets":
            slide.bullets = slide.bullets[:_max_bullets_for_layout(slide.layout)]

        # bullet_too_long is intentionally NOT auto-fixed — truncation drops
        # content. Overflow is handled by the reflow engine (pagination).

    return slides


def qc_report(issues: list[QCIssue]) -> str:
    """Return a one-line summary for the pipeline log."""
    if not issues:
        return "QC passed — no issues"

    fixed   = sum(1 for i in issues if i.auto_fixable)
    manual  = sum(1 for i in issues if not i.auto_fixable)
    details = "\n".join(
        f"    Slide {i.slide_number} [{i.issue_type}]: {i.detail}"
        + (" → auto-fixed" if i.auto_fixable else " → needs review")
        for i in issues
    )
    return f"{len(issues)} issue(s) — {fixed} auto-fixed, {manual} need review\n{details}"


# Layouts whose body is a free-flowing textbox: the fit/reflow engine paginates
# them, so QC must NOT cap or truncate — that would silently drop content.
_FREE_BODY_LAYOUTS = {
    TemplateType.theory_slide,
    TemplateType.summary,
    TemplateType.homework_slide,
}


def _max_bullets_for_layout(layout: TemplateType) -> int:
    if layout in {
        TemplateType.recap_slide,
        TemplateType.topics_slide,
        TemplateType.mcq_slide,
        TemplateType.mcq_grid_slide,
        TemplateType.pyq_slide,
        TemplateType.pyq_grid_slide,
    }:
        return 4
    if layout in _FREE_BODY_LAYOUTS:
        # No practical cap — the reflow engine splits overflow into new slides.
        return 9999
    return MAX_BULLETS
