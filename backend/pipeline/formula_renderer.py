"""
Formula rendering pipeline: LaTeX mathtext → PNG image.

Uses matplotlib's built-in mathtext engine — a clean subset of LaTeX math mode
that runs without any external LaTeX / dvipng installation.

Delimiter convention (produced by the AI writer):
  $$latex$$   → standalone block formula  (full-width, large render)
  $latex$     → inline formula            (smaller, embedded in text line)
  plain text  → no rendering; passed through unchanged

Chemistry subscripts (H2O, C6H6, H2SO4) are converted directly to Unicode by
`to_unicode_math()` — no image render needed for simple molecular formulas.
Complex chemistry structures should go through `$$...$$` delimiters using
matplotlib-supported math notation.

Public API used by ppt_generator:
  split_bullet_segments(text)     → list[TextSegment | FormulaSegment]
  render_formula_png(latex, ...)  → bytes | None
  to_unicode_math(text)           → str     (Unicode subscript/superscript conversion)
  is_pure_formula_bullet(text)    → bool
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


# ── Segment dataclasses ───────────────────────────────────────────────────────

@dataclass
class TextSegment:
    """A plain-text part of a bullet."""
    text: str


@dataclass
class FormulaSegment:
    """A LaTeX formula segment extracted from a bullet."""
    latex: str
    block: bool          # True → $$...$$ (takes full bullet row), False → $...$
    png: bytes | None = field(default=None, repr=False)


BulletSegment = TextSegment | FormulaSegment


# ── Delimiter regexes ─────────────────────────────────────────────────────────

# Match $$...$$ first (greedy for single-line, minimal cross-line)
_BLOCK_RE  = re.compile(r'\$\$(.+?)\$\$', re.DOTALL)
# Match $...$ (but NOT $$...$$) — lookbehind/ahead to avoid double-dollar match
_INLINE_RE = re.compile(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)')


# ── Segmentation ─────────────────────────────────────────────────────────────

def split_bullet_segments(text: str) -> list[BulletSegment]:
    """
    Split a bullet string into alternating Text / Formula segments.

    Examples
    --------
    "Energy: $$E = mc^2$$"
        → [TextSegment("Energy: "), FormulaSegment("E = mc^2", block=True)]

    "Speed of light $c = 3 \\times 10^8$ m/s"
        → [TextSegment("Speed of light "), FormulaSegment("c = 3...", block=False),
           TextSegment(" m/s")]

    "No formula here"
        → [TextSegment("No formula here")]
    """
    if '$$' not in text and '$' not in text:
        return [TextSegment(text)]

    segments: list[BulletSegment] = []

    # First look for block ($$...$$) formulas
    if '$$' in text:
        pos = 0
        for m in _BLOCK_RE.finditer(text):
            before = text[pos:m.start()]
            if before.strip():
                segments.append(TextSegment(before))
            segments.append(FormulaSegment(latex=m.group(1).strip(), block=True))
            pos = m.end()
        tail = text[pos:]
        if tail.strip():
            segments.append(TextSegment(tail))

        if segments:
            return segments

    # Fallback: look for inline ($...$) formulas
    pos = 0
    for m in _INLINE_RE.finditer(text):
        before = text[pos:m.start()]
        if before.strip():
            segments.append(TextSegment(before))
        segments.append(FormulaSegment(latex=m.group(1).strip(), block=False))
        pos = m.end()
    tail = text[pos:]
    if tail.strip():
        segments.append(TextSegment(tail))

    return segments if segments else [TextSegment(text)]


def is_pure_formula_bullet(text: str) -> bool:
    """Return True when the entire bullet is a single $$...$$ formula block."""
    stripped = text.strip()
    return bool(_BLOCK_RE.fullmatch(stripped))


# ── Formula renderer ──────────────────────────────────────────────────────────

def render_formula_png(
    latex: str,
    *,
    fontsize: int = 28,
    dpi: int = 200,
    text_color: str = "white",
    bg_transparent: bool = True,
    padding: float = 0.10,
) -> bytes | None:
    """
    Render a LaTeX math-mode expression to a PNG image (bytes).

    Uses matplotlib's mathtext engine — no external LaTeX binary required.

    Parameters
    ----------
    latex           : LaTeX string WITHOUT outer $ delimiters
                      e.g. r"\\frac{1}{2\\pi\\sqrt{LC}}"
    fontsize        : base font size in points (larger → bigger image)
    dpi             : render resolution; 150-250 is a good range
    text_color      : formula text colour (use "white" for dark slide backgrounds)
    bg_transparent  : True → transparent PNG (recommended for dark slides)
    padding         : extra whitespace around formula (in inches)

    Returns
    -------
    bytes  : PNG image data, or
    None   : if rendering fails (caller should fall back to plain text)
    """
    try:
        import matplotlib
        matplotlib.use("Agg")          # non-interactive; no display required
        import matplotlib.pyplot as plt
        from matplotlib import rcParams

        # Use Computer Modern — the classic LaTeX look
        rcParams.update({
            "mathtext.fontset": "cm",
            "mathtext.rm":      "serif",
        })

        math_expr = f"${latex}$"      # matplotlib needs outer $ $

        # Tiny initial canvas — we resize once we know the text extent
        fig = plt.figure(figsize=(2, 1))
        ax  = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()

        t = ax.text(
            0.5, 0.5, math_expr,
            ha="center", va="center",
            fontsize=fontsize,
            color=text_color,
            transform=ax.transAxes,
        )

        # First draw to measure text extent in pixels
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        bb = t.get_window_extent(renderer=renderer)

        # Resize figure to tightly wrap the text
        width_in  = max(bb.width  / dpi + padding * 2, 1.5)
        height_in = max(bb.height / dpi + padding * 2, 0.6)
        fig.set_size_inches(width_in, height_in)
        fig.canvas.draw()

        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            dpi=dpi,
            transparent=bg_transparent,
            bbox_inches="tight",
            pad_inches=padding,
        )
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except ImportError:
        log.warning(
            "matplotlib not available — formula rendering disabled. "
            "Run: pip install matplotlib"
        )
        return None
    except Exception as exc:
        log.warning("Formula render failed for %r: %s", latex[:60], exc)
        return None


# ── Unicode math / chemistry conversion ──────────────────────────────────────

# Superscript translation: digits + common math chars
_TO_SUP = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")

# Subscript translation: digits only (used for chemistry subscripts)
_TO_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")

# x^2, a^{n-1} → superscript
_POW_BRACED_RE = re.compile(r'\^\{([^}]{1,6})\}')    # ^{...}
_POW_SIMPLE_RE = re.compile(r'\^([0-9+\-nN]{1,4})')  # ^2, ^-1, ^n

# Chemical formula subscripts: Element symbol(s) followed by digit(s)
# e.g.  H2O → H₂O,  C6H12O6 → C₆H₁₂O₆,  H2SO4 → H₂SO₄,  CO2 → CO₂
# Match ANY uppercase (+ optional lowercase) + digits sequence inside a formula.
_ELEM_RE = re.compile(r'([A-Z][a-z]?)(\d+)')

# Arrow / equilibrium arrows for chemical reactions.
# IMPORTANT: multi-char patterns (-->, <->, <=>) MUST come before single-char (->)
# so that <-> is not partially consumed by the -> pattern first.
_CHEM_ARROWS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\s*<-->\s*'), ' ⇌ '),
    (re.compile(r'\s*<=>\s*'),  ' ⇌ '),
    (re.compile(r'\s*<->\s*'),  ' ⇌ '),
    (re.compile(r'\s*-->\s*'),  ' ⟶ '),
    (re.compile(r'\s*->\s*'),   ' → '),
]

# Degree/temperature: 30°C, 25°F, 180°
_DEG_RE = re.compile(r'(\d)\s*deg\b', re.IGNORECASE)
# Remove \text{} LaTeX wrapper (common from AI)
_LATEX_TEXT_RE = re.compile(r'\\text\{([^}]+)\}')
# Remove \mathrm{}, \mathbf{} wrappers
_LATEX_WRAP_RE = re.compile(r'\\math(?:rm|bf|it|sf|tt)\{([^}]+)\}')


def to_unicode_math(text: str) -> str:
    """
    Convert common LaTeX / ASCII math notation to Unicode equivalents.

    Transformations applied (in order):
    1. Strip `\\text{}`, `\\mathrm{}` wrappers → plain text inside
    2. Superscripts: `x^2` → `x²`, `a^{n-1}` → `aⁿ⁻¹`
    3. Chemical element subscripts: `C6H12O6` → `C₆H₁₂O₆`
    4. Chemistry arrows: `->` → `→`, `<->` → `⇌`
    5. Degree shorthand: `30 deg` → `30°`

    Skips segments inside `$...$` or `$$...$$` delimiters — those go to the
    formula renderer instead of Unicode conversion.

    Returns the converted string (may be the same object if no changes made).
    """
    # Skip if content has formula delimiters — renderer handles those
    if '$' in text:
        return text

    # 1. Strip LaTeX text wrappers
    text = _LATEX_TEXT_RE.sub(r'\1', text)
    text = _LATEX_WRAP_RE.sub(r'\1', text)

    # 2. Superscripts (braced first to avoid double-match)
    text = _POW_BRACED_RE.sub(lambda m: m.group(1).translate(_TO_SUP), text)
    text = _POW_SIMPLE_RE.sub(lambda m: m.group(1).translate(_TO_SUP), text)

    # 3. Chemical subscripts — only inside chemistry-looking segments
    #    (Capital letter + optional lowercase + digits)
    text = _ELEM_RE.sub(lambda m: m.group(1) + m.group(2).translate(_TO_SUB), text)

    # 4. Chemistry arrows
    for pat, repl in _CHEM_ARROWS:
        text = pat.sub(repl, text)

    # 5. Degree shorthands
    text = _DEG_RE.sub(r'\1°', text)

    return text
