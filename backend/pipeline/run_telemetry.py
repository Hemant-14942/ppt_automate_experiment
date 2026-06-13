"""
Capture each pipeline run's outcome to memory/runs/<timestamp>.json.

Why a separate module: orchestrator should only have to call
`save_run_record(...)` with the data it already has — all the messy
serialisation / file-naming logic lives here.

The Style Learner reads these records to find patterns and propose new
soft hints for memory/style.yaml.
"""
import os
import uuid
from datetime import datetime
from statistics import mean

from schemas.run_record  import (
    RunRecord, LayoutOverride, PlanFixRecord,
    FaithfulnessFlag, VisualFlag, SlideTrace,
)
from schemas.slide_content   import SlideContent
from schemas.slide_plan      import FullSlidePlan, SlideOutline
from schemas.plan_review     import LayoutSuggestion, PlanReview
from schemas.faithfulness    import FaithfulnessReport
from schemas.critic_report   import SlideCritique
from schemas.request         import PDFContext
from config import MEMORY_DIR


# Where individual run records live
RUNS_DIR = os.path.join(MEMORY_DIR, "runs")


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────

def print_slide_trace(slide_plan: FullSlidePlan) -> None:
    """
    Print a human-readable table showing which PDF pages each slide draws from.
    Called by the orchestrator right after planning so the operator can verify
    content provenance in the terminal.
    """
    print("  Slide → Source Page mapping:")
    print(f"  {'Slide':<6} {'Layout':<22} {'Source Pages':<16} Title")
    print(f"  {'-'*6} {'-'*22} {'-'*16} {'-'*40}")
    for s in slide_plan.slides:
        pages_str = ", ".join(str(p) for p in s.source_pages) if s.source_pages else "—"
        title_preview = s.title[:55] + "…" if len(s.title) > 55 else s.title
        print(f"  {s.slide_number:<6} {s.template.value:<22} {pages_str:<16} {title_preview}")


def save_run_record(
    context:              PDFContext,
    page_count:           int,
    slide_contents:       list[SlideContent],
    slide_plan:           FullSlidePlan,
    layout_suggestions:   list[LayoutSuggestion],
    plan_review:          PlanReview,
    faithfulness_reports: list[FaithfulnessReport],
    visual_critiques:     list[SlideCritique],
    visual_retries:       int,
    final_status:         str = "success",
    strategy=None,
    pagination_splits:    int = 0,
) -> str:
    """
    Build a RunRecord from the pipeline state and persist it.
    Returns the absolute path of the written file.

    `strategy` (DeckStrategy) and `pagination_splits` (number of slides the fit
    engine split) are Phase-4 outcome signals fed to the profile learner.
    """
    os.makedirs(RUNS_DIR, exist_ok=True)

    profile_val = ""
    density_val = ""
    if strategy is not None:
        profile_val = strategy.profile.value if hasattr(strategy.profile, "value") else str(strategy.profile)
        density_val = strategy.density.value if hasattr(strategy.density, "value") else str(strategy.density)

    record = RunRecord(
        timestamp=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        subject=context.subject,
        purpose=context.purpose,
        class_level=context.class_level,
        language=context.language,
        batch=context.batch,
        page_count=page_count,
        slide_count=len(slide_contents),
        layout_distribution=_layout_distribution(slide_contents),
        bullet_length_stats=_bullet_length_stats(slide_contents),
        title_length_stats=_title_length_stats(slide_contents),
        slide_trace=_build_slide_trace(slide_plan),
        layout_overrides=_collect_layout_overrides(layout_suggestions),
        plan_fixes=_collect_plan_fixes(plan_review),
        faithfulness_flags=_collect_faithfulness(faithfulness_reports),
        visual_flags=_collect_visual(visual_critiques),
        visual_retries=visual_retries,
        final_status=final_status,
        profile=profile_val,
        density=density_val,
        pagination_splits=pagination_splits,
        visual_overflow_flags=_count_visual_overflow(visual_critiques),
        theory_bullet_avg=_theory_bullet_avg(slide_contents),
    )

    # Append a short uuid suffix so concurrent / same-second runs don't collide
    short_uuid = uuid.uuid4().hex[:6]
    fname = (
        f"{record.timestamp.replace(':', '')}_"
        f"{record.subject.replace(' ', '_')}_"
        f"{record.purpose.replace(' ', '_')}_"
        f"{short_uuid}.json"
    )
    path = os.path.join(RUNS_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(record.model_dump_json(indent=2))
    return path


def load_recent_runs(limit: int = 20) -> list[RunRecord]:
    """Load the N most recent run records (chronological newest-first)."""
    if not os.path.isdir(RUNS_DIR):
        return []
    files = sorted(os.listdir(RUNS_DIR), reverse=True)[:limit]
    out: list[RunRecord] = []
    for fname in files:
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(RUNS_DIR, fname), "r", encoding="utf-8") as f:
                out.append(RunRecord.model_validate_json(f.read()))
        except Exception:
            continue
    return out


