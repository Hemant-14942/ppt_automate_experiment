"""
Schemas for the Faithfulness Critic agent.

The Faithfulness Critic compares each slide's CONTENT against the SOURCE
PAGES that slide was supposed to be drawn from, and flags any text the
writer made up. This is an "anti-hallucination" guard that runs AFTER the
writer but BEFORE the generator — so we never ship a slide that lies.
"""
from typing import Optional
from pydantic import BaseModel


class BulletVerdict(BaseModel):
    """One verdict on one bullet."""
    bullet_index: int        # 0-based position in slide.bullets
    status:       str        # "supported" | "paraphrased" | "unsupported" | "contradicts"
    evidence:     Optional[str] = None     # short quote / page number, if supported


class FaithfulnessReport(BaseModel):
    """
    Per-slide verdict from the Faithfulness Critic.

    `fix_action` is what the orchestrator should do:
      - "ok"            : nothing wrong, keep slide as-is
      - "strip_bullets" : remove the bullets flagged 'unsupported' or
                          'contradicts'; keep the rest
      - "rewrite"       : too much hallucination — rewrite whole slide
                          using ONLY source page content (writer is called
                          again with a fix_hint)
    """
    slide_number:            int
    bullet_verdicts:         list[BulletVerdict] = []
    title_status:            str    # same set as bullet status
    speaker_notes_status:    str    # same set
    fix_action:              str    # ok | strip_bullets | rewrite
    fix_hint:                Optional[str] = None   # used when fix_action="rewrite"
