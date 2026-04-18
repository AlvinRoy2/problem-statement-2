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

app.include_router(api_router, prefix="/api")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
