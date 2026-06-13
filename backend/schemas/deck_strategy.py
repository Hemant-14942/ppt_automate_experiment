"""
DeckStrategy — the structured "plan of attack" the Profiler agent produces
once, up front, for a whole PDF.

WHY THIS EXISTS
───────────────
Different PDFs need fundamentally different decks:
  • a question bank → one question per slide, terse
  • lecture notes  → thorough theory slides, verbose, paginated
  • a formula sheet→ one formula per slide, big text

Phase 1 made each slide adapt its *fit* (font + pagination). Phase 2 lets the
system also adapt its *feel*: an LLM classifies the document and emits this
object, which then steers the planner (structure), the writer (verbosity), and
the fit engine (how aggressively to paginate for readability).

Everything downstream treats DeckStrategy as OPTIONAL — if profiling fails, the
pipeline falls back to its prior behaviour.
"""
from pydantic import BaseModel, Field
from enum import Enum


class ContentProfile(str, Enum):
    theory         = "theory"          # definitions / explanations, few or no questions
    lecture_notes  = "lecture_notes"   # full teaching content, examples, derivations
    dpp            = "dpp"             # daily practice problems — questions + hints
    question_bank  = "question_bank"   # many MCQs / PYQs
    formula_sheet  = "formula_sheet"   # formulas / key results, minimal prose
    mixed          = "mixed"           # a genuine blend of theory + questions


class Density(str, Enum):
    terse    = "terse"      # short phrases, few bullets — Revision / Quick recap
    balanced = "balanced"   # moderate detail
    verbose  = "verbose"    # full sentences, complete coverage — Lecture notes


class DeckStrategy(BaseModel):
    """The Profiler's structured decision for the whole deck."""
    profile:  ContentProfile
    density:  Density

    # Structure guidance (steers the Planner)
    one_item_per_slide: bool = Field(
        default=False,
        description="True for DPP / question banks — every question/problem gets its own slide.",
    )
    prefer_theory_for_concepts: bool = Field(
        default=True,
        description="Use theory_slide for explanatory passages (vs section dividers).",
    )

    # Verbosity guidance (steers the Writer — SOFT hints, never hard truncation)
    target_bullets_per_theory_slide: int = Field(
        default=5,
        description="Roughly how many points a theory slide should aim for before the fit engine paginates.",
    )
    bullet_style: str = Field(
        default="sentence",
        description="'phrase' (terse), 'sentence' (1-2 sentences), or 'paragraph' (thorough).",
    )

    rationale: str = Field(
        default="",
        description="One short sentence explaining the classification.",
    )

    # ── Defaults used when profiling is unavailable ─────────────────────────
    @classmethod
    def default(cls) -> "DeckStrategy":
        return cls(
            profile=ContentProfile.mixed,
            density=Density.balanced,
            one_item_per_slide=False,
            prefer_theory_for_concepts=True,
            target_bullets_per_theory_slide=5,
            bullet_style="sentence",
            rationale="(profiler not run — using balanced defaults)",
        )
