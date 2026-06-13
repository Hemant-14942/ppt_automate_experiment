"""Throwaway: regenerate ONLY the slide-9 Assertion/Reason MCQ with the current
code (slide-9 badge fix applied), render to PNG so we can eyeball the badges."""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".smoke_deps"))

from schemas.slide_content import SlideContent
from schemas.slide_plan import TemplateType
from schemas.request import PDFContext
from pipeline.ppt_generator import generate_pptx
from pipeline.pptx_to_pdf import convert_pptx_to_pdf
from pipeline.pdf_loader import pdf_pages_to_png_bytes

CTX = PDFContext(
    batch="verify", purpose="Lecture notes", subject="English",
    class_level="Competitive exam", language="English",
)

slide9 = SlideContent(
    slide_number=1,
    title=(
        "Assertion (A): Confidence is compatible with the presence of doubt "
        "rather than dependent on its elimination. Reason (R): Confidence is "
        "presented as a regulated form of self-judgment that enables action "
        "even when certainty is incomplete."
    ),
    bullets=[
        "A is false, but R is true.",
        "A is true, but R is false.",
        "Both A and R are true, but R is not the correct explanation of A.",
        "Both A and R are true, and R is the correct explanation of A.",
    ],
    speaker_notes="",
    layout=TemplateType.mcq_slide,
)

pptx_path = generate_pptx([slide9], CTX, "_verify_slide9.pptx")
print(f"  pptx → {pptx_path}")
pdf_path = convert_pptx_to_pdf(pptx_path)
print(f"  pdf  → {pdf_path}")
pngs = pdf_pages_to_png_bytes(pdf_path, dpi=130, page_indices=[0])
png_path = os.path.join(os.path.dirname(pptx_path), "_verify_slide9.png")
with open(png_path, "wb") as f:
    f.write(pngs[0])
print(f"  png  → {png_path}")
