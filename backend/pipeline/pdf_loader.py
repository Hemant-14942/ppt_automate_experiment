import fitz
import base64
import sys
from config import PDF_DPI

# Suppress MuPDF warnings (like "No common ancestor in structure tree") 
# to keep the terminal clean. These are non-fatal and don't affect rendering.
fitz.TOOLS.mupdf_display_errors(False)


def pdf_to_base64_images(pdf_path: str) -> list[dict]:
    """
    Convert every page of a PDF into a base64 encoded image.
    Returns a list of dicts — one per page.
    """

    images = []
    doc = fitz.open(pdf_path)

    for page_num in range(len(doc)):
        page = doc[page_num]

        # convert page to pixmap at configured DPI
        mat = fitz.Matrix(PDF_DPI / 72, PDF_DPI / 72)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)

        # get raw bytes and convert to base64
        img_bytes = pix.tobytes("png")
        b64_string = base64.b64encode(img_bytes).decode("utf-8")

        images.append({
            "page_number": page_num + 1,
            "base64":      b64_string,
            "mime_type":   "image/png"
        })

        print(f"    Loaded page {page_num + 1} of {len(doc)}")

    doc.close()

    print(f"  PDF loaded — {len(images)} pages total")
    return images


def get_pdf_page_count(pdf_path: str) -> int:
    """Quick helper — returns total page count without loading images."""
    doc = fitz.open(pdf_path)
    count = len(doc)
    doc.close()
    return count


def pdf_pages_to_png_bytes(
    pdf_path: str,
    dpi: int = 110,
    page_indices: list[int] | None = None,
) -> list[bytes]:
    """
    Render PDF pages to PNG bytes.
    Used by the Visual Critic agent — it sends each PNG to Gemini Vision.

    page_indices: optional 0-based page numbers to render. When omitted, every
    page is rendered. Partial rendering avoids PNG work on unchanged slides.
    DPI 110 keeps payload small (~150-300 KB per slide) while remaining legible.
    """
    images: list[bytes] = []
    doc = fitz.open(pdf_path)
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    indices = page_indices if page_indices is not None else range(len(doc))
    for i in indices:
        if i < 0 or i >= len(doc):
            continue
        pix = doc[i].get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        images.append(pix.tobytes("png"))
    doc.close()
    return images