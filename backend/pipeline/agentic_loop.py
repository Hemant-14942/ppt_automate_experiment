"""
Agentic Pipeline Loop  (Phase 5)

Replaces the linear `run_pipeline_async` with an LLM-driven decision
loop. The Orchestrator agent looks at PipelineState and chooses the
next tool to invoke at every step.

Safety bounds (multi-layered defense):
  • MAX_STEPS hard cap (default 20) — prevents runaway loops.
  • MAX_VISUAL_RETRIES enforced by the rewrite tool itself.
  • Transition validator — if the LLM picks a tool with unmet prereqs,
    we fall back to the next legal default tool.
  • Repeat detector — if the same tool is picked 3 times in a row, we
    force a transition to the next legal tool to break the cycle.

The loop is opt-in via the AGENTIC_MODE flag in config / env. The
default `run_pipeline_async` remains the linear pipeline so production
is unaffected.
"""
import os
import yaml
import time
import traceback
from pipeline.tools             import PipelineState, execute_tool
from agents.orchestrator_agent  import decide_next_tool
from pipeline.pdf_loader        import get_pdf_page_count
from pipeline.token_tracker     import TokenTracker
from schemas.agent_state        import ToolName
from schemas.request            import PDFContext
from config import STYLE_YAML, MAX_VISUAL_RETRIES


# Hard cap on total tool invocations
MAX_STEPS = 20

# Recovery default — used when the LLM picks an invalid tool
_DEFAULT_NEXT_TOOL: dict[str, ToolName] = {
    # key = "stage signature"; value = the legal tool to call
    # signature is constructed from state.summarize() to pick the next step
}


def _next_legal_tool(state: PipelineState) -> ToolName:
    """
    Fallback: determines which tool would be next under the LINEAR pipeline,
    used to recover from an invalid LLM choice.
    """
    s = state.summarize()
    if not s["extracted"]:                 return ToolName.EXTRACT
    if not s["planned"]:                   return ToolName.PLAN
    if not s["layout_reviewed"]:           return ToolName.REVIEW_LAYOUTS
    if not s["plan_reviewed"]:             return ToolName.CRITIQUE_PLAN
    if (s["n_layout_overrides"] or s["n_plan_fixes"]) \
            and not s["plan_fixes_applied"] and not s["written"]:
        return ToolName.APPLY_PLAN_FIXES
    if not s["written"]:                   return ToolName.WRITE
    if not s["faithfulness_checked"]:      return ToolName.CHECK_FAITHFULNESS
    if s["n_faith_strips"] or s["n_faith_rewrites"]:
        return ToolName.APPLY_FAITHFULNESS
    if not s["pptx_generated"]:            return ToolName.GENERATE_PPTX
    if s["slides_pending_recheck"]:
        return ToolName.VISUAL_CRITIQUE
    if not s["visual_critiqued"]:
        if s["libreoffice_available"]:
            return ToolName.VISUAL_CRITIQUE
    if s["n_visual_bad"] and s["visual_retries_used"] < MAX_VISUAL_RETRIES:
        return ToolName.REWRITE_SLIDES
    return ToolName.FINALIZE


def _is_legal(state: PipelineState, tool: ToolName) -> bool:
    """Enforce the hard transition rules even if the LLM tries to break them."""
    s = state.summarize()
    requires_extract = {
        ToolName.PLAN, ToolName.REVIEW_LAYOUTS, ToolName.CRITIQUE_PLAN,
        ToolName.APPLY_PLAN_FIXES, ToolName.WRITE,
        ToolName.CHECK_FAITHFULNESS, ToolName.APPLY_FAITHFULNESS,
        ToolName.GENERATE_PPTX, ToolName.VISUAL_CRITIQUE,
        ToolName.REWRITE_SLIDES, ToolName.FINALIZE,
    }
    if tool in requires_extract and not s["extracted"]:
        return False
    if tool in {ToolName.REVIEW_LAYOUTS, ToolName.CRITIQUE_PLAN,
                ToolName.APPLY_PLAN_FIXES, ToolName.WRITE} and not s["planned"]:
        return False
    # Plan fixes are a ONE-TIME step. Re-applying mutates the plan again and
    # invalidates the written slides → a full, costly re-write. Block it once
    # it has run, or once slides already exist.
    if tool == ToolName.APPLY_PLAN_FIXES and (s["plan_fixes_applied"] or s["written"]):
        return False
    if tool in {ToolName.CHECK_FAITHFULNESS, ToolName.APPLY_FAITHFULNESS,
                ToolName.GENERATE_PPTX} and not s["written"]:
        return False
    if tool in {ToolName.VISUAL_CRITIQUE, ToolName.REWRITE_SLIDES,
                ToolName.FINALIZE} and not s["pptx_generated"]:
        return False
    if tool == ToolName.REWRITE_SLIDES and not s["visual_critiqued"]:
        return False
    if tool == ToolName.VISUAL_CRITIQUE:
        if s["slides_pending_recheck"]:
            return True
        if s["visual_critiqued"] and s["n_visual_bad"] == 0:
            return False
    if tool == ToolName.FINALIZE:
        if s["slides_pending_recheck"]:
            return False
        if s["n_visual_bad"] > 0 and s["visual_retries_used"] < MAX_VISUAL_RETRIES:
            return False
    return True


