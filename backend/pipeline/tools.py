"""
Tools that the LLM Orchestrator (Phase 5) can call.

Each tool:
  • Reads state from the PipelineState dataclass.
  • Performs its side-effect (LLM call, file I/O, etc.).
  • Mutates state in-place.
  • Returns a short note describing what happened (logged + shown to the
    orchestrator on its next decision).

Tools are written so the LLM does NOT need to pass arguments — every input
the tool needs is already on `state`. This keeps decisions simple: just
pick a tool name.

A tool may be called multiple times (e.g. visual_critique → rewrite_slides
→ visual_critique again) and must be idempotent / safe to repeat.
"""
import os
import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional, Any

from pipeline.pdf_loader        import pdf_to_base64_images
from agents.extractor           import extract_all_pages_async
from agents.profiler            import profile_deck
from agents.planner             import plan_slides
from agents.layout_picker       import review_layouts
from agents.plan_critic         import critique_plan
from agents.writer              import write_all_slides_async, rewrite_slides_with_hints
from agents.faithfulness_critic import check_faithfulness
from agents.visual_critic       import critique_deck_visually, critique_slides_visually
from agents.qc_agent            import run_qc, auto_fix
from pipeline.plan_revisor      import apply_revisions
from pipeline.faithfulness_revisor import apply_strips, collect_rewrite_hints
from pipeline.fit_engine         import reflow_slides, label_continuation_titles
from pipeline.slide_cleanup      import drop_placeholder_slides, dedupe_tables
from pipeline.ppt_generator     import generate_pptx
from pipeline.pptx_to_pdf       import is_available as libreoffice_available

from schemas.request        import PDFContext
from schemas.deck_strategy  import DeckStrategy
from schemas.extracted_page import ExtractedPage
from schemas.slide_plan     import FullSlidePlan
from schemas.slide_content  import SlideContent
from schemas.plan_review    import LayoutSuggestion, PlanReview
from schemas.faithfulness   import FaithfulnessReport
from schemas.critic_report  import SlideCritique
from schemas.agent_state    import ToolName, ActionLog
from config import MAX_VISUAL_RETRIES, VISUAL_CRITIC_SKIP


# ──────────────────────────────────────────────────────────────────────────
# Pipeline state (the LLM's "world")
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class PipelineState:
    """Everything the agentic orchestrator needs to track."""
    pdf_path:             str
    context:              PDFContext
    output_filename:      str
    style_rules:          dict          = field(default_factory=dict)

    # built up as tools run
    pages_base64:         Optional[list[dict]] = None
    extracted_pages:      Optional[list[ExtractedPage]] = None
    strategy:             Optional[DeckStrategy] = None
    slide_plan:           Optional[FullSlidePlan] = None
    slide_contents:       Optional[list[SlideContent]] = None
    output_path:          Optional[str] = None

    # critique results
    layout_suggestions:   list[LayoutSuggestion] = field(default_factory=list)
    plan_review:          Optional[PlanReview] = None
    faithfulness_reports: list[FaithfulnessReport] = field(default_factory=list)
    visual_critiques:     list[SlideCritique] = field(default_factory=list)
    slides_pending_recheck: list[int] = field(default_factory=list)

    # bookkeeping
    visual_retries:       int = 0
    visual_attempted:     bool = False     # true once visual_critique has run (even if skipped)
    plan_fixes_applied:   bool = False     # true once apply_plan_fixes has run — never re-apply
    faithfulness_attempted: bool = False
    history:              list[ActionLog] = field(default_factory=list)
    done:                 bool = False
    fatal_error:          Optional[str] = None

    # ─── summary the LLM sees on each decision ───────────────────────────
    def summarize(self) -> dict:
        return {
            "extracted":       self.extracted_pages is not None,
            "n_extracted":     len(self.extracted_pages or []),
            "planned":         self.slide_plan is not None,
            "n_planned":       self.slide_plan.total_slides if self.slide_plan else 0,
            "layout_reviewed": bool(self.layout_suggestions),
            "n_layout_overrides": sum(
                1 for s in self.layout_suggestions
                if s.suggested_layout != s.current_layout and s.confidence >= 0.8
            ),
            "plan_reviewed":   self.plan_review is not None,
            "n_plan_fixes":    len(self.plan_review.fixes) if self.plan_review else 0,
            "plan_fixes_applied": self.plan_fixes_applied,
            "written":         self.slide_contents is not None,
            "n_written":       len(self.slide_contents or []),
            "faithfulness_checked": self.faithfulness_attempted,
            "n_faith_strips":  sum(1 for r in self.faithfulness_reports
                                   if r.fix_action == "strip_bullets"),
            "n_faith_rewrites": sum(1 for r in self.faithfulness_reports
                                    if r.fix_action == "rewrite"),
            "pptx_generated":  self.output_path is not None,
            "visual_critiqued": self.visual_attempted,
            "n_visual_bad":    sum(1 for c in self.visual_critiques
                                   if c.should_retry),
            "slides_pending_recheck": self.slides_pending_recheck,
            "visual_retries_used": self.visual_retries,
            "visual_retry_budget": MAX_VISUAL_RETRIES,
            "libreoffice_available": libreoffice_available(),
            "history": [
                {"step": a.step, "tool": a.tool.value, "note": a.note}
                for a in self.history[-8:]
            ],
        }


