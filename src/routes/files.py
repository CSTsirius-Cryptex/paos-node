from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import os, base64, httpx, json
from src.auth import require_auth, require_memory_write
from src.config import VAULT_PATH
from src.obsidian import safe_join

router = APIRouter(dependencies=[Depends(require_auth)])

FILE_CONFIG = os.path.join(VAULT_PATH, "PAOS", "data", "file_config.json")

# ── 副檔名 → folder_type 路由表 ───────────────────────────────────────────────

EXT_MAP = {
    "images":    {"jpg", "jpeg", "png", "gif", "webp", "svg", "bmp"},
    "documents": {"pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "csv"},
    "audio":     {"mp3", "wav", "m4a", "aac", "ogg", "flac"},
}

_VALID_FOLDER_TYPES = frozenset(EXT_MAP) | {"misc"}

def _ext_to_folder_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    for folder_type, exts in EXT_MAP.items():
        if ext in exts:
            return folder_type
    return "misc"

def _safe_filename(filename: str) -> str:
    """
    驗證 filename 是安全的純檔名（不含路徑）。
    拒絕：空字串、含 / 或 \\ 的名稱、以及 '.' 或 '..'。
    Raises ValueError on invalid.
    """
    if not filename or not filename.strip():
        raise ValueError("filename 不能為空")
    name = filename.strip()
    if '/' in name or '\\' in name:
        raise ValueError(f"filename 不可包含路徑分隔符：{filename!r}")
    if name in ('..', '.'):
        raise ValueError(f"filename 不合法：{filename!r}")
    return name

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
    """計算最終儲存路徑（已驗路徑安全）"""
    # 驗 filename 是純檔名，不含路徑
    filename = _safe_filename(filename)

    # 驗 folder_type 只允許已知類型，防止目錄穿越
    if folder_type and folder_type not in _VALID_FOLDER_TYPES:
        raise ValueError(f"無效的 folder_type：{folder_type!r}，允許值：{sorted(_VALID_FOLDER_TYPES)}")

    ftype = folder_type or _ext_to_folder_type(filename)
    config = _load_config()

    if project:
        # 查 projects.json 找 vault_path
        projects_file = os.path.join(VAULT_PATH, "PAOS", "data", "projects.json")
        vault_rel = project  # fallback：直接用 project 當相對路徑
        if os.path.exists(projects_file):
            with open(projects_file, "r", encoding="utf-8") as f:
                projects = json.load(f)
            match = next((p for p in projects if p["name"] == project or p["vault_path"] == project), None)
            if match:
                vault_rel = match["vault_path"]
        # 用 safe_join 驗證 vault_rel（user 傳入的 project 可能是任意字串）
        project_base = safe_join(vault_rel.lstrip("/"))
        folder = str(project_base / "attachments" / ftype)
    else:
        # config[ftype] 來自內部設定，仍透過 safe_join 驗一次
        folder = str(safe_join(config[ftype]))

    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, filename)

# ── POST /files/from-url ──────────────────────────────────────────────────────

class FileFromUrl(BaseModel):
    url: str
    filename: str
    project: Optional[str] = None
    folder_type: Optional[str] = None

@router.post("/files/from-url", status_code=201, dependencies=[Depends(require_memory_write)])
async def file_from_url(req: FileFromUrl):
    """下載 URL 指向的檔案並存到 Vault"""
    try:
        save_path = _resolve_save_path(req.filename, req.project, req.folder_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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

@router.post("/files/upload", status_code=201, dependencies=[Depends(require_memory_write)])
def file_upload(req: FileUpload):
    """接收 base64 編碼的檔案內容並存到 Vault"""
    try:
        data = base64.b64decode(req.content_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="content_base64 解碼失敗，請確認為有效 base64 字串")

    try:
        save_path = _resolve_save_path(req.filename, req.project, req.folder_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    with open(save_path, "wb") as f:
        f.write(data)

    rel = os.path.relpath(save_path, VAULT_PATH).replace(os.sep, "/")
    return {"ok": True, "saved_to": rel}
