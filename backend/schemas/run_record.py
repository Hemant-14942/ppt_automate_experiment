"""
Schemas for capturing pipeline run telemetry and proposed style updates.

A RunRecord is written at the end of every pipeline run. Over time, the
Style Learner reads accumulated records and proposes new soft hints to
add to memory/style.yaml. The system thus gets smarter with every PDF
it processes.
"""
from typing import Optional
from pydantic import BaseModel


# ── Telemetry of one pipeline run ─────────────────────────────────────────

class LayoutOverride(BaseModel):
    """Layout Picker changed planner's choice (high-confidence only)."""
    slide_number:    int
    from_layout:     str
    to_layout:       str
    confidence:      float
    reason:          str = ""


class PlanFixRecord(BaseModel):
    """Plan Critic structural fix applied."""
    action:          str
    slide_number:    int
    detail:          str = ""


class FaithfulnessFlag(BaseModel):
    """Bullet stripped or slide rewritten due to faithfulness check."""
    slide_number:    int
    fix_action:      str          # "strip_bullets" | "rewrite"
    n_bullets:       int = 0      # how many bullets dropped
    hint:            Optional[str] = None


class VisualFlag(BaseModel):
    """Visual Critic flag that triggered a retry."""
    slide_number:    int
    score:           int
    issue_types:     list[str]
    hint:            Optional[str] = None


class SlideTrace(BaseModel):
    """Which PDF pages fed each slide — the content provenance trail."""
    slide_number:    int
    layout:          str
    title:           str              # first 80 chars of slide title
    source_pages:    list[int]        # PDF page numbers this slide drew from


class RunRecord(BaseModel):
    """
    One pipeline run's outcome — enough signal for the Style Learner to
    notice what tends to go wrong / right for a given (subject, purpose)
    combination.
    """
    timestamp:               str          # ISO 8601
    subject:                 str
    purpose:                 str
    class_level:             str
    language:                str
    batch:                   str
    page_count:              int
    slide_count:             int
    layout_distribution:     dict[str, int]   # template name → count
    bullet_length_stats:     dict[str, float] # avg / max / p95
    title_length_stats:      dict[str, float]
    slide_trace:             list[SlideTrace]      = []   # provenance: slide → source pages
    layout_overrides:        list[LayoutOverride]  = []
    plan_fixes:              list[PlanFixRecord]   = []
    faithfulness_flags:      list[FaithfulnessFlag] = []
    visual_flags:            list[VisualFlag]      = []
    visual_retries:          int = 0
    final_status:            str = "success"    # "success" | "error"

    # ── Phase 4 — Profiler outcome signals (defaults keep old records valid) ─
    profile:                 str = ""     # DeckStrategy.profile used this run
    density:                 str = ""     # DeckStrategy.density used this run
    pagination_splits:       int = 0      # how many slides the fit engine split
    visual_overflow_flags:   int = 0      # slides the visual critic flagged as overflow
    theory_bullet_avg:       float = 0.0  # avg bullets per theory/summary/homework slide


# ── Style update proposed by the Style Learner ───────────────────────────

class StyleHint(BaseModel):
    """One new soft hint to merge into style.yaml."""
    key:             str               # short snake_case key
    value:           str               # plain-English rule, ≤ 120 chars
    confidence:      float             # 0..1; we only apply ≥ 0.7
    evidence_runs:   int               # how many runs back this up
    rationale:       str               # 1-line why we propose it


class StyleUpdate(BaseModel):
    """
    Output of the Style Learner. The orchestrator merges these hints into
    memory/style.yaml, preserving manually-edited rules.
    """
    new_hints:               list[StyleHint] = []
    runs_analyzed:           int
    summary:                 str = ""


# ── Structured per-profile calibration (Phase 4) ─────────────────────────────

class LearnedProfile(BaseModel):
    """
    Deterministically-aggregated norms for one (subject, purpose, profile)
    combination, computed from past run records. Fed back into the Profiler as
    a PRIOR so the system calibrates to a teacher's recurring content over time.
    """
    key:                            str    # "subject|purpose|profile" (lowercased)
    subject:                        str = ""
    purpose:                        str = ""
    profile:                        str = ""
    runs:                           int = 0
    recommended_density:            str = "balanced"
    avg_bullets_per_theory_slide:   float = 0.0
    avg_slides_per_page:            float = 0.0
    overflow_rate:                  float = 0.0   # fraction of runs with visual overflow
    suggested_theory_bullet_target: int = 5
    updated_at:                     str = ""
