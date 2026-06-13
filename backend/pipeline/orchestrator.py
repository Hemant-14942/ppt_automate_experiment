import os
import asyncio
import time
import traceback
import yaml
from pipeline.pdf_loader import pdf_to_base64_images, get_pdf_page_count
from agents.extractor import extract_all_pages_async
from agents.profiler import profile_deck, render_strategy_report
from agents.planner import plan_slides
from agents.layout_picker import review_layouts, render_picker_report
from agents.plan_critic   import critique_plan, render_review_report
from agents.writer import write_all_slides_async, rewrite_slides_with_hints
from agents.qc_agent import run_qc, auto_fix, qc_report
from agents.visual_critic import (
    critique_deck_visually,
    critique_slides_visually,
    render_critique_report,
)
from agents.faithfulness_critic import (
    check_faithfulness,
    render_faithfulness_report,
)
from agents.style_learner import learn_from_runs, render_learner_report
from pipeline.plan_revisor import apply_revisions
from pipeline.faithfulness_revisor import apply_strips, collect_rewrite_hints
from pipeline.run_telemetry import save_run_record, load_recent_runs, print_slide_trace
from pipeline.profile_learner import learn_profiles, render_profiles_report
from pipeline.token_tracker import TokenTracker
from pipeline.style_writer  import merge_style_update, write_learned_profiles
from pipeline.ppt_generator import generate_pptx
from pipeline.fit_engine import reflow_slides, render_reflow_report, is_free_body_layout, label_continuation_titles
from pipeline.slide_cleanup import drop_placeholder_slides, render_cleanup_report, dedupe_tables, render_dedupe_report
from pipeline.pptx_to_pdf import is_available as libreoffice_available
from schemas.request import PDFContext
from config import STYLE_YAML, MEMORY_DIR, MAX_VISUAL_RETRIES, MAX_PAGINATION_ROUNDS



# Visual-critic issue types that mean "content physically does not fit" — these
# are best fixed by SPLITTING the slide (pagination), not by deleting content.
_OVERFLOW_ISSUE_TYPES = {"text_overflow", "off_screen"}


def _has_overflow_issue(critique) -> bool:
    return any(i.type in _OVERFLOW_ISSUE_TYPES for i in (critique.issues or []))


