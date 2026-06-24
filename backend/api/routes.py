import os
import re
from urllib.parse import parse_qs, urlparse

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pipeline.pptx_to_pdf import (
    convert_pptx_to_pdf,
    is_available as libreoffice_available,
    LibreOfficeNotInstalled,
)
from config import OUTPUT_DIR, STORAGE_BACKEND, TEMPLATE_PPTX


router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────────
# Template discovery helper
# ─────────────────────────────────────────────────────────────────────────────

_REFS_DIR = os.path.dirname(TEMPLATE_PPTX)

# Human-readable display names for the bundled templates.
_TEMPLATE_DISPLAY_NAMES = {
    "Common Template.pptx":        "Common",
    "CLAT_Common_Template_1.pptx": "CLAT Common",
    "Acchitecture Format.pptx":    "Architecture",
}


def _list_templates() -> list[dict]:
    """Scan the reference_ppts directory and return template metadata."""
    templates = []
    try:
        for fname in sorted(os.listdir(_REFS_DIR)):
            if not fname.lower().endswith(".pptx"):
                continue
            if fname.endswith(".bak"):
                continue
            tid = fname.replace(" ", "_").replace(".pptx", "").lower()
            display = _TEMPLATE_DISPLAY_NAMES.get(fname, fname.replace(".pptx", ""))
            templates.append({"id": tid, "name": display, "filename": fname})
    except Exception:
        pass
    return templates

MAX_DRIVE_PDF_BYTES = 50 * 1024 * 1024
DRIVE_DOWNLOAD_TIMEOUT = 60


def _extract_drive_file_id(pdf_url: str) -> str:
    parsed = urlparse(pdf_url.strip())
    hostname = (parsed.hostname or "").lower()

    if hostname not in {"drive.google.com", "docs.google.com"}:
        raise HTTPException(
            status_code=400,
            detail="Only public Google Drive PDF links are supported"
        )

    match = re.search(r"/(?:file/d|document/d)/([^/]+)", parsed.path)
    if match:
        return match.group(1)

    file_id = parse_qs(parsed.query).get("id", [None])[0]
    if file_id:
        return file_id

    raise HTTPException(
        status_code=400,
        detail="Could not find a Google Drive file ID in the link"
    )


def _download_public_drive_pdf(pdf_url: str, pdf_path: str) -> None:
    file_id = _extract_drive_file_id(pdf_url)
    download_url = "https://drive.google.com/uc"
    session = requests.Session()

    try:
        response = session.get(
            download_url,
            params={"export": "download", "id": file_id},
            stream=True,
            timeout=DRIVE_DOWNLOAD_TIMEOUT,
        )
        response.raise_for_status()

        confirm_token = next(
            (
                value
                for key, value in response.cookies.items()
                if key.startswith("download_warning")
            ),
            None,
        )

        if confirm_token:
            response.close()
            response = session.get(
                download_url,
                params={"export": "download", "id": file_id, "confirm": confirm_token},
                stream=True,
                timeout=DRIVE_DOWNLOAD_TIMEOUT,
            )
            response.raise_for_status()

        total = 0
        first_chunk = b""
        with open(pdf_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                if not first_chunk:
                    first_chunk = chunk
                total += len(chunk)
                if total > MAX_DRIVE_PDF_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="PDF is too large. Maximum allowed size is 50MB"
                    )
                f.write(chunk)

        if total == 0 or not first_chunk.lstrip().startswith(b"%PDF"):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Drive link did not return a PDF. Make sure the file is a "
                    "public PDF shared as 'Anyone with the link can view'."
                )
            )
    except HTTPException:
        raise
    except requests.RequestException as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not download PDF from Google Drive: {e}"
        )


@router.get("/download/{filename}")
async def download_ppt(filename: str):
    """
    Download endpoint — frontend calls this to get the .pptx file.
    """

    file_path = os.path.join(OUTPUT_DIR, filename)

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail="File not found"
        )

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )


@router.get("/download-pdf/{filename}")
async def download_pdf(filename: str):
    """
    Download endpoint — converts a generated .pptx to PDF and returns it as an
    attachment. This requires LibreOffice on the backend.
    """
    pptx_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(pptx_path):
        raise HTTPException(status_code=404, detail="PPT file not found")

    try:
        pdf_path = convert_pptx_to_pdf(pptx_path)
    except LibreOfficeNotInstalled as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF export failed: {e}")

    pdf_filename = os.path.splitext(os.path.basename(filename))[0] + ".pdf"
    return FileResponse(
        path=pdf_path,
        filename=pdf_filename,
        media_type="application/pdf",
    )


@router.get("/preview/{filename}")
async def preview_ppt(filename: str):
    """
    Render a generated .pptx as a PDF stream so the frontend can embed it
    in an <iframe> for slide preview. The PDF is cached next to the .pptx
    and only re-generated when the .pptx changes.
    """
    pptx_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(pptx_path):
        raise HTTPException(status_code=404, detail="PPT file not found")

    try:
        pdf_path = convert_pptx_to_pdf(pptx_path)
    except LibreOfficeNotInstalled as e:
        # 501 Not Implemented — frontend can show a friendly message
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview failed: {e}")

    pdf_filename = os.path.basename(pdf_path)
    return FileResponse(
        path=pdf_path,
        filename=pdf_filename,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{pdf_filename}"'},
    )


@router.get("/health")
async def health_check():
    """Simple health check — frontend can ping this to check if server is running."""
    return {
        "status": "ok",
        "storage_backend": STORAGE_BACKEND,
        "preview_available": libreoffice_available(),
    }


@router.get("/templates")
async def list_templates():
    """
    Return the available reference PPT templates the user can choose from.
    Each item has: id, name, filename.
    """
    return {"templates": _list_templates()}
