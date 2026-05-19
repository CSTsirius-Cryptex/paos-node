from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import os, base64, httpx, json
from src.auth import require_auth
from src.config import VAULT_PATH

router = APIRouter(dependencies=[Depends(require_auth)])

FILE_CONFIG = os.path.join(VAULT_PATH, "PAOS", "data", "file_config.json")

# ── 副檔名 → folder_type 路由表 ───────────────────────────────────────────────

EXT_MAP = {
    "images":    {"jpg", "jpeg", "png", "gif", "webp", "svg", "bmp"},
    "documents": {"pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "csv"},
    "audio":     {"mp3", "wav", "m4a", "aac", "ogg", "flac"},
}

def _ext_to_folder_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    for folder_type, exts in EXT_MAP.items():
        if ext in exts:
            return folder_type
    return "misc"

# ── 載入自訂路徑設定 ──────────────────────────────────────────────────────────

def _load_config() -> dict:
    defaults = {
        "images":    "PAOS/attachments/images",
        "documents": "PAOS/attachments/documents",
        "audio":     "PAOS/attachments/audio",
        "misc":      "PAOS/attachments/misc",
    }
    if not os.path.exists(FILE_CONFIG):
        return defaults
    with open(FILE_CONFIG, "r", encoding="utf-8") as f:
        return {**defaults, **json.load(f)}

def _resolve_save_path(filename: str, project: Optional[str], folder_type: Optional[str]) -> str:
    """計算最終儲存路徑"""
    ftype = folder_type or _ext_to_folder_type(filename)
    config = _load_config()

    if project:
        # 查 projects.json 找 vault_path
        projects_file = os.path.join(VAULT_PATH, "PAOS", "data", "projects.json")
        vault_rel = project  # fallback：直接用 project 當路徑
        if os.path.exists(projects_file):
            with open(projects_file, "r", encoding="utf-8") as f:
                projects = json.load(f)
            match = next((p for p in projects if p["name"] == project or p["vault_path"] == project), None)
            if match:
                vault_rel = match["vault_path"]
        folder = os.path.join(VAULT_PATH, vault_rel.replace("/", os.sep), "attachments", ftype)
    else:
        folder = os.path.join(VAULT_PATH, config[ftype].replace("/", os.sep))

    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, filename)

# ── POST /files/from-url ──────────────────────────────────────────────────────

class FileFromUrl(BaseModel):
    url: str
    filename: str
    project: Optional[str] = None
    folder_type: Optional[str] = None

@router.post("/files/from-url", status_code=201)
async def file_from_url(req: FileFromUrl):
    """下載 URL 指向的檔案並存到 Vault"""
    save_path = _resolve_save_path(req.filename, req.project, req.folder_type)

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            r = await client.get(req.url)
            r.raise_for_status()
            with open(save_path, "wb") as f:
                f.write(r.content)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"下載失敗：{e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    rel = os.path.relpath(save_path, VAULT_PATH).replace(os.sep, "/")
    return {"ok": True, "saved_to": rel}

# ── POST /files/upload ────────────────────────────────────────────────────────

class FileUpload(BaseModel):
    content_base64: str
    filename: str
    project: Optional[str] = None
    folder_type: Optional[str] = None

@router.post("/files/upload", status_code=201)
def file_upload(req: FileUpload):
    """接收 base64 編碼的檔案內容並存到 Vault"""
    try:
        data = base64.b64decode(req.content_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="content_base64 解碼失敗，請確認為有效 base64 字串")

    save_path = _resolve_save_path(req.filename, req.project, req.folder_type)
    with open(save_path, "wb") as f:
        f.write(data)

    rel = os.path.relpath(save_path, VAULT_PATH).replace(os.sep, "/")
    return {"ok": True, "saved_to": rel}