# ──────────────────────────────────────────────────────────────────────────
# Internal helper — record an action result
# ──────────────────────────────────────────────────────────────────────────

def _log(state: PipelineState, tool: ToolName, reasoning: str,
         note: str, dur_ms: int, ok: bool) -> None:
    state.history.append(ActionLog(
        step=len(state.history) + 1,
        tool=tool,
        reasoning=reasoning[:200],
        succeeded=ok,
        duration_ms=dur_ms,
        note=note[:240],
    ))


# ──────────────────────────────────────────────────────────────────────────
# Tool implementations  (one per ToolName)
# ──────────────────────────────────────────────────────────────────────────

async def _t_extract(state: PipelineState) -> str:
    state.pages_base64 = pdf_to_base64_images(state.pdf_path)
    state.extracted_pages = await extract_all_pages_async(
        state.pages_base64, state.context
    )
    return f"extracted {len(state.extracted_pages)} pages"


async def _t_plan(state: PipelineState) -> str:
    if not state.extracted_pages:
        raise RuntimeError("plan_slides requires prior extract_pdf")
    # Profile the document once (lazily) so the plan is strategy-aware.
    if state.strategy is None:
        state.strategy = await asyncio.to_thread(
            profile_deck, state.extracted_pages, state.context,
            state.style_rules.get("learned_profiles"),
        )
    state.slide_plan = await asyncio.to_thread(
        plan_slides, state.extracted_pages, state.context, state.strategy
    )
    return (
        f"planned {state.slide_plan.total_slides} slides "
        f"(profile={state.strategy.profile.value}, density={state.strategy.density.value})"
    )


async def _t_review_layouts(state: PipelineState) -> str:
    if not state.slide_plan:
        raise RuntimeError("review_layouts requires a slide_plan")
    state.layout_suggestions = await review_layouts(
        state.slide_plan, state.extracted_pages, state.context
    )
    n_changes = sum(1 for s in state.layout_suggestions
                    if s.suggested_layout != s.current_layout and s.confidence >= 0.8)
    return f"{n_changes} high-confidence layout change(s) suggested"


async def _t_critique_plan(state: PipelineState) -> str:
    if not state.slide_plan:
        raise RuntimeError("critique_plan requires a slide_plan")
    state.plan_review = await asyncio.to_thread(
        critique_plan, state.slide_plan, state.extracted_pages, state.context
    )
    return f"{len(state.plan_review.fixes)} structural fix(es) proposed"


