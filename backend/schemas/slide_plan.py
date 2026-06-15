""" Defines the slide plan — how many slides, what template each uses, which pages each"""
from pydantic import BaseModel
from enum import Enum


class TemplateType(str, Enum):
    # ── Opening / structural ────────────────────────────────────────────────
    title_slide      = "title_slide"        # very first slide — chapter/subject/purpose
    recap_slide      = "recap_slide"        # "Recap of previous lecture" — numbered points
    topics_slide     = "topics_slide"       # "Topics to be covered" — numbered points
    section_heading  = "section_heading"    # divider when a new topic begins

    # ── Body ────────────────────────────────────────────────────────────────
    theory_slide     = "theory_slide"       # explanation / definitions / formula list
    table_slide      = "table_slide"        # source had a TABLE — show it as a real
                                            # rendered table (headers + rows). No body
                                            # bullets; the slide is all table.
    theory_table_slide = "theory_table_slide"  # short theory bullets ABOVE a table.
                                            # Use when the source page has both an
                                            # explanatory passage AND a small reference
                                            # table that belong together on one slide.
    passage_slide    = "passage_slide"      # cloze / reading-comprehension passage —
                                            # verbatim paragraph with blanks (__X__, (1))
                                            # preserved; followed by per-blank question slides
    mcq_slide        = "mcq_slide"          # MCQ — 4 options in single column
    mcq_grid_slide   = "mcq_grid_slide"     # MCQ — 4 short options in 2x2 grid
    question_only    = "question_only"      # long-answer / subjective question — no options
    pyq_slide        = "pyq_slide"          # MCQ with "PYQ Exam-Year" tag, single column
    pyq_grid_slide   = "pyq_grid_slide"     # PYQ MCQ with 2x2 grid
    pyq_question_only= "pyq_question_only"  # PYQ subjective question

    # ── Diagrams / figures ────────────────────────────────────────────────────
    figure_slide     = "figure_slide"       # a detected diagram/figure/formula —
                                            # rendered as the cropped image OR a
                                            # text description, placed right after
                                            # the question/section it belongs to.

    # ── Closing ─────────────────────────────────────────────────────────────
    summary          = "summary"            # key takeaways at end
    homework_slide   = "homework_slide"     # practice / assignment list
    thank_you_slide  = "thank_you_slide"    # decorative closing slide


class SlideOutline(BaseModel):
    slide_number:    int
    title:           str
    template:        TemplateType
    source_pages:    list[int]    # which PDF pages this slide covers
    key_points:      list[str]    # main points planner identified
    include_diagram: bool
    emphasis:        list[str]    # things instructor marked as important


class FullSlidePlan(BaseModel):
    total_slides: int
    slides:       list[SlideOutline]
