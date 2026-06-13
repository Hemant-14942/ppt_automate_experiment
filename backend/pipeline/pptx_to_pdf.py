"""
PPTX → PDF converter using LibreOffice in headless mode.

Why LibreOffice?
  python-pptx writes .pptx perfectly but cannot render it. To preview in the
  browser we convert to PDF (which every browser can render natively).
  LibreOffice gives us pixel-perfect conversion including custom fonts,
  decorative graphics, and the large 40 × 22.5 in canvas from our template.

The converter:
  - Finds the LibreOffice `soffice` binary in standard locations
  - Caches the resulting PDF — only re-converts when the .pptx is newer
  - Returns the PDF path, or raises a helpful error if LibreOffice is missing
"""

import os
import shutil
import subprocess
from pathlib import Path


# Locations LibreOffice typically lives on macOS / Linux
_SOFFICE_CANDIDATES = [
    "soffice",
    "libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
    "/opt/homebrew/bin/soffice",
    "/usr/local/bin/soffice",
]


def _find_soffice() -> str | None:
    """Return the first valid LibreOffice executable path, or None."""
    for candidate in _SOFFICE_CANDIDATES:
        # absolute path — check file existence
        if "/" in candidate and os.path.exists(candidate):
            return candidate
        # bare name — check PATH
        found = shutil.which(candidate)
        if found:
            return found
    return None


def is_available() -> bool:
    """True if LibreOffice can be invoked for conversion."""
    return _find_soffice() is not None


class LibreOfficeNotInstalled(RuntimeError):
    """Raised when soffice is missing — message tells the user how to install."""
    def __init__(self):
        super().__init__(
            "LibreOffice not found. Install it to enable PPT previews:\n"
            "  macOS  : brew install --cask libreoffice\n"
            "  Ubuntu : sudo apt install -y libreoffice\n"
            "  Docker : RUN apt-get install -y libreoffice"
        )


def prewarm(timeout_s: int = 60) -> bool:
    """
    Pre-warm LibreOffice by doing one throwaway conversion at server
    startup. This pages LibreOffice's binaries, fonts and shared libs
    into the OS file cache so the FIRST user-triggered conversion is
    no longer a cold start (~10-15 s on macOS → ~3-5 s).

    Safe to call multiple times — silently no-ops if LibreOffice isn't
    installed. Runs synchronously; call it from an async startup hook
    with asyncio.to_thread so the server can still accept requests
    while it warms.
    """
    import tempfile

    soffice = _find_soffice()
    if soffice is None:
        return False

    try:
        from pptx import Presentation as _P
    except ImportError:
        return False

    try:
        with tempfile.TemporaryDirectory() as tmp:
            dummy_pptx = Path(tmp) / "_warmup.pptx"
            prs = _P()
            prs.slides.add_slide(prs.slide_layouts[5])
            prs.save(str(dummy_pptx))

            cmd = [
                soffice,
                "--headless",
                "--norestore",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                f"-env:UserInstallation=file://{tmp}",
                "--convert-to", "pdf",
                "--outdir", tmp,
                str(dummy_pptx),
            ]
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        return True
    except Exception:
        return False


def convert_pptx_to_pdf(pptx_path: str, out_dir: str | None = None) -> str:
    """
    Convert a .pptx to .pdf using LibreOffice.

    Caching: if a .pdf exists next to the .pptx and is newer than the .pptx,
    the cached file is returned without re-running the converter.
    """
    pptx = Path(pptx_path)
    if not pptx.exists():
        raise FileNotFoundError(f"PPTX not found: {pptx_path}")

    out_dir_p = Path(out_dir) if out_dir else pptx.parent
    out_dir_p.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir_p / (pptx.stem + ".pdf")

    # ── cache check ──────────────────────────────────────────────────────────
    if pdf_path.exists() and pdf_path.stat().st_mtime >= pptx.stat().st_mtime:
        return str(pdf_path)

    soffice = _find_soffice()
    if soffice is None:
        raise LibreOfficeNotInstalled()

    # ── convert ──────────────────────────────────────────────────────────────
    # LibreOffice is single-instance; use a per-conversion user profile to
    # allow concurrent calls (otherwise it errors with "already running").
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_profile:
        cmd = [
            soffice,
            "--headless",
            "--norestore",
            "--nologo",
            "--nodefault",
            "--nofirststartwizard",
            f"-env:UserInstallation=file://{tmp_profile}",
            "--convert-to", "pdf",
            "--outdir", str(out_dir_p),
            str(pptx),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("LibreOffice conversion timed out (>120s)")

        if result.returncode != 0 or not pdf_path.exists():
            raise RuntimeError(
                f"LibreOffice failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

    return str(pdf_path)