async def _t_apply_plan_fixes(state: PipelineState) -> str:
    if not state.slide_plan:
        raise RuntimeError("apply_plan_fixes requires a slide_plan")
    review = state.plan_review or PlanReview(
        overall_ok=True, fixes=[], narrative_note="(no review run)"
    )
    new_plan, log = apply_revisions(
        state.slide_plan, state.layout_suggestions, review
    )
    state.slide_plan = new_plan
    # Mark as applied so neither the LLM nor the linear fallback can re-apply
    # the same fixes — re-applying mutates the plan again and forces a costly
    # full re-write of every slide.
    state.plan_fixes_applied = True
    return f"applied {len(log)} revision(s) → {new_plan.total_slides} slides"


async def _t_write(state: PipelineState) -> str:
    if not state.slide_plan:
        raise RuntimeError("write_slides requires a slide_plan")
    state.slide_contents = await write_all_slides_async(
        state.slide_plan, state.extracted_pages, state.context,
        state.style_rules, state.strategy,
    )
    return f"wrote {len(state.slide_contents)} slide(s)"


async def _t_check_faithfulness(state: PipelineState) -> str:
    if not state.slide_contents:
        raise RuntimeError("check_faithfulness requires written slides")
    state.faithfulness_reports = await check_faithfulness(
        state.slide_contents, state.slide_plan, state.extracted_pages
    )
    state.faithfulness_attempted = True
    n_strip   = sum(1 for r in state.faithfulness_reports
                    if r.fix_action == "strip_bullets")
    n_rewrite = sum(1 for r in state.faithfulness_reports
                    if r.fix_action == "rewrite")
    return f"{n_strip} strip + {n_rewrite} rewrite flag(s)"


async def _t_apply_faithfulness(state: PipelineState) -> str:
    if not state.faithfulness_reports:
        return "no faithfulness reports to apply"
    state.slide_contents, strip_log = apply_strips(
        state.slide_contents, state.faithfulness_reports
    )
    fixes = collect_rewrite_hints(state.faithfulness_reports)
    if fixes:
        state.slide_contents = await rewrite_slides_with_hints(
            state.slide_contents, state.slide_plan, state.extracted_pages,
            state.context, state.style_rules, fixes, state.strategy,
        )
    # Clear the reports so the orchestrator doesn't loop forever on them
    state.faithfulness_reports = []
    return f"stripped {len(strip_log)} + rewrote {len(fixes)} slide(s)"


async def _t_generate(state: PipelineState) -> str:
    if not state.slide_contents:
        raise RuntimeError("generate_pptx requires written slides")
    # drop empty/placeholder slides, then paginate, before QC + generation
    state.slide_contents, _ = drop_placeholder_slides(state.slide_contents)
    state.slide_contents, _ = dedupe_tables(state.slide_contents)
    state.slide_contents, _ = reflow_slides(state.slide_contents, state.strategy)
    state.slide_contents, _ = label_continuation_titles(state.slide_contents)
    # always run QC + auto-fix immediately before generation
    issues = run_qc(state.slide_contents)
    state.slide_contents = auto_fix(state.slide_contents, issues)
    state.output_path = await asyncio.to_thread(
        generate_pptx, state.slide_contents, state.context, state.output_filename
    )
    return f"generated → {os.path.basename(state.output_path)}"


