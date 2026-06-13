"""
Schemas used by the Layout Picker and Plan Critic agents.

These run BETWEEN planner and writer. They look at the planner's draft plan
and propose surgical fixes — change a slide's layout, merge two slides,
insert a missing section heading, etc. — before any expensive writer LLM
calls happen.
"""
from typing import Optional
from pydantic import BaseModel
from schemas.slide_plan import TemplateType


# ── PER-SLIDE LAYOUT REVIEW (Layout Picker output) ─────────────────────────

class LayoutSuggestion(BaseModel):
    """
    One layout opinion for one slide.
    The agent inspects what the slide's source pages actually contain and
    decides whether the planner's chosen layout is the best fit.
    """
    slide_number:      int
    current_layout:    TemplateType
    suggested_layout:  TemplateType        # may equal current → no change
    confidence:        float               # 0..1; orchestrator ignores low-conf changes
    reason:            str                 # short, why this layout fits better


# ── DECK-LEVEL STRUCTURAL REVIEW (Plan Critic output) ──────────────────────

class PlanFixAction(BaseModel):
    """
    One concrete edit to the slide plan. Kept deliberately tiny so we can
    apply each action atomically without re-running the planner.

    Supported action types:
      - "change_layout"    : change ONE slide's TemplateType
      - "insert_heading"   : insert a section_heading before slide N
                             (uses `title` for the heading)
      - "remove_slide"     : drop slide N (e.g. duplicate / empty / wrong)
      - "reorder"          : move slide N to position M  (use `target_index`)
      - "merge_with_next"  : merge slide N into slide N+1 (use_target = N+1)
                             — useful when the planner over-fragments
    """
    action_type:    str
    slide_number:   int                              # slide the action operates on
    target_layout:  Optional[TemplateType] = None    # for change_layout
    target_index:   Optional[int] = None             # for reorder
    title:          Optional[str] = None             # for insert_heading
    reason:         str                              # 1-line justification


class PlanReview(BaseModel):
    """
    Output of the Plan Critic — a verdict on the whole deck flow.

    `overall_ok`     : true if the plan is acceptable as-is.
    `fixes`          : ordered list of actions to apply.
    `narrative_note` : one short sentence on the deck's narrative arc.
    """
    overall_ok:      bool
    fixes:           list[PlanFixAction] = []
    narrative_note:  str