# ──────────────────────────────────────────────────────────────────────────
# Internal — stats helpers
# ──────────────────────────────────────────────────────────────────────────

def _layout_distribution(contents: list[SlideContent]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in contents:
        key = c.layout.value if hasattr(c.layout, "value") else str(c.layout)
        out[key] = out.get(key, 0) + 1
    return out


def _bullet_length_stats(contents: list[SlideContent]) -> dict[str, float]:
    lengths: list[int] = []
    for c in contents:
        for b in c.bullets:
            lengths.append(len(b.split()))
    if not lengths:
        return {"avg": 0.0, "max": 0.0, "count": 0.0}
    return {
        "avg":   round(mean(lengths), 2),
        "max":   float(max(lengths)),
        "count": float(len(lengths)),
    }


def _title_length_stats(contents: list[SlideContent]) -> dict[str, float]:
    lengths = [len(c.title) for c in contents]
    if not lengths:
        return {"avg_chars": 0.0, "max_chars": 0.0}
    return {
        "avg_chars": round(mean(lengths), 2),
        "max_chars": float(max(lengths)),
    }


# Layouts whose body is free-flowing prose (paginated by the fit engine).
_FREE_BODY_NAMES = {"theory_slide", "summary", "homework_slide"}
# Visual issue types that mean content physically did not fit.
_OVERFLOW_ISSUE_NAMES = {"text_overflow", "off_screen"}


def _theory_bullet_avg(contents: list[SlideContent]) -> float:
    """Average bullet count across free-body slides — the writer-density signal."""
    counts = [
        len(c.bullets) for c in contents
        if (c.layout.value if hasattr(c.layout, "value") else str(c.layout)) in _FREE_BODY_NAMES
        and c.bullets
    ]
    return round(mean(counts), 2) if counts else 0.0


def _count_visual_overflow(critiques: list[SlideCritique]) -> int:
    """How many slides the visual critic flagged specifically for overflow."""
    return sum(
        1 for c in critiques
        if c.should_retry and any(i.type in _OVERFLOW_ISSUE_NAMES for i in c.issues)
    )


def _collect_layout_overrides(
    suggestions: list[LayoutSuggestion],
) -> list[LayoutOverride]:
    """Only record overrides we ACTUALLY applied (high-confidence)."""
    out = []
    for s in suggestions:
        if s.suggested_layout == s.current_layout:
            continue
        if s.confidence < 0.8:
            continue
        out.append(LayoutOverride(
            slide_number=s.slide_number,
            from_layout=s.current_layout.value,
            to_layout=s.suggested_layout.value,
            confidence=round(s.confidence, 2),
            reason=s.reason[:160],
        ))
    return out


def _collect_plan_fixes(review: PlanReview) -> list[PlanFixRecord]:
    return [
        PlanFixRecord(
            action=f.action_type,
            slide_number=f.slide_number,
            detail=(f.reason or "")[:160],
        )
        for f in review.fixes
    ]


def _collect_faithfulness(
    reports: list[FaithfulnessReport],
) -> list[FaithfulnessFlag]:
    out = []
    for r in reports:
        if r.fix_action == "ok":
            continue
        n_dropped = sum(
            1 for v in r.bullet_verdicts
            if v.status in ("unsupported", "contradicts")
        )
        out.append(FaithfulnessFlag(
            slide_number=r.slide_number,
            fix_action=r.fix_action,
            n_bullets=n_dropped,
            hint=(r.fix_hint or "")[:200] if r.fix_hint else None,
        ))
    return out


def _collect_visual(critiques: list[SlideCritique]) -> list[VisualFlag]:
    out = []
    for c in critiques:
        if not c.should_retry:
            continue
        out.append(VisualFlag(
            slide_number=c.slide_number,
            score=c.overall_score,
            issue_types=[i.type for i in c.issues],
            hint=(c.content_fix_hint or "")[:200]
                  if c.content_fix_hint else None,
        ))
    return out


def _build_slide_trace(slide_plan: FullSlidePlan) -> list[SlideTrace]:
    """Build the slide → source pages provenance list from the final slide plan."""
    return [
        SlideTrace(
            slide_number=s.slide_number,
            layout=s.template.value,
            title=s.title[:80],
            source_pages=list(s.source_pages),
        )
        for s in slide_plan.slides
    ]
