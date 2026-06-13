"""
Smoke tests for all pipeline fixes:
  1. Control-character sanitization (_x000D_, _x0008_, etc.)
  2. Currency symbol reordering (₹ before number)
  3. Table detection flags in ExtractedPage
  4. Solution-slide visual detection
  5. Table rendering in PPT generator (end-to-end PPTX build)
  6. SlideContent sanitization validators

Run:  cd backend && python -m pytest tests/ -v
 or:  cd backend && python tests/test_sanitization_and_layouts.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas.extracted_page import ExtractedPage, ContentType, _sanitize_text
from schemas.slide_content import SlideContent, TableBlock, _sanitize_slide_text
from schemas.slide_plan import TemplateType
from pipeline.ppt_generator import generate_pptx, _is_solution_slide
from schemas.request import PDFContext


# ─────────────────────────────────────────────────────────────────────────────
# 1. Control-character sanitization
# ─────────────────────────────────────────────────────────────────────────────

def test_sanitize_text_strips_word_xml_escapes():
    dirty = "Cash Outflow per year _x000D_\n× PVAF"
    clean = _sanitize_text(dirty)
    assert "_x000D_" not in clean
    assert "× PVAF" in clean

def test_sanitize_text_strips_backspace_escapes():
    dirty = "_x0008__x0008_ 71.375 Crore"
    clean = _sanitize_text(dirty)
    assert "_x0008_" not in clean
    assert "71.375" in clean

def test_sanitize_text_preserves_normal_text():
    normal = "The answer is (a) Shoal"
    assert _sanitize_text(normal) == normal

def test_sanitize_text_handles_none():
    assert _sanitize_text(None) is None

def test_sanitize_text_handles_empty():
    assert _sanitize_text("") == ""

def test_extracted_page_auto_sanitizes():
    page = ExtractedPage(
        page_number=1,
        content_type=ContentType.text_heavy,
        main_text="Hello _x000D_ World _x0008_ test",
        should_skip=False,
    )
    assert "_x000D_" not in page.main_text
    assert "_x0008_" not in page.main_text
    assert "Hello" in page.main_text
    assert "World" in page.main_text


# ─────────────────────────────────────────────────────────────────────────────
# 2. Currency symbol reordering
# ─────────────────────────────────────────────────────────────────────────────

def test_currency_reorder_rupee_after_number():
    dirty = "71.375 Crore ₹"
    clean = _sanitize_slide_text(dirty)
    assert clean.startswith("₹71.375")

def test_currency_reorder_dollar():
    dirty = "5,000 $"
    clean = _sanitize_slide_text(dirty)
    assert "5,000" in clean
    assert clean.index("$") < clean.index("5")

def test_currency_already_correct():
    correct = "₹25 Crore"
    assert _sanitize_slide_text(correct) == correct

def test_slide_content_auto_sanitizes_title():
    slide = SlideContent(
        slide_number=1,
        title="Cost is 25 Crore ₹",
        bullets=["The answer is _x000D_ correct"],
        speaker_notes="Note _x0008_ here",
        layout=TemplateType.theory_slide,
    )
    assert "_x000D_" not in slide.bullets[0]
    assert "_x0008_" not in slide.speaker_notes
    assert "₹25" in slide.title


# ─────────────────────────────────────────────────────────────────────────────
# 3. Table detection in ExtractedPage
# ─────────────────────────────────────────────────────────────────────────────

def test_extracted_page_table_fields():
    page = ExtractedPage(
        page_number=1,
        content_type=ContentType.table,
        main_text="Year | 15% | 14%\n1 | 0.870 | 0.877",
        has_table=True,
        table_description="PV factors: 3 cols, 2 rows",
        should_skip=False,
    )
    assert page.has_table is True
    assert page.content_type == ContentType.table
    assert "PV factors" in page.table_description

def test_extracted_page_table_defaults_false():
    page = ExtractedPage(
        page_number=1,
        content_type=ContentType.text_heavy,
        main_text="Just text",
        should_skip=False,
    )
    assert page.has_table is False
    assert page.table_description is None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Solution-slide detection
# ─────────────────────────────────────────────────────────────────────────────

def test_solution_slide_detected():
    slide = SlideContent(
        slide_number=1,
        title="Solution: Cost of Project M",
        bullets=["-> Step 1"],
        speaker_notes="",
        layout=TemplateType.theory_slide,
    )
    assert _is_solution_slide(slide) is True

def test_solution_slide_with_dash():
    slide = SlideContent(
        slide_number=1,
        title="Solution — Dividend Payout",
        bullets=[],
        speaker_notes="",
        layout=TemplateType.theory_slide,
    )
    assert _is_solution_slide(slide) is True

def test_non_solution_slide():
    slide = SlideContent(
        slide_number=1,
        title="Equity Valuation Example",
        bullets=[],
        speaker_notes="",
        layout=TemplateType.theory_slide,
    )
    assert _is_solution_slide(slide) is False


# ─────────────────────────────────────────────────────────────────────────────
# 5. End-to-end PPTX generation with table + solution slides
# ─────────────────────────────────────────────────────────────────────────────

def test_pptx_generation_with_table_and_solution():
    """Build a real .pptx with table_slide, solution theory_slide, and
    verify the file is created and is a valid .pptx."""
    from config import TEMPLATE_PPTX
    if not os.path.exists(TEMPLATE_PPTX):
        print(f"  SKIP: template not found at {TEMPLATE_PPTX}")
        return

    ctx = PDFContext(
        subject="Mathematics",
        batch="Test",
        purpose="Lecture Notes",
        class_level="UG / College",
        language="English",
    )

    slides = [
        SlideContent(
            slide_number=1,
            title="Financial Analysis",
            bullets=[],
            speaker_notes="",
            layout=TemplateType.title_slide,
        ),
        SlideContent(
            slide_number=2,
            title="Present Value Factors",
            bullets=[],
            speaker_notes="Discount factors for Project M",
            layout=TemplateType.table_slide,
            table_data=TableBlock(
                headers=["Year", "15%", "14%", "13%", "12%"],
                rows=[
                    ["1", "0.870", "0.877", "0.885", "0.893"],
                    ["2", "0.756", "0.769", "0.783", "0.797"],
                    ["3", "0.658", "0.675", "0.693", "0.712"],
                    ["4", "0.572", "0.592", "0.613", "0.636"],
                    ["PVAF", "2.855", "2.914", "2.974", "3.037"],
                ],
                caption="Discount factors for n = 1..4 at various rates",
            ),
        ),
        SlideContent(
            slide_number=3,
            title="Solution: Cost of Project M",
            bullets=[
                "-> Formula: Cost = Annual Outflow × PVAF",
                "-> Given: ₹25 Crore/year, PVAF (15%, 4yr) = 2.855",
                "-> Calculation: 25 × 2.855 = ₹71.375 Crore",
                "-> Answer: (B) ₹71.375 Crore",
            ],
            speaker_notes="Answer: (B) ₹71.375 Crore",
            layout=TemplateType.theory_slide,
        ),
        SlideContent(
            slide_number=4,
            title="Theory + Table Combo",
            bullets=[
                "-> The Gordon Growth Model values equity based on dividends",
                "-> P₀ = E(1−b) / (Ke − br)",
            ],
            speaker_notes="",
            layout=TemplateType.theory_table_slide,
            table_data=TableBlock(
                headers=["Variable", "Value"],
                rows=[
                    ["EPS (E)", "₹10"],
                    ["Ke", "8%"],
                    ["r", "12%"],
                    ["P₀", "₹159.09"],
                ],
            ),
        ),
        SlideContent(
            slide_number=5,
            title="Summary",
            bullets=[
                "Cost of Project M = ₹71.375 Crore",
                "PV of Cash Inflows = ₹75.943 Crore",
                "Profitability Index = 1.064 (viable)",
                "Dividend Payout Ratio = 70%",
            ],
            speaker_notes="",
            layout=TemplateType.summary,
        ),
        SlideContent(
            slide_number=6,
            title="Thank You",
            bullets=[],
            speaker_notes="",
            layout=TemplateType.thank_you_slide,
        ),
    ]

    out_file = "_sanitization_smoketest.pptx"
    output_path = generate_pptx(slides, ctx, out_file)
    assert os.path.exists(output_path), f"PPTX not created: {output_path}"
    size = os.path.getsize(output_path)
    assert size > 10_000, f"PPTX too small ({size} bytes) — likely broken"
    print(f"\n  PPTX smoke test PASSED — {output_path} ({size:,} bytes)")
    print(f"  Contains: table_slide, solution theory_slide (green), theory_table_slide, summary")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_all():
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    passed = 0
    failed = 0
    for fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✓ {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {fn.__name__}: {e}")
    print(f"\n{'='*50}")
    print(f"  {passed} passed, {failed} failed out of {len(tests)} tests")
    print(f"{'='*50}")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
