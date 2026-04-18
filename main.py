import asyncio
import traceback
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.database import init_db
from agent.loop import agent_execution_loop
from api.endpoints import router as api_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Initializing SQLite Database...")
    init_db()
    
    # Google Services: Native Google Cloud Logging Integration
    try:
        import google.cloud.logging
        client = google.cloud.logging.Client()
        client.setup_logging()
        print("Google Cloud Logging successfully attached.")
    except Exception as e:
        print("Running locally (Google Cloud credentials not found) — skipping Cloud Logging.")
    
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
