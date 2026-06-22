"""
Image Studio — Gemini-powered image generation and editing.

Two capabilities:
  1. generate_image_from_prompt  — creates a brand-new image via Imagen 4 Fast
                                   (imagen-4.0-fast-generate-001, standard key).
  2. edit_image_with_gemini      — edits an existing PNG via gemini-3.1-flash-image,
                                   with a local PIL fallback if the model is unavailable.

Both return raw PNG bytes suitable for base64-encoding into the session gallery.

The edit function has a graceful PIL fallback: if the Gemini experimental model
is unavailable, basic style transforms (darker, lighter, grayscale, contrast,
sharpen, invert, blur) are applied locally so the feature always works.
"""
from __future__ import annotations

import asyncio
import base64
import io

from agents.gemini_client import client


# ── Image generation (Imagen 4 Fast) ─────────────────────────────────────────

async def generate_image_from_prompt(prompt: str) -> bytes:
    """Generate a new educational image from a text prompt using Imagen 4 Fast.

    Uses imagen-4.0-fast-generate-001 via generate_images — fast, high quality,
    works on a standard Gemini API key.

    Returns raw PNG bytes.  Raises RuntimeError on failure.
    """
    from google.genai import types

    response = await asyncio.to_thread(
        client.models.generate_images,
        model="imagen-4.0-fast-generate-001",
        prompt=prompt,
        config=types.GenerateImagesConfig(number_of_images=1),
    )

    generated = response.generated_images
    if not generated:
        raise RuntimeError("Imagen 4 returned no images — try a more descriptive prompt")

    return generated[0].image.image_bytes


# ── Image editing (Gemini 2.0 Flash, with PIL fallback) ───────────────────────

async def edit_image_with_gemini(png_bytes: bytes, instruction: str) -> bytes:
    """Edit an existing PNG image using a natural-language instruction.

    Tries Gemini 2.0 Flash preview image-generation first.  If that model is
    unavailable, falls back to PIL-based basic style transforms so the feature
    degrades gracefully.

    Returns raw PNG bytes.
    """
    try:
        return await _gemini_edit(png_bytes, instruction)
    except Exception as gemini_err:
        print(f"  [image_studio] Gemini edit unavailable ({gemini_err}), using PIL fallback")
        return await asyncio.to_thread(_pil_style_fallback, png_bytes, instruction)


async def _gemini_edit(png_bytes: bytes, instruction: str) -> bytes:
    from google.genai import types

    content = types.Content(
        role="user",
        parts=[
            types.Part(
                inline_data=types.Blob(mime_type="image/png", data=png_bytes)
            ),
            types.Part(
                text=(
                    f"Edit this image: {instruction}. "
                    "Keep it clear and suitable for educational slides."
                )
            ),
        ],
    )

    response = await asyncio.to_thread(
        client.models.generate_content,
        model="gemini-3.1-flash-image",
        contents=content,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"]
        ),
    )

    for part in response.candidates[0].content.parts:
        idata = getattr(part, "inline_data", None)
        if idata:
            # inline_data.data may be raw bytes (newer SDK) or base64 string
            raw = idata.data if isinstance(idata.data, bytes) else base64.b64decode(idata.data)
            # Normalise to PNG so gallery always stores PNG
            return _ensure_png(raw)

    raise RuntimeError("Gemini returned no image in response")


def _ensure_png(image_bytes: bytes) -> bytes:
    """Convert image bytes to PNG format if they aren't already."""
    if image_bytes[:4] == b"\x89PNG":
        return image_bytes
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _pil_style_fallback(png_bytes: bytes, instruction: str) -> bytes:
    """Apply basic PIL-based style transforms when Gemini is unavailable."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    instr = instruction.lower()

    if any(w in instr for w in ("darker", "dark", "dim", "shadow")):
        img = ImageEnhance.Brightness(img).enhance(0.55)
    elif any(w in instr for w in ("lighter", "bright", "light", "glow")):
        img = ImageEnhance.Brightness(img).enhance(1.55)
    elif any(w in instr for w in ("grayscale", "greyscale", "black and white", "b&w", "monochrome")):
        img = ImageOps.grayscale(img).convert("RGB")
    elif any(w in instr for w in ("contrast", "vivid", "punch", "bold")):
        img = ImageEnhance.Contrast(img).enhance(1.9)
        img = ImageEnhance.Color(img).enhance(1.4)
    elif any(w in instr for w in ("sharpen", "sharp", "crisp")):
        img = img.filter(ImageFilter.SHARPEN).filter(ImageFilter.SHARPEN)
    elif any(w in instr for w in ("blur", "soft", "smooth", "defocus")):
        img = img.filter(ImageFilter.GaussianBlur(radius=2.5))
    elif any(w in instr for w in ("invert", "negative", "negate")):
        img = ImageOps.invert(img)
    elif any(w in instr for w in ("sepia", "warm", "vintage", "retro")):
        img = _sepia(img)
    else:
        # No recognised keyword — boost contrast slightly as a generic "enhance"
        img = ImageEnhance.Contrast(img).enhance(1.3)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _sepia(img: "Image.Image") -> "Image.Image":
    from PIL import Image as _Image
    gray = img.convert("L")
    result = _Image.new("RGB", img.size)
    pixels = result.load()
    g = gray.load()
    for y in range(img.height):
        for x in range(img.width):
            v = g[x, y]  # type: ignore[index]
            r = min(255, int(v * 1.08))
            gr = min(255, int(v * 0.85))
            b = min(255, int(v * 0.66))
            pixels[x, y] = (r, gr, b)  # type: ignore[index]
    return result
