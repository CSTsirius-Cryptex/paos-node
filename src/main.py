from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from src.routes import health, memory, handoffs, gpts, notes, todos, jobs, projects, files, setup as setup_router_module
from src.routes import panel as panel_router
from src.central import register_node
from src.keys import fetch_public_key
from src.config import NODE_PORT, INIT_AGENTS
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

    # 自動初始化 .env 中 INIT_AGENTS 列出的 agent Vault 結構
    if INIT_AGENTS:
        from src.routes.setup import init_agent_vault
        for agent in INIT_AGENTS:
            try:
                result = init_agent_vault(agent, force=False)
                logger.info(f"[setup] {agent} 初始化完成：新建 {len(result['created'])} 個項目，略過 {len(result['skipped'])} 個")
            except Exception as e:
                logger.warning(f"[setup] {agent} 初始化失敗：{e}")

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
app.include_router(setup_router_module.router)
app.include_router(memory.router)
app.include_router(handoffs.router)
app.include_router(notes.router)
app.include_router(todos.router)
app.include_router(jobs.router)
app.include_router(projects.router)
app.include_router(files.router)
app.include_router(gpts.router)
app.include_router(panel_router.router)

# Panel 靜態檔案（用 FileResponse 明確路由，避免 StaticFiles mount 攔截 /panel/api/*）
_static_dir = Path(__file__).parent.parent / "static" / "panel"

_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}

@app.get("/panel", include_in_schema=False)
@app.get("/panel/", include_in_schema=False)
@app.get("/panel/index.html", include_in_schema=False)
async def panel_index():
    return FileResponse(_static_dir / "index.html", media_type="text/html", headers=_NO_CACHE)

@app.get("/panel/panel.js", include_in_schema=False)
async def panel_js():
    return FileResponse(_static_dir / "panel.js", media_type="application/javascript", headers=_NO_CACHE)

@app.get("/panel/panel.css", include_in_schema=False)
async def panel_css():
    return FileResponse(_static_dir / "panel.css", media_type="text/css", headers=_NO_CACHE)

# 字型 & 圖示靜態目錄（路徑不與 /panel/api/* 衝突，可直接 StaticFiles）
_fonts_dir  = Path(__file__).parent.parent / "static" / "fonts"
_assets_dir = Path(__file__).parent.parent / "static" / "assets"
if _fonts_dir.exists():
    app.mount("/panel/fonts",  StaticFiles(directory=str(_fonts_dir)),  name="panel-fonts")
if _assets_dir.exists():
    app.mount("/panel/assets", StaticFiles(directory=str(_assets_dir)), name="panel-assets")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=NODE_PORT, reload=False)