async def _t_visual_critique(state: PipelineState) -> str:
    if not state.output_path:
        raise RuntimeError("visual_critique requires generated pptx")
    state.visual_attempted = True
    if VISUAL_CRITIC_SKIP:
        return "skipped — VISUAL_CRITIC_SKIP=true in .env"
    if not libreoffice_available():
        return "skipped — LibreOffice not available; treating as no issues"

    pending = state.slides_pending_recheck
    if pending:
        state.visual_critiques = await critique_slides_visually(
            state.output_path,
            state.slide_contents,
            pending,
            previous_critiques=state.visual_critiques,
        )
        state.slides_pending_recheck = []
        n_bad = sum(1 for c in state.visual_critiques if c.should_retry)
        return f"re-checked {len(pending)} slide(s); {n_bad} still flagged"

    state.visual_critiques = await critique_deck_visually(
        state.output_path, state.slide_contents
    )
    n_bad = sum(1 for c in state.visual_critiques if c.should_retry)
    return f"{n_bad} slide(s) flagged out of {len(state.visual_critiques)}"


async def _t_rewrite_from_visual(state: PipelineState) -> str:
    """Rewrite flagged slides with visual critic hints, then regenerate."""
    bad = [c for c in state.visual_critiques if c.should_retry]
    if not bad:
        return "no slides flagged — nothing to rewrite"
    fixes = {
        c.slide_number: {
            "hint": c.content_fix_hint,
            "new_layout": c.suggested_layout,
        }
        for c in bad
    }
    state.slide_contents = await rewrite_slides_with_hints(
        state.slide_contents, state.slide_plan, state.extracted_pages,
        state.context, state.style_rules, fixes, state.strategy,
    )
    # Always regenerate after a rewrite so visual_critique sees fresh output
    issues = run_qc(state.slide_contents)
    state.slide_contents = auto_fix(state.slide_contents, issues)
    state.output_path = await asyncio.to_thread(
        generate_pptx, state.slide_contents, state.context, state.output_filename
    )
    rewritten = list(fixes.keys())
    state.visual_critiques = [
        c for c in state.visual_critiques if c.slide_number not in rewritten
    ]
    state.slides_pending_recheck = rewritten
    state.visual_retries += 1
    return f"rewrote {len(fixes)} slide(s) + regenerated pptx; pending re-check"


async def _t_finalize(state: PipelineState) -> str:
    if not state.output_path:
        raise RuntimeError("cannot finalize — no pptx generated yet")
    state.done = True
    return "pipeline finalized"


# ──────────────────────────────────────────────────────────────────────────
# Dispatcher
# ──────────────────────────────────────────────────────────────────────────\\
_TOOL_FUNCS = {
    ToolName.EXTRACT:            _t_extract,
    ToolName.PLAN:               _t_plan,
    ToolName.REVIEW_LAYOUTS:     _t_review_layouts,
    ToolName.CRITIQUE_PLAN:      _t_critique_plan,
    ToolName.APPLY_PLAN_FIXES:   _t_apply_plan_fixes,
    ToolName.WRITE:              _t_write,
    ToolName.CHECK_FAITHFULNESS: _t_check_faithfulness,
    ToolName.APPLY_FAITHFULNESS: _t_apply_faithfulness,
    ToolName.GENERATE_PPTX:      _t_generate,
    ToolName.VISUAL_CRITIQUE:    _t_visual_critique,
    ToolName.REWRITE_SLIDES:     _t_rewrite_from_visual,
    ToolName.FINALIZE:           _t_finalize,
}


async def execute_tool(
    state:     PipelineState,
    tool:      ToolName,
    reasoning: str = "",
) -> tuple[bool, str]:
    """
    Run a tool, mutate state in-place, log the action.
    Returns (ok, note). The orchestrator agent uses `note` as feedback.
    """
    if tool not in _TOOL_FUNCS:
        msg = f"unknown tool: {tool}"
        _log(state, tool, reasoning, msg, 0, False)
        return False, msg

    start = time.monotonic()
    try:
        note = await _TOOL_FUNCS[tool](state)
        dur_ms = int((time.monotonic() - start) * 1000)
        _log(state, tool, reasoning, note, dur_ms, True)
        return True, note
    except Exception as e:
        dur_ms = int((time.monotonic() - start) * 1000)
        note = f"error: {e}"
        _log(state, tool, reasoning, note, dur_ms, False)
        return False, note