def _load_style_rules() -> dict:
    if os.path.exists(STYLE_YAML):
        with open(STYLE_YAML, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


# ──────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────

async def run_pipeline_agentic(pdf_path: str, context: PDFContext) -> dict:
    """
    LLM-driven pipeline. Mirrors `run_pipeline_async` signature so callers
    don't care which mode they're in.
    """
    if not os.path.exists(pdf_path):
        return {"status": "error", "message": f"PDF not found: {pdf_path}"}

    safe_batch   = context.batch.replace(" ", "_").replace("/", "-")
    safe_subject = context.subject.replace(" ", "_")
    output_filename = f"{safe_subject}_{safe_batch}_{context.purpose}_slides.pptx"

    page_count = get_pdf_page_count(pdf_path)

    print(f"\n{'='*52}")
    print(f"  PDF to PPT — AGENTIC MODE (Phase 5)")
    print(f"{'='*52}")
    print(f"  Subject : {context.subject}")
    print(f"  Pages   : {page_count}")
    print(f"  Output  : {output_filename}")
    print(f"{'='*52}\n")

    tracker = TokenTracker()
    tracker.activate()
    pipeline_start = time.monotonic()

    def _fail(message: str) -> dict:
        elapsed = time.monotonic() - pipeline_start
        print(f"\n  ERROR — Agentic pipeline failed: {message}")
        print(tracker.summary(elapsed))
        return {"status": "error", "message": message}

    state = PipelineState(
        pdf_path=pdf_path,
        context=context,
        output_filename=output_filename,
        style_rules=_load_style_rules(),
    )

    # Track repeats to break loops
    last_two: list[ToolName] = []

    for step in range(1, MAX_STEPS + 1):
        # ─── ask the LLM what to do next ───────────────────────────────
        try:
            decision = await decide_next_tool(state.summarize())
            chosen = decision.next_tool
            reasoning = decision.reasoning
        except Exception as e:
            print(f"  [step {step}] decision LLM failed ({e}); using default")
            chosen = _next_legal_tool(state)
            reasoning = "fallback after LLM error"

        # ─── transition validation ─────────────────────────────────────
        if not _is_legal(state, chosen):
            forced = _next_legal_tool(state)
            print(f"  [step {step}] LLM picked illegal '{chosen.value}', "
                  f"forcing '{forced.value}'")
            chosen, reasoning = forced, "illegal LLM choice → linear default"

        # ─── repeat-loop breaker ───────────────────────────────────────
        if last_two and last_two[-1] == chosen and \
           (len(last_two) >= 2 and last_two[-2] == chosen):
            forced = _next_legal_tool(state)
            if forced != chosen:
                print(f"  [step {step}] same tool 3x in a row, forcing '{forced.value}'")
                chosen = forced

        # ─── execute the tool ──────────────────────────────────────────
        print(f"  [step {step:2d}] {chosen.value:28s}  ← {reasoning[:90]}")
        try:
            ok, note = await execute_tool(state, chosen, reasoning)
        except Exception as e:
            print(f"  [step {step:2d}] tool crashed [{type(e).__name__}]: {e!r}")
            traceback.print_exc()
            return _fail(f"{chosen.value} crashed: {e}")
        print(f"           → {'ok' if ok else '✗'}  {note}")

        last_two.append(chosen)
        if len(last_two) > 3:
            last_two = last_two[-3:]

        if state.done:
            break
        if state.fatal_error:
            return _fail(state.fatal_error)
        if not ok and chosen == ToolName.EXTRACT:
            return _fail(f"extraction failed: {note}")

    # ─── final summary ────────────────────────────────────────────────
    if not state.output_path:
        return _fail("agentic loop ended without producing pptx")

    print(f"\n{'='*52}")
    print(f"  Agentic pipeline complete in {len(state.history)} step(s)")
    print(f"  Output : {state.output_path}")
    print(f"{'='*52}\n")

    elapsed = time.monotonic() - pipeline_start
    print(tracker.summary(elapsed))

    return {
        "status":       "success",
        "filename":     output_filename,
        "total_pages":  page_count,
        "total_slides": len(state.slide_contents or []),
        "message":      None,
        "steps":        len(state.history),
        "agentic":      True,
        "analytics":    tracker.report_dict(elapsed),
    }
