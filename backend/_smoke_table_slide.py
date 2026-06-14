"""Throwaway smoke test: take the borderless 'Indian vs Western Civilization'
comparison exactly as extraction would put it in main_text (tab-aligned), run it
through the REAL recovery path (_recover_table_from_text), then render the
resulting table_slide with the production ppt_generator and export a PNG.

Run:  python _smoke_table_slide.py
"""
import os

from schemas.slide_content import SlideContent
from schemas.slide_plan import TemplateType
from schemas.request import PDFContext
from agents.writer import _recover_table_from_text
from pipeline.ppt_generator import generate_pptx
from pipeline.pptx_to_pdf import convert_pptx_to_pdf
from pipeline.pdf_loader import pdf_pages_to_png_bytes

CTX = PDFContext(
    batch="7777", purpose="Lecture Notes", subject="Social Science",
    class_level="Class 9-10", language="English",
)

# This is what the extractor drops into main_text for the borderless comparison
# table (tab-separated, no grid lines) — the case that used to get prosified.
SOURCE = [{
    "main_text": (
        "According to Gandhi: Indian vs Western Civilization\n"
        "Indian Civilization\tWestern Civilization\n"
        "Based on morality\tBased on materialism\n"
        "Teaches self-control\tEncourages endless desires\n"
        "Promotes simplicity\tPromotes luxury\n"
        "Focuses on spiritual growth\tFocuses on physical comfort"
    )
}]

# 1. Recover the structured table the same way the writer safety net does.
table = _recover_table_from_text(SOURCE)
print("Recovered table:")
print("  headers:", table.headers)
for r in table.rows:
    print("  row    :", r)

# 2. Build the slide the renderer will draw.
slide = SlideContent(
    slide_number=1,
    title="Indian vs Western Civilization",
    bullets=[],
    speaker_notes="",
    layout=TemplateType.table_slide,
    table_data=table,
)

# 3. Render with the production generator → PPTX → PDF → PNG.
pptx_path = generate_pptx([slide], CTX, "_smoke_table_slide.pptx")
print(f"  pptx -> {pptx_path}")
pdf_path = convert_pptx_to_pdf(pptx_path)
print(f"  pdf  -> {pdf_path}")
pngs = pdf_pages_to_png_bytes(pdf_path, dpi=130, page_indices=[0])
png_path = os.path.join(os.path.dirname(pptx_path), "_smoke_table_slide.png")
with open(png_path, "wb") as f:
    f.write(pngs[0])
print(f"  png  -> {png_path}")
