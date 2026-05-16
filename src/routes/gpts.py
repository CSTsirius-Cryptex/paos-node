import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from src.auth import require_auth
from src.config import CENTRAL_URL

router = APIRouter(dependencies=[Depends(require_auth)])

@router.get("/gpts")
async def list_gpts(request: Request):
    # 直接向 Central 公開端點取得 GPT 列表（無需 auth，/gpts 為公開資源）
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{CENTRAL_URL}/gpts", timeout=10)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="無法從 Central 取得 GPT 列表")
    return resp.json()
