"""
Shared text sanitization for agent/LLM output.

The writing/extraction models occasionally emit math and currency symbols in
BROKEN forms instead of the real glyph:

  • bare Unicode code-point hex:   "20b9" → ₹   "20d7" → ×   (seen on solution
    slides as "(c) 20b9 71.375 Crore" / "Outflow 20d7 PVAF")
  • Word-style XML escapes:        "_x20B9_" → ₹   "_x00D7_" → ×   (these used
    to be STRIPPED by the control-char regex, silently deleting the ₹ / ×)

This module restores the known printable symbols, then removes only genuine
control-character noise. Keeping the whitelist small means we never corrupt
legitimate content (e.g. the year "2024" is NOT in the map).
"""

import re
import unicodedata

# Known printable math / currency code points the models tend to mangle.
# Note: 0x20D7 (combining arrow) is the model's frequent mis-encoding of "×".
_SYMBOL_CODEPOINTS = {
    0x20B9: "₹", 0x20AC: "€", 0x00A3: "£", 0x0024: "$", 0x00A5: "¥",
    0x00D7: "×", 0x20D7: "×", 0x00F7: "÷", 0x2217: "*", 0x2212: "-",
    0x221A: "√", 0x2192: "→", 0x21D2: "⇒", 0x2264: "≤", 0x2265: "≥",
    0x2260: "≠", 0x2248: "≈", 0x00B1: "±", 0x00B0: "°", 0x03C0: "π",
    0x0394: "Δ", 0x03B1: "α", 0x03B2: "β", 0x03B8: "θ", 0x03BB: "λ",
    0x03BC: "µ", 0x2211: "Σ", 0x222B: "∫", 0x221E: "∞",
}

# Word-style escape: _x20B9_  (4 hex digits between _x ... _)
_WORD_ESCAPE_RE = re.compile(r"_x([0-9A-Fa-f]{4})_")

# Bare hex code-point token (only the symbols we KNOW the model mangles, so we
# never touch normal numbers/words). Bounded so "120b9x" won't match.
_BARE_HEX_RE = re.compile(
    r"(?<![0-9A-Za-z])("
    + "|".join(f"{cp:04x}" for cp in _SYMBOL_CODEPOINTS)
    + r")(?![0-9A-Za-z])",
    re.IGNORECASE,
)

# Raw C0 control chars (keep \t \n \r).
_RAW_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _restore_word_escape(m: re.Match) -> str:
    cp = int(m.group(1), 16)
    if cp in _SYMBOL_CODEPOINTS:
        return _SYMBOL_CODEPOINTS[cp]
    if cp < 0x20:                       # genuine control char → drop
        return ""
    try:
        ch = chr(cp)
        if unicodedata.category(ch).startswith("C"):  # other control/format
            return ""
        return ch
    except (ValueError, OverflowError):
        return ""


def _restore_bare_hex(m: re.Match) -> str:
    return _SYMBOL_CODEPOINTS[int(m.group(1), 16)]


def restore_symbols(text: str) -> str:
    """Convert mangled symbol encodings back to their real glyphs."""
    text = _WORD_ESCAPE_RE.sub(_restore_word_escape, text)
    text = _BARE_HEX_RE.sub(_restore_bare_hex, text)
    return text


def strip_control_chars(text: str) -> str:
    """Remove raw C0 control chars (after symbol restoration)."""
    return _RAW_CONTROL_RE.sub("", text)
