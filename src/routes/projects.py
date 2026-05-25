from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import os, json
from src.auth import require_auth, require_memory_write
from src.config import VAULT_PATH
from src.obsidian import safe_join

router = APIRouter(dependencies=[Depends(require_auth)])

PROJECTS_DATA = os.path.join(VAULT_PATH, "PAOS", "data", "projects.json")

# ── helpers ──────────────────────────────────────────────────────────────────

def _load_paos_projects() -> list[dict]:
    if not os.path.exists(PROJECTS_DATA):
        return []
    with open(PROJECTS_DATA, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_paos_projects(projects: list[dict]) -> None:
    os.makedirs(os.path.dirname(PROJECTS_DATA), exist_ok=True)
    with open(PROJECTS_DATA, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)

EXCLUDE_DIRS = {
    "PAOS", ".obsidian", ".trash", "templates", "Templates",
    "attachments", "data", "memory", "worklog", "workspace",
    "work-log", "translations", "perspectives", "decisions",
    "insights", "knowledge", "contacts", "skill-insights",
}

def _scan_vault_folders(max_depth: int = 4) -> list[dict]:
    """遞迴掃描 Vault 最多 max_depth 層資料夾，排除系統目錄"""
    results = []

    def _walk(current_path: str, rel_path: str, depth: int):
        if depth > max_depth:
            return
        try:
            entries = os.listdir(current_path)
        except PermissionError:
            return
        for name in entries:
            if name in EXCLUDE_DIRS or name.startswith("."):
                continue
            full = os.path.join(current_path, name)
            if not os.path.isdir(full):
                continue
            vault_rel = f"{rel_path}/{name}" if rel_path else name
            results.append({
                "name": name,
                "vault_path": vault_rel,
                "source": "vault",
            })
            _walk(full, vault_rel, depth + 1)

    _walk(VAULT_PATH, "", 1)
    return results

# ── GET /projects ─────────────────────────────────────────────────────────────

@router.get("/projects")
def list_projects():
    """回傳可用專案清單：Vault 資料夾掃描 ∪ PAOS 自己維護的清單"""
    vault_projects = _scan_vault_folders()
    paos_projects = _load_paos_projects()

    # 以 vault_path 去重，PAOS 清單優先（保留額外欄位）
    seen = {p["vault_path"]: p for p in paos_projects}
    for p in vault_projects:
        if p["vault_path"] not in seen:
            seen[p["vault_path"]] = p

    return {"projects": list(seen.values())}

# ── POST /projects ────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    vault_path: str
    description: Optional[str] = None

@router.post("/projects", status_code=201, dependencies=[Depends(require_memory_write)])
def create_project(req: ProjectCreate):
    """建立新專案：在 Vault 建資料夾並加入 PAOS 清單"""
    try:
        target = safe_join(req.vault_path.lstrip("/"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    os.makedirs(target, exist_ok=True)
    # 建立 attachments 子目錄
    for sub in ("attachments/images", "attachments/documents", "attachments/audio", "attachments/misc"):
        os.makedirs(os.path.join(target, sub.replace("/", os.sep)), exist_ok=True)

    projects = _load_paos_projects()
    # 避免重複
    if not any(p["vault_path"] == req.vault_path for p in projects):
        projects.append({
            "name": req.name,
            "vault_path": req.vault_path,
            "description": req.description or "",
            "source": "paos",
        })
        _save_paos_projects(projects)

    return {"ok": True, "vault_path": req.vault_path}
