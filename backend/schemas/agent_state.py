"""
Schemas for the LLM Orchestrator (Phase 5).

The Orchestrator is the highest-level agent in the system. Instead of the
pipeline running a fixed linear flow (extract → plan → write → ...), the
Orchestrator agent looks at the current PipelineState and picks the NEXT
tool to invoke. This lets the system:

  • Skip phases that aren't needed (e.g. faithfulness on a pure-MCQ deck
    where bullets are verbatim from the source).
  • Re-run a phase if quality is low (e.g. plan_critic suggests so many
    fixes that we should re-plan from scratch).
  • Stop early when quality is already high.
  • Fan out into parallel exploration (future).

Every decision is bounded by:
  - A hard MAX_STEPS cap to prevent runaway loops.
  - Validated tool transitions (extract must precede plan, etc.).
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class ToolName(str, Enum):
    """All tools the Orchestrator agent can call."""
    EXTRACT             = "extract_pdf"
    PLAN                = "plan_slides"
    REVIEW_LAYOUTS      = "review_layouts"
    CRITIQUE_PLAN       = "critique_plan"
    APPLY_PLAN_FIXES    = "apply_plan_fixes"
    WRITE               = "write_slides"
    CHECK_FAITHFULNESS  = "check_faithfulness"
    APPLY_FAITHFULNESS  = "apply_faithfulness_fixes"
    GENERATE_PPTX       = "generate_pptx"
    VISUAL_CRITIQUE     = "visual_critique"
    REWRITE_SLIDES      = "rewrite_slides_with_hints"
    FINALIZE            = "finalize"


class OrchestratorDecision(BaseModel):
    """
    The LLM Orchestrator's structured output at each step.

    next_tool : the tool to invoke
    reasoning : ≤ 200-char justification (logged for auditability)
    rationale_summary : optional 1-line summary of WHY this decision improves the deck
    """
    next_tool:         ToolName
    reasoning:         str
    rationale_summary: Optional[str] = None


class ActionLog(BaseModel):
    """One executed step in the orchestrator's history."""
    step:        int
    tool:        ToolName
    reasoning:   str
    succeeded:   bool
    duration_ms: int = 0
    note:        str = ""
