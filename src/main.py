from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from src.routes import health, memory, handoffs, gpts, notes, todos, jobs, projects, files
from src.routes import panel as panel_router
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

import os
_central = os.getenv("CENTRAL_URL", "https://paos-central-production.up.railway.app")
app = FastAPI(
    title="PAOS Node",
    servers=[{"url": f"{_central}/node", "description": "PAOS Central proxy"}],
    lifespan=lifespan,
)

# ── Panel 本機限制 middleware ────────────────────────────────────
# /panel/api/* 只允許 localhost 連線，防止 cloudflared tunnel 將控制台 API 暴露到網路。
# pywebview 視窗內的 fetch 來源是 127.0.0.1，正常可用；外部請求一律 403。
@app.middleware("http")
async def panel_localhost_only(request: Request, call_next):
    if request.url.path.startswith("/panel/api/"):
        client_host = request.client.host if request.client else ""
        if client_host not in ("127.0.0.1", "::1", "localhost"):
            return JSONResponse(status_code=403, content={"detail": "panel API 僅限本機存取"})
    return await call_next(request)

app.include_router(health.router)
app.include_router(memory.router)
app.include_router(handoffs.router)
app.include_router(notes.router)
app.include_router(todos.router)
app.include_router(jobs.router)
app.include_router(projects.router)
app.include_router(files.router)
app.include_router(gpts.router)
app.include_router(panel_router.router)

# Panel 靜態檔案（index.html、panel.js、panel.css）
# 掛在 /panel，但 /panel/api/* 已由 panel router 優先處理
_static_dir = Path(__file__).parent.parent / "static" / "panel"
if _static_dir.exists():
    app.mount("/panel", StaticFiles(directory=str(_static_dir), html=True), name="panel-static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=NODE_PORT, reload=False)
