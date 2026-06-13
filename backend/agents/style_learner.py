"""
Style Learner Agent

After a pipeline run completes, this agent looks at the accumulated
run records in memory/runs/ and proposes new soft hints to add to
memory/style.yaml. The goal: each PDF the system processes makes it
SLIGHTLY smarter for the next one.

What patterns it looks for (examples):
  • Layout Picker repeatedly overrides mcq_slide → pyq_grid_slide for
    (subject=English, purpose=Revision). Next time, recommend pyq_grid_slide
    directly in the planner for that combination.
  • Bullets longer than 18 words consistently trigger overflow flags.
    Add a hint: keep bullets ≤ 14 words.
  • Plan Critic keeps removing spurious section_headings between MCQs.
    Reinforce the soft hint: never section_heading between same-set MCQs.

The agent is conservative — it only proposes hints with strong evidence
(confidence ≥ 0.7, supported by multiple runs OR a single clear failure).
Manually-edited rules in style.yaml are PRESERVED (we only ADD, never
overwrite).
"""

import json
from google.genai import types

from agents.gemini_client import client
from schemas.run_record   import RunRecord, StyleUpdate
from config import PLAN_CRITIC_MODEL
from pipeline.token_tracker import record_api_attempt, record_api_failure, record_usage


def _build_learner_prompt(
    recent_runs: list[RunRecord],
    current_style: dict,
) -> str:
    """One-shot LLM prompt that proposes new soft hints."""

    # Compact run summaries — we don't dump the full records into the prompt
    runs_summary = []
    for r in recent_runs[:15]:   # cap context size
        runs_summary.append({
            "timestamp":    r.timestamp,
            "subject":      r.subject,
            "purpose":      r.purpose,
            "class_level":  r.class_level,
            "language":     r.language,
            "pages":        r.page_count,
            "slides":       r.slide_count,
            "layouts":      r.layout_distribution,
            "bullet_avg":   r.bullet_length_stats.get("avg"),
            "bullet_max":   r.bullet_length_stats.get("max"),
            "title_max":    r.title_length_stats.get("max_chars"),
            "layout_overrides": [
                {"from": lo.from_layout, "to": lo.to_layout,
                 "reason": lo.reason[:60]}
                for lo in r.layout_overrides
            ],
            "plan_fixes": [
                {"action": pf.action, "detail": pf.detail[:60]}
                for pf in r.plan_fixes
            ],
            "faithfulness": [
                {"action": ff.fix_action, "n": ff.n_bullets,
                 "hint": (ff.hint or "")[:80]}
                for ff in r.faithfulness_flags
            ],
            "visual": [
                {"score": vf.score, "issues": vf.issue_types,
                 "hint": (vf.hint or "")[:80]}
                for vf in r.visual_flags
            ],
            "visual_retries": r.visual_retries,
        })

    return f"""You are the Style Learner agent for an AI PDF-to-PPT pipeline.

Your job: look at the last {len(recent_runs)} pipeline runs and propose
NEW soft hints to add to the system's style memory. These hints help the
planner, layout picker, and writer make better choices on future PDFs.

CURRENT memory/style.yaml content:
{json.dumps(current_style, indent=2, ensure_ascii=False)}

Recent run records (newest first):
{json.dumps(runs_summary, indent=2, ensure_ascii=False)}

PATTERNS TO LOOK FOR (be VERY specific):

A. Layout-picker recurring overrides
   If Layout Picker keeps changing one layout → another for the same
   (subject, purpose) combination, propose a hint so the planner picks
   the right one first time.
   Example hint key: "english_revision_short_mcq_layout"
            value : "For subject=English purpose=Revision: prefer pyq_grid_slide for short-option MCQs"

B. Bullet / title overflow patterns
   If the visual critic repeatedly flags text_overflow with hints to shorten,
   tighten the global max_bullet_words / max title length.
   Example hint key: "bullet_max_words_tight"
            value : "Keep bullets to ≤ 14 words; longer bullets overflow in body slides"

C. Plan-critic recurring fixes
   If Plan Critic keeps removing the same kind of slide (e.g. spurious
   section_headings between MCQs), reinforce that as a strong rule.

D. Faithfulness recurring causes
   If the writer often hallucinates specific kinds of facts (dates,
   attributions, examples), propose a hint to avoid that pattern.

E. Slide-count norms by purpose
   If purpose=Revision averages ~8 slides across runs, reinforce that
   target.

OUTPUT RULES — be CONSERVATIVE:
  • Propose a hint ONLY if at LEAST one of these is true:
      - it shows up in ≥ 2 runs OR
      - it's a single but SEVERE failure (e.g. wrong MCQ answer) where
        a rule could prevent it next time.
  • confidence must reflect the evidence (≥ 0.8 = clear pattern, 0.5-0.8 = mild)
  • evidence_runs must be the actual count of runs supporting it.
  • Keep `value` plain English, ≤ 120 characters.
  • Use snake_case for `key`.
  • DO NOT propose a hint that already exists in current style.yaml.
  • If there's nothing strong to add, return new_hints = []. THIS IS PREFERRED
    over noise.

Always set runs_analyzed = {len(recent_runs)}.
Return JSON only.
"""


def learn_from_runs(
    recent_runs: list[RunRecord],
    current_style: dict,
) -> StyleUpdate:
    """
    Single Gemini call that returns proposed style hints.
    Empty new_hints list = no clear pattern, leave style.yaml alone.
    """
    if not recent_runs:
        return StyleUpdate(new_hints=[], runs_analyzed=0,
                           summary="no runs to learn from")
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=StyleUpdate,
    )
    response = None
    try:
        record_api_attempt("critics", PLAN_CRITIC_MODEL)
        response = client.models.generate_content(
            model=PLAN_CRITIC_MODEL,
            contents=_build_learner_prompt(recent_runs, current_style),
            config=config,
        )
        record_usage("critics", response.usage_metadata, model=PLAN_CRITIC_MODEL)
        update = response.parsed
        return update
    except Exception as e:
        if response is None:
            record_api_failure("critics", PLAN_CRITIC_MODEL)
        print(f"  Style learner failed ({e}); skipping")
        return StyleUpdate(new_hints=[], runs_analyzed=len(recent_runs),
                           summary=f"failed: {e}")


def render_learner_report(update: StyleUpdate) -> str:
    """Pretty-print for orchestrator logs."""
    if not update.new_hints:
        return f"    No new style hints proposed ({update.runs_analyzed} runs analysed)."
    lines = [
        f"    Style Learner — {update.runs_analyzed} runs analysed",
        f"    Summary: {update.summary}" if update.summary else "",
        f"    Proposed {len(update.new_hints)} new hint(s):",
    ]
    for h in update.new_hints:
        lines.append(
            f"      • {h.key}  (conf {h.confidence:.2f}, "
            f"evidence={h.evidence_runs})"
        )
        lines.append(f"          → {h.value}")
    return "\n".join(l for l in lines if l)