async def _run_visual_critique_loop(
    output_path: str,
    slide_contents: list,
    slide_plan,
    extracted_pages,
    context: PDFContext,
    style_rules: dict,
    output_filename: str,
    strategy=None,
) -> tuple[str, list, list, int]:
    """
    Closed-loop visual self-correction (Phase 3). Converges in two phases:

      PHASE A — Pagination: if the critic confirms a free-body slide (theory /
        summary / homework) still OVERFLOWS, we re-split it more aggressively
        (overflow_pressure↑) instead of asking the writer to delete content.
        Splitting renumbers slides, so we re-critique the FULL deck each round.

      PHASE B — Rewrite: remaining issues (wrong layout, long title, MCQ option
        overflow, …) are fixed by a targeted writer rewrite of just those
        slides, with a partial re-check. A no-progress guard breaks the loop if
        a round fails to reduce the flagged count.

    Returns (output_path, slide_contents, critiques, rounds_done).
    """
    rounds_done = 0

    print("STEP 7 — Visual critique (full deck)...")
    critiques = await critique_deck_visually(output_path, slide_contents)
    print(render_critique_report(critiques))

    # ── PHASE A — pagination convergence ────────────────────────────────────
    overflow_pressure = 0
    for p_round in range(1, MAX_PAGINATION_ROUNDS + 1):
        layout_by_num = {c.slide_number: c.layout for c in slide_contents}
        overflow_bad = [
            c for c in critiques
            if c.should_retry and _has_overflow_issue(c)
            and is_free_body_layout(layout_by_num.get(c.slide_number))
        ]
        if not overflow_bad:
            break

        overflow_pressure += 1
        print(f"STEP 7.A{p_round} — {len(overflow_bad)} slide(s) overflow; "
              f"re-paginating (pressure={overflow_pressure})...")
        slide_contents, reflow_log = reflow_slides(
            slide_contents, strategy, overflow_pressure=overflow_pressure
        )
        slide_contents, _ = label_continuation_titles(slide_contents)
        print(render_reflow_report(reflow_log))
        slide_contents = auto_fix(slide_contents, run_qc(slide_contents))
        output_path = generate_pptx(slide_contents, context, output_filename, strategy)
        rounds_done += 1

        # numbers changed → must re-critique the whole deck
        critiques = await critique_deck_visually(output_path, slide_contents)
        print(render_critique_report(critiques))
        print()

    # ── PHASE B — content/layout rewrite convergence ────────────────────────
    prev_bad_nums: set[int] = set()
    for attempt in range(1, MAX_VISUAL_RETRIES + 1):
        layout_by_num = {c.slide_number: c.layout for c in slide_contents}
        # Skip free-body overflow here — Phase A owns those (avoid data loss).
        bad = [
            c for c in critiques
            if c.should_retry and not (
                _has_overflow_issue(c)
                and is_free_body_layout(layout_by_num.get(c.slide_number))
            )
        ]
        if not bad:
            print("  No further content/layout fixes needed.\n")
            break

        bad_nums = {c.slide_number for c in bad}
        if bad_nums == prev_bad_nums:
            print(f"  No progress on slides {sorted(bad_nums)} — stopping retries.\n")
            break
        prev_bad_nums = bad_nums

        fixes = {
            c.slide_number: {
                "hint": c.content_fix_hint,
                "new_layout": c.suggested_layout,
            }
            for c in bad
        }
        pending = list(fixes.keys())
        print(f"STEP 7.B{attempt} — {len(bad)} slide(s) flagged — rewriting with hints...")

        slide_contents = await rewrite_slides_with_hints(
            slide_contents,
            slide_plan,
            extracted_pages,
            context,
            style_rules,
            fixes,
            strategy,
        )
        slide_contents = auto_fix(slide_contents, run_qc(slide_contents))
        output_path = generate_pptx(slide_contents, context, output_filename, strategy)
        rounds_done += 1

        print(f"STEP 7.B{attempt}b — Visual re-check ({len(pending)} slide(s))...")
        critiques = await critique_slides_visually(
            output_path,
            slide_contents,
            pending,
            previous_critiques=critiques,
        )
        print(render_critique_report(critiques))
        print()

    # Honest final status — some slides may remain flagged after the budget.
    remaining = [c for c in critiques if c.should_retry]
    if remaining:
        print(f"  {len(remaining)} slide(s) still flagged after the retry budget — "
              f"left as-is (no content dropped): "
              f"{sorted(c.slide_number for c in remaining)}\n")
    else:
        print("  All slides passed visual review.\n")

    return output_path, slide_contents, critiques, rounds_done


