"""
LLM Orchestrator Agent

Looks at the current PipelineState and decides which tool to call next.
This is the top-level "thinking" agent that turns the system from a
linear pipeline into a true agentic loop.

Design points:
  • One Gemini call per decision (small, cheap, fast).
  • Structured output (`OrchestratorDecision`) — no free-form parsing.
  • The prompt encodes hard transition rules (you cannot plan before
    extracting, etc.) so the LLM cannot violate the state machine.
  • If the LLM somehow returns an invalid choice, the caller falls back
    to the next legal default tool.
"""
import json
from google.genai import types

from agents.gemini_client import client
from schemas.agent_state  import OrchestratorDecision, ToolName
from config import ORCHESTRATOR_MODEL
from pipeline.token_tracker import record_api_attempt, record_api_failure, record_usage


# Tool catalogue shown to the LLM
_TOOL_DESCRIPTIONS = {
    ToolName.EXTRACT:            "Run vision Gemini on every PDF page in parallel. Required first step.",
    ToolName.PLAN:                "Produce a draft slide plan from extracted pages. Required after extract.",
    ToolName.REVIEW_LAYOUTS:      "Per-slide layout sanity check; flags wrong template choices.",
    ToolName.CRITIQUE_PLAN:       "Whole-deck structural review; flags spurious headings, missing summary, etc.",
    ToolName.APPLY_PLAN_FIXES:    "Deterministically apply layout-picker + plan-critic suggestions to the plan.",
    ToolName.WRITE:               "Generate content (title, bullets, notes) for every slide in parallel.",
    ToolName.CHECK_FAITHFULNESS:  "Anti-hallucination check — verify bullets match source PDF pages.",
    ToolName.APPLY_FAITHFULNESS:  "Strip unsupported bullets / rewrite hallucinated slides.",
    ToolName.GENERATE_PPTX:       "Run QC auto-fix and build the .pptx file from current slide contents.",
    ToolName.VISUAL_CRITIQUE:     "Render generated pptx and use vision LLM to flag visually-broken slides.",
    ToolName.REWRITE_SLIDES:      "Rewrite slides flagged by visual_critique + regenerate the pptx.",
    ToolName.FINALIZE:            "Mark the pipeline complete. Only call when a clean pptx exists.",
}


# Transition rules the LLM must obey
_TRANSITION_RULES = """
HARD TRANSITION RULES — violating these breaks the pipeline:
  1. extract_pdf must be the FIRST tool called.
  2. plan_slides can only be called AFTER extract_pdf.
  3. review_layouts, critique_plan, apply_plan_fixes need a slide_plan first.
  4. write_slides needs a slide_plan first.
  5. check_faithfulness, apply_faithfulness_fixes need written slides.
  6. generate_pptx needs written slides.
  7. visual_critique needs a generated pptx.
  8. rewrite_slides_with_hints needs visual_critiques to act on.
  9. finalize can ONLY be called when state.pptx_generated == True AND
     slides_pending_recheck is empty AND either visual_critique passed
     (n_visual_bad == 0) OR visual_retries_used >= visual_retry_budget.
 10. You may NOT skip extract / plan / write / generate_pptx — they are
     non-negotiable for any valid output.
 11. If libreoffice_available == false, skip visual_critique entirely
     and go straight to finalize once the pptx is generated.
 12. After rewrite_slides_with_hints, visual_critique automatically
     re-checks ONLY the rewritten slides — do not expect a full-deck pass.
 13. Do NOT call visual_critique again when n_visual_bad == 0 and
     slides_pending_recheck is empty.
"""


# Soft guidance — when each optional tool typically helps
_SOFT_GUIDANCE = """
SOFT GUIDANCE (use your judgment):
  • For a SHORT MCQ-only deck (few slides, all from same exam), faithfulness
    check is usually overkill — the bullets are the verbatim options.
  • For a long Lecture-notes deck, faithfulness is more valuable.
  • Always run review_layouts + critique_plan before writing — they catch
    expensive mistakes upstream.
  • If visual_critique flags >= 1 slide, call rewrite_slides_with_hints
    THEN visual_critique re-checks only those slides — max visual_retry_budget
    rewrite rounds total.
  • After ANY rewrite, visual_critique runs automatically on rewritten slides
    only — call it once, then finalize if n_visual_bad == 0.
"""


def _build_decision_prompt(state_summary: dict) -> str:
    tool_block = "\n".join(
        f"  - {t.value:28s}: {desc}"
        for t, desc in _TOOL_DESCRIPTIONS.items()
    )
    return f"""You are the LLM Orchestrator of a PDF-to-PPT agentic pipeline.

Your only job: read the CURRENT STATE summary and pick the SINGLE next
tool to invoke. You do not write code, you do not fill arguments — every
tool reads what it needs from state directly.

CURRENT STATE:
{json.dumps(state_summary, indent=2)}

AVAILABLE TOOLS:
{tool_block}

{_TRANSITION_RULES}

{_SOFT_GUIDANCE}

Return your decision as JSON matching the OrchestratorDecision schema:
  next_tool : one of the tool names above
  reasoning : short justification (≤ 200 chars)
  rationale_summary : optional 1-line summary of why this improves the deck

Pick exactly one tool. No multi-step plans. No new tools.
"""


async def decide_next_tool(state_summary: dict) -> OrchestratorDecision:
    """One Gemini call → one OrchestratorDecision."""
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=OrchestratorDecision,
    )
    try:
        record_api_attempt("planning", ORCHESTRATOR_MODEL)
        response = await client.aio.models.generate_content(
            model=ORCHESTRATOR_MODEL,
            contents=_build_decision_prompt(state_summary),
            config=config,
        )
    except Exception:
        record_api_failure("planning", ORCHESTRATOR_MODEL)
        raise
    record_usage("planning", response.usage_metadata, model=ORCHESTRATOR_MODEL)
    return response.parsed
