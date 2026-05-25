from fastapi import Depends, Header, HTTPException, Request
from typing import Optional
from jose import jwt, JWTError
from src.config import PAOS_API_KEY
from src.keys import get_cached_public_key

def require_auth(
    request: Request,
    x_api_key: Optional[str] = Header(None, include_in_schema=False),
    authorization: Optional[str] = Header(None, include_in_schema=False),
):
    """Accept either X-API-Key (owner/local) or Bearer JWT (OAuth client)."""

    # API key path
    if x_api_key:
        if x_api_key == PAOS_API_KEY:
            return {"auth": "api_key"}
        raise HTTPException(status_code=401, detail="無效的 API Key")

    # JWT path
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
        public_key = get_cached_public_key()
        if not public_key:
            raise HTTPException(status_code=503, detail="公鑰尚未就緒，請稍後再試")
        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
            if payload.get("iss") != "paos-central":
                raise HTTPException(status_code=401, detail="JWT 發行者不符")
            return {"auth": "jwt", "sub": payload.get("sub"), "email": payload.get("email"), "scope": payload.get("scope")}
        except JWTError as e:
            raise HTTPException(status_code=401, detail=f"JWT 驗證失敗: {e}")

    raise HTTPException(status_code=401, detail="需要 X-API-Key 或 Bearer token")


# 保留舊名稱供向後相容
require_api_key = require_auth


def require_scope(needed: str):
    """
    回傳一個 FastAPI Dependency，在 JWT 路徑下確認 scope 包含 `needed`。
    API key 路徑（擁有者本機呼叫）直接放行，不檢查 scope。

    用法：
        @router.put("/...", dependencies=[Depends(require_memory_write)])
    """
    def checker(auth_info: dict = Depends(require_auth)) -> dict:
        # API key = 擁有者，不受 scope 限制
        if auth_info.get("auth") == "api_key":
            return auth_info
        scope_str = auth_info.get("scope") or ""
        if needed not in scope_str.split():
            raise HTTPException(
                status_code=403,
                detail=f"此操作需要 {needed} 權限（token scope 不足）",
            )
        return auth_info
    return checker


# 預建實例（module 載入時建立一次，FastAPI 可正確快取 per-request）
require_memory_read  = require_scope("memory:read")
require_memory_write = require_scope("memory:write")