def _load_style_rules() -> dict:
    """Load learned style rules from memory/style.yaml. Returns {} if file missing."""
    if os.path.exists(STYLE_YAML):
        with open(STYLE_YAML, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def _empty_plan_review():
    """Placeholder used when the Plan Critic didn't run (so telemetry still works)."""
    from schemas.plan_review import PlanReview
    return PlanReview(overall_ok=True, fixes=[], narrative_note="(not run)")


def _agentic_mode_enabled() -> bool:
    """Phase 5 — agentic mode is opt-in via env var AGENTIC_MODE=1."""
    return os.environ.get("AGENTIC_MODE", "0").strip() in {"1", "true", "True", "yes"}


async def _background_telemetry(
    context,
    page_count,
    slide_contents,
    slide_plan,
    layout_suggestions,
    plan_review,
    faithfulness_reports,
    visual_critiques,
    visual_retries,
    style_rules,
    strategy=None,
    pagination_splits=0,
    tracker: TokenTracker | None = None,
    usage_snapshot=None,
    started_at: float | None = None,
) -> None:
    """
    Save run record + style learning OFF the user's request path.
    Any failure here is logged but never bubbles up — telemetry must
    never break a successful pipeline run.
    """
    try:
        record_path = save_run_record(
            context=context,
            page_count=page_count,
            slide_contents=slide_contents,
            slide_plan=slide_plan,
            layout_suggestions=layout_suggestions,
            plan_review=plan_review,
            faithfulness_reports=faithfulness_reports,
            visual_critiques=visual_critiques,
            visual_retries=visual_retries,
            final_status="success",
            strategy=strategy,
            pagination_splits=pagination_splits,
        )
        print(f"  [bg] Telemetry saved → {os.path.basename(record_path)}")

        recent_runs = load_recent_runs(limit=15)

        # Phase 4 — deterministic per-profile calibration (no LLM).
        try:
            profiles = learn_profiles(recent_runs)
            print(render_profiles_report(profiles))
            written = write_learned_profiles(profiles)
            if written:
                print(f"  [bg] Profile calibration updated ({len(written)}):")
                for line in written:
                    print(f"    - {line}")
        except Exception as pe:
            print(f"  [bg] Profile learner skipped ({pe})")

        # LLM style learner — qualitative free-text hints (unchanged).
        update = await asyncio.to_thread(
            learn_from_runs, recent_runs, style_rules
        )
        print(render_learner_report(update))
        applied = merge_style_update(update)
        if applied:
            print(f"  [bg] Style memory updated ({len(applied)} hint(s)):")
            for line in applied:
                print(f"    - {line}")
    except Exception as e:
        print(f"  [bg] Telemetry / learner skipped [{type(e).__name__}]: {e!r}")
        traceback.print_exc()
    finally:
        if tracker and usage_snapshot is not None and started_at is not None:
            elapsed = time.monotonic() - started_at
            print(tracker.summary_delta(usage_snapshot, elapsed))


async def run_pipeline_async(pdf_path: str, context: PDFContext) -> dict:
    """
    Dispatcher: chooses between the linear pipeline (default) and the
    LLM-driven agentic loop (Phase 5) based on the AGENTIC_MODE env var.
    """
    if _agentic_mode_enabled():
        from pipeline.agentic_loop import run_pipeline_agentic
        return await run_pipeline_agentic(pdf_path, context)
    return await _run_linear_pipeline(pdf_path, context)


async def _run_linear_pipeline(pdf_path: str, context: PDFContext) -> dict:
    """
    Full async pipeline — PDF + context in, .pptx file out.

    Steps:
      1. Load PDF → base64 images
      2. Extract ALL pages in PARALLEL (10x faster than sequential)
      3. Plan slide structure (single Gemini call)
      4. Write ALL slides in PARALLEL with full context sharing
      5. QC check + auto-fix
      6. Generate .pptx

    Returns dict with status, filename, total_pages, total_slides.
    """

    if not os.path.exists(pdf_path):
        return {"status": "error", "message": f"PDF not found: {pdf_path}"}

    safe_batch   = context.batch.replace(" ", "_").replace("/", "-")
    safe_subject = context.subject.replace(" ", "_")
    output_filename = f"{safe_subject}_{safe_batch}_{context.purpose}_slides.pptx"

    page_count = get_pdf_page_count(pdf_path)

    print(f"\n{'='*52}")
    print(f"  PDF to PPT Pipeline")
    print(f"{'='*52}")
    print(f"  Subject : {context.subject}")
    print(f"  Batch   : {context.batch}")
    print(f"  Purpose : {context.purpose}")
    print(f"  Level   : {context.class_level}")
    print(f"  Language: {context.language}")
    print(f"  Pages   : {page_count}")
    print(f"  Output  : {output_filename}")
    print(f"{'='*52}\n")

    tracker = TokenTracker()
    tracker.activate()
    pipeline_start = time.monotonic()

    try:
        # load style memory
        style_rules = _load_style_rules()
        if style_rules:
            print(f"  Style memory loaded ({len(style_rules)} rules)\n")

        # ── STEP 1: Load PDF ─────────────────────────────────
        print("STEP 1 — Loading PDF pages...")
        pages = pdf_to_base64_images(pdf_path)
        print(f"  Done — {len(pages)} pages loaded\n")

        # ── STEP 2: Parallel extraction ──────────────────────
        print("STEP 2 — Extracting content (parallel)...")
        extracted_pages = await extract_all_pages_async(pages, context)
        if not extracted_pages:
            return {"status": "error", "message": "No readable content found in PDF"}
        print()

        # ── STEP 2.5: Profile the document ───────────────────
        # One cheap call that classifies the PDF and picks a deck-wide strategy
        # (profile + density). This steers the planner, writer, and fit engine.
        print("STEP 2.5 — Profiling document (deck strategy)...")
        strategy = profile_deck(
            extracted_pages, context, style_rules.get("learned_profiles")
        )
        print(render_strategy_report(strategy))
        print()

        # ── STEP 3: Plan slides ──────────────────────────────
        print("STEP 3 — Planning slide structure...")
        slide_plan = plan_slides(extracted_pages, context, strategy)
        print_slide_trace(slide_plan)
        print()

        # Tracking variables for run telemetry (Phase 4 — Style Learner)
        layout_suggestions: list = []
        plan_review = None
        f_reports: list = []
        critiques: list = []
        pagination_splits: int = 0

        # ── STEP 3.5: PRE-WRITE REVIEW ───────────────────────
        # Two agents run in parallel against the draft plan:
        #   • Layout Picker → per-slide layout sanity check
        #   • Plan Critic   → deck-level structural review
        # Their suggestions are applied surgically by `apply_revisions`.
        print("STEP 3.5 — Pre-write review (Layout Picker + Plan Critic)...")
        try:
            layout_task = asyncio.create_task(
                review_layouts(slide_plan, extracted_pages, context)
            )
            critic_task = asyncio.to_thread(
                critique_plan, slide_plan, extracted_pages, context
            )
            layout_suggestions, plan_review = await asyncio.gather(
                layout_task, critic_task
            )
            print(render_picker_report(layout_suggestions))
            print(render_review_report(plan_review))

            slide_plan, change_log = apply_revisions(
                slide_plan, layout_suggestions, plan_review
            )
            if change_log:
                print(f"  Applied {len(change_log)} plan revision(s):")
                for line in change_log:
                    print(f"    - {line}")
            else:
                print("  No revisions applied — plan accepted as-is.")
        except Exception as e:
            print(f"  Pre-write review skipped ({e}) — using original plan.")
        print()

        # ── STEP 4: Parallel writing with full context ───────
        print("STEP 4 — Writing slides (parallel, full-context agents)...")
        all_slide_contents = await write_all_slides_async(
            slide_plan, extracted_pages, context, style_rules, strategy
        )
        print()

        # ── STEP 4.5: FAITHFULNESS CRITIC (anti-hallucination) ────
        # Compare every bullet against source pages; strip unsupported
        # ones in-place, rewrite slides with heavy hallucination.
        print("STEP 4.5 — Faithfulness check (anti-hallucination)...")
        try:
            f_reports = await check_faithfulness(
                all_slide_contents, slide_plan, extracted_pages
            )
            print(render_faithfulness_report(f_reports))

            all_slide_contents, strip_log = apply_strips(
                all_slide_contents, f_reports
            )
            for line in strip_log:
                print(f"    - {line}")

            rewrite_fixes = collect_rewrite_hints(f_reports)
            if rewrite_fixes:
                print(f"  Rewriting {len(rewrite_fixes)} hallucinated slide(s)...")
                all_slide_contents = await rewrite_slides_with_hints(
                    all_slide_contents,
                    slide_plan,
                    extracted_pages,
                    context,
                    style_rules,
                    rewrite_fixes,
                    strategy,
                )
        except Exception as e:
            print(f"  Faithfulness check skipped ({e})")
        print()

        # ── STEP 4.6: Drop empty / placeholder slides ────────────
        # Annotated targets the extractor never captured can leave behind
        # "Content missing" placeholder slides — remove them before generation.
        print("STEP 4.6 — Dropping empty/placeholder slides...")
        all_slide_contents, cleanup_log = drop_placeholder_slides(all_slide_contents)
        print(render_cleanup_report(cleanup_log))
        all_slide_contents, dedupe_log = dedupe_tables(all_slide_contents)
        print(render_dedupe_report(dedupe_log))
        print()

        # ── STEP 4.7: Fit & reflow — paginate overflowing slides ──
        # Content-adaptive: instead of truncating long slides, split them into
        # continuation slides so nothing is lost and text stays readable.
        print("STEP 4.7 — Fit & reflow (pagination)...")
        all_slide_contents, reflow_log = reflow_slides(all_slide_contents, strategy)
        all_slide_contents, _ = label_continuation_titles(all_slide_contents)
        pagination_splits = len(reflow_log)   # Phase-4 outcome signal
        print(render_reflow_report(reflow_log))
        print()

        # ── STEP 5: QC check + auto-fix ─────────────────────
        print("STEP 5 — Quality check...")
        issues = run_qc(all_slide_contents)
        all_slide_contents = auto_fix(all_slide_contents, issues)
        print(f"  {qc_report(issues)}\n")

        # ── STEP 6: Generate PPTX ────────────────────────────
        print("STEP 6 — Generating PowerPoint file...")
        output_path = generate_pptx(all_slide_contents, context, output_filename, strategy)
        print()

        # ── STEP 7: Visual critique + auto-retry loop ─────────
        retries_done = 0
        if libreoffice_available():
            output_path, all_slide_contents, critiques, retries_done = (
                await _run_visual_critique_loop(
                    output_path,
                    all_slide_contents,
                    slide_plan,
                    extracted_pages,
                    context,
                    style_rules,
                    output_filename,
                    strategy,
                )
            )
        else:
            print("STEP 7 — Visual critique skipped (LibreOffice not available)\n")

        # ── STEP 8: Telemetry + Style Learner — BACKGROUND ────
        # Fire-and-forget so the user response isn't blocked. The deck is
        # already saved; telemetry + learning is pure housekeeping.
        print("STEP 8 — Scheduling telemetry + style learning in background...")
        bg_snapshot = tracker.snapshot()
        bg_started_at = time.monotonic()
        asyncio.create_task(_background_telemetry(
            context=context,
            page_count=page_count,
            slide_contents=all_slide_contents,
            slide_plan=slide_plan,
            layout_suggestions=layout_suggestions,
            plan_review=plan_review or _empty_plan_review(),
            faithfulness_reports=f_reports,
            visual_critiques=critiques,
            visual_retries=retries_done,
            style_rules=style_rules,
            strategy=strategy,
            pagination_splits=pagination_splits,
            tracker=tracker,
            usage_snapshot=bg_snapshot,
            started_at=bg_started_at,
        ))

        elapsed = time.monotonic() - pipeline_start
        print(f"{'='*52}")
        print(f"  Pipeline complete")
        print(f"  Input  : {pdf_path} ({page_count} pages)")
        print(f"  Output : {output_path} ({slide_plan.total_slides} slides)")
        if retries_done:
            print(f"  Visual critic triggered {retries_done} retry round(s)")
        if issues:
            print(f"  QC     : {sum(1 for i in issues if i.auto_fixable)} auto-fixed, "
                  f"{sum(1 for i in issues if not i.auto_fixable)} need review")
        print(f"{'='*52}\n")
        print(tracker.summary(elapsed))

        return {
            "status":       "success",
            "filename":     output_filename,
            "total_pages":  page_count,
            "total_slides": slide_plan.total_slides,
            "message":      None,
            "analytics":    tracker.report_dict(elapsed),
        }

    except Exception as e:
        elapsed = time.monotonic() - pipeline_start
        print(f"\n  ERROR — Pipeline failed [{type(e).__name__}]: {e!r}")
        traceback.print_exc()
        print(tracker.summary(elapsed))
        return {"status": "error", "message": str(e)}
