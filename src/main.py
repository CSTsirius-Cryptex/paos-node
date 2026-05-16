from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.routes import health, memory, handoffs, gpts, notes, todos, jobs
from src.central import register_node
from src.keys import fetch_public_key
from src.config import NODE_PORT
import logging

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await fetch_public_key()
        logger.info("Public key fetched from Central.")
    except Exception as e:
        logger.warning(f"Failed to fetch public key: {e}. JWT auth unavailable until key is loaded.")
    await register_node()
    yield

app = FastAPI(title="PAOS Node", lifespan=lifespan)

app.include_router(health.router)
app.include_router(memory.router)
app.include_router(handoffs.router)
app.include_router(notes.router)
app.include_router(todos.router)
app.include_router(jobs.router)
app.include_router(gpts.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=NODE_PORT, reload=False)
