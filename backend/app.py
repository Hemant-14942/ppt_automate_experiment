import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from api.session_routes import router as session_router
from config import FRONTEND_ORIGINS, UPLOAD_DIR, OUTPUT_DIR
from pipeline.pptx_to_pdf import prewarm as prewarm_libreoffice, is_available as libreoffice_available
import os


# create the FastAPI app
app = FastAPI(
    title="PDF to PPT Generator",
    description="Convert teaching PDFs into presentation slides using AI",
    version="1.0.0"
)


# ── CORS — allow frontend to talk to backend ────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── mount routes under /api prefix ──────────────────
app.include_router(router, prefix="/api")
app.include_router(session_router, prefix="/api")


# ── create required directories on startup ──────────
@app.on_event("startup")
async def startup():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("\n  PDF to PPT server started")
    print(f"  Uploads → {UPLOAD_DIR}/")
    print(f"  Outputs → {OUTPUT_DIR}/")

    # Pre-warm LibreOffice in the background so the first preview / visual
    # critique conversion isn't a cold start. Runs off the event loop so
    # the server is immediately available; warm-up finishes in ~10-15 s.
    if libreoffice_available():
        async def _warm():
            ok = await asyncio.to_thread(prewarm_libreoffice)
            print(f"  LibreOffice pre-warm {'done' if ok else 'failed'}\n")
        asyncio.create_task(_warm())
    else:
        print("  LibreOffice not available — preview disabled\n")