"""Smoke test: render one slide for EACH MCQ variant so we can eyeball layout.

Covers:
  1. Vertical MCQ — short stem, short options
  2. Vertical MCQ — medium options (wrap 1-2 lines)
  3. Vertical MCQ — long sentence options (wrap 3+ lines → widen + reflow)
  4. Assertion-Reason MCQ — long stem, mixed short/long options
  5. Long statement MCQ — slide-19 type (long stem + short opts → 2-column grid)
  6. MCQ grid — very short one/two-word options (2x2 template)
  7. PYQ MCQ — vertical with exam-year tag

Run:  cd backend && .venv/bin/python _smoke_mcq_types.py
Outputs PNGs to backend/outputs/_smoke_mcq/<n>_<name>.png
"""
import os
import fitz

from schemas.slide_content import SlideContent
from schemas.slide_plan import TemplateType
from schemas.request import PDFContext
from pipeline.ppt_generator import generate_pptx

OUT_DIR = "outputs/_smoke_mcq"
os.makedirs(OUT_DIR, exist_ok=True)

ctx = PDFContext(
    batch="Smoke Batch", purpose="Lecture Notes", subject="English",
    class_level="Competitive exam", language="English",
)

cases = [
    ("1_vertical_short", TemplateType.mcq_slide,
     "What is the capital of France?",
     ["Paris", "London", "Rome", "Berlin"],
     "Answer: (a) Paris"),

    ("2_vertical_medium", TemplateType.mcq_slide,
     "Why does the passage reject the idea that confidence and determination inherently guarantee success?",
     ["Because success is portrayed as structurally inaccessible",
      "Because failure is described as irrelevant to personal development",
      "Because both qualities are framed as situational and ethically constrained practices",
      "Because determination is presented as harmful to long term growth"],
     "Answer: (c)"),

    ("3_vertical_long_opts", TemplateType.mcq_slide,
     "According to the author, what is the primary reason that long-term planning often fails in volatile markets?",
     ["Because organisations consistently underestimate the compounding effect of small forecasting errors over multi-year horizons and rarely revise assumptions",
      "Because the people responsible for the plan are usually replaced before the plan can be evaluated, breaking accountability across the whole cycle",
      "Because incentive structures reward short-term wins, so resources are quietly diverted away from the slower long-term initiatives that were promised",
      "Because external shocks such as regulation, technology shifts and competitor moves invalidate the assumptions the plan was originally built upon"],
     "Answer: (a)"),

    ("4_assertion_reason", TemplateType.mcq_slide,
     "Assertion (A): Confidence, as described in the passage, is compatible with the presence of doubt rather than dependent on its elimination. Reason (R): Confidence is presented as a regulated form of self-judgment that enables action even when certainty is incomplete.",
     ["A is false, but R is true.",
      "A is true, but R is false.",
      "Both A and R are true, but R is not the correct explanation of A.",
      "Both A and R are true, and R is the correct explanation of A."],
     "Answer: (d)"),

    ("5_long_stmt_grid", TemplateType.mcq_slide,
     "Which of the following statements are correct based on the passage?\n1. The Greeks contributed to the empirical approach in astronomy through mathematical and observational methods.\n2. Astronomy today encompasses subfields like astrophysics and cosmology, which were not part of ancient astronomy.\n3. Stonehenge and the Nebra disk are examples of how ancient cultures integrated sky-watching into their daily lives.",
     ["1 and 2 only", "2 and 3 only", "All 1, 2, and 3", "1 and 3 only"],
     "Answer: (b)"),

    ("6_grid_short", TemplateType.mcq_grid_slide,
     "What was Dr. Carver by profession?",
     ["Doctor", "Scientist", "Politician", "Professor"],
     "Answer: (b) Scientist"),

    ("7_pyq_vertical", TemplateType.pyq_slide,
     "Which one of the following best describes the central idea of the passage?",
     ["Technological progress always outpaces ethical regulation in society",
      "Innovation and caution must be balanced through situational judgment",
      "Determination alone is sufficient to overcome structural barriers",
      "Confidence is incompatible with any form of lingering doubt"],
     "Exam: SSC CGL 2019\nAnswer: (b)"),
]

contents = []
for i, (name, layout, q, opts, notes) in enumerate(cases, start=1):
    contents.append(SlideContent(
        slide_number=i, title=q, bullets=opts,
        speaker_notes=notes, layout=layout,
    ))

pptx = generate_pptx(contents, ctx, filename="_smoke_mcq_types.pptx")

# pptx -> pdf -> per-page png
import subprocess
subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir",
                "outputs", pptx], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
pdf = pptx.replace(".pptx", ".pdf")
doc = fitz.open(pdf)
for idx, (name, *_rest) in enumerate(cases):
    pg = doc[idx]
    scale = 1200 / pg.rect.width
    pix = pg.get_pixmap(matrix=fitz.Matrix(scale, scale))
    path = os.path.join(OUT_DIR, f"{name}.png")
    pix.save(path)
    print("saved", path)
print("\nDONE — PNGs in", OUT_DIR)
