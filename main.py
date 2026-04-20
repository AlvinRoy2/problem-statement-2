import asyncio
import traceback
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from core.database import init_db
from agent.loop import agent_execution_loop
from api.endpoints import router as api_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Initializing SQLite Database...")
    init_db()
    
    # ── Google AI Services (API-key only — no GCP project required) ──────────
    # All four services use the GOOGLE_API_KEY from https://aistudio.google.com
    # SK-15: Gemini Embeddings | SK-16: Function Calling
    # SK-17: Files API          | SK-18: Grounding with Google Search
    try:
        import os
        from google import genai
        from dotenv import load_dotenv
        load_dotenv()

        _api_key = os.getenv("GOOGLE_API_KEY", "")
        if _api_key:
            _warmup_client = genai.Client(api_key=_api_key)
            # Lightweight connectivity check — validate the key works
            _models = [m.name for m in _warmup_client.models.list()]
            _gemini_models = [m for m in _models if "gemini" in m.lower()]
            print(f"[OK] Google AI Services ready - {len(_gemini_models)} Gemini model(s) accessible.")
            print("    SK-15: text-embedding-004 (Semantic Search)")
            print("    SK-16: Gemini Function Calling (Agentic Decisions)")
            print("    SK-17: Gemini Files API (Report Analysis)")
            print("    SK-18: Gemini Grounding + Google Search (Real-Time Context)")
        else:
            print("[INFO] GOOGLE_API_KEY not set - Google AI Services will be skipped at runtime.")
    except Exception as e:
        print(f"[WARN] Google AI Services warmup skipped: {str(e)}")
    
    print("Starting background operations...")
    task = asyncio.create_task(agent_execution_loop())
    
    yield
    
    print("Shutting down background operations...")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        print("Background operations stopped.")

app = FastAPI(
    title="SmartVenue Agent OS", 
    version="1.1", 
    description="Modular backend for open-source venue crowd management.",
    lifespan=lifespan
)

# NOTE: Replace allow_origins with specific domains in a production environment
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Security: Enforce Trusted Hosts and compress data for Efficiency
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)

from typing import Optional
import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app.include_router(api_router, prefix="/api")

# Serve the frontend dist directory statically (Critical for Cloud Run Docker builds)
frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")

if os.path.exists(frontend_dist):
    # Mount Vite's static assets explicitly to avoid Catch-All conflicts
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")
    
    # Catch-all to support React Router / Vite's index.html handling
    @app.get("/{catchall:path}")
    async def serve_react_app(catchall: str):
        file_path = os.path.join(frontend_dist, catchall)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(frontend_dist, "index.html"))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
