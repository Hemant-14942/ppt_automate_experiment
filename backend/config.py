import os
from dotenv import load_dotenv

load_dotenv()

# API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
FRONTEND_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]

# Models
EXTRACTION_MODEL       = "gemini-2.5-flash"
EXTRACTION_RETRY_MODEL = "gemini-3.5-flash"   # escalated model for the single retry attempt
PLANNING_MODEL     = "gemini-3.5-flash"
WRITING_MODEL      = "gemini-2.5-flash"
CRITIC_MODEL       = "gemini-3.5-flash"    # legacy alias — prefer the 3 below

# Split critic models — lets each agent use the right tier independently:
#   PLAN_CRITIC_MODEL  : one-shot, high-reasoning (plan structure, style)
#   SLIDE_CRITIC_MODEL : per-slide faithfulness + visual checks
#   LAYOUT_MODEL       : per-slide layout classification (simple task)
PLAN_CRITIC_MODEL  = "gemini-3.5-flash"
SLIDE_CRITIC_MODEL = "gemini-3.5-flash"
LAYOUT_MODEL       = "gemini-2.5-flash"
ORCHESTRATOR_MODEL = "gemini-2.5-flash"
PROFILER_MODEL     = "gemini-2.5-flash"  

# PDF
PDF_DPI = 150

# PPT
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").lower()

UPLOAD_DIR = os.getenv(
    "UPLOAD_DIR",
    "/tmp/pdf-to-ppt/uploads" if STORAGE_BACKEND == "s3" else "uploads"
)

OUTPUT_DIR = os.getenv(
    "OUTPUT_DIR",
    "/tmp/pdf-to-ppt/outputs" if STORAGE_BACKEND == "s3" else "outputs"
)
# s3
# S3 storage config. Used only when STORAGE_BACKEND=s3.
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_PRESIGNED_URL_EXPIRE_SECONDS = int(
    os.getenv("S3_PRESIGNED_URL_EXPIRE_SECONDS", "3600")
)
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")


# Reference template — every slide is cloned from this file so the look matches.
# Kept inside backend/ so Railway can deploy the backend service by itself.
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PPTX = os.path.join(
    _BACKEND_DIR, "assets", "reference_ppts", "Common Template.pptx"
)

# Agent settings
# MAX_SLIDES is effectively NO limit — the deck size is purely content-driven.
# If the PDF has 50 annotated questions, we produce 50+ slides. No artificial cap.
MAX_SLIDES            = 500
MIN_SLIDES            = 3
MAX_BULLETS           = 5
MAX_BULLET_WORDS      = 12          # bullets longer than this get trimmed by QC
MAX_CONCURRENT_AGENTS = 15          # max parallel Gemini calls — stays within rate limits

# Extraction resilience
# A page extraction may fail on a TRANSIENT error (rate limit 429, 503, timeout).
# We retry at most this many times before giving up on that page. Kept at 1 so a
# blip is recovered without hammering the API.
MAX_EXTRACTION_RETRIES = 1
# Output-token budget for ONE page's JSON. Dense pages (long comprehension
# passages + MCQs) can otherwise truncate mid-JSON (finish_reason=MAX_TOKENS),
# which makes the parse return None and the page silently drop.
MAX_EXTRACTION_OUTPUT_TOKENS = 8192

# Faithfulness critic resilience. Large decks can send 100+ critic calls; if one
# call stalls, the whole gather() used to look stuck. Timeout fail-opens that
# slide and lets the pipeline continue.
FAITHFULNESS_TIMEOUT_SECONDS = int(os.getenv("FAITHFULNESS_TIMEOUT_SECONDS", "75"))
FAITHFULNESS_PROGRESS_EVERY = int(os.getenv("FAITHFULNESS_PROGRESS_EVERY", "10"))

# Visual critic — max CONTENT-REWRITE rounds after the initial full-deck pass
# (Phase 3: raised from 1 so the loop can actually converge on hard slides).
MAX_VISUAL_RETRIES = 2

# Visual critic — max PAGINATION rounds. When the critic confirms a free-body
# slide still overflows, we re-split it (more aggressively) instead of asking
# the writer to delete content. Each round bumps the overflow "pressure".
MAX_PAGINATION_ROUNDS = 2

# Skip visual critic entirely (saves many API calls)
# Set VISUAL_CRITIC_SKIP=true in .env to skip
VISUAL_CRITIC_SKIP = os.getenv("VISUAL_CRITIC_SKIP", "false").lower() == "true"

# Style memory
MEMORY_DIR = os.path.join(os.path.dirname(__file__), "memory")
STYLE_YAML = os.path.join(MEMORY_DIR, "style.yaml")

# Devanagari (Hindi) rendering — the brand fonts (Anton/Poppins) have NO
# Devanagari glyphs, so any Hindi text run is re-assigned to this font. The
# host running LibreOffice / PowerPoint must have a Devanagari font available;
# override via env if your deploy box ships a different one (e.g.
# "Lohit Devanagari", "Mangal", "Kohinoor Devanagari").
DEVANAGARI_FONT = os.getenv("DEVANAGARI_FONT", "Noto Sans Devanagari")