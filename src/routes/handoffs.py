import json, os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
from src.auth import require_api_key
from src.config import VAULT_PATH

router = APIRouter(dependencies=[Depends(require_api_key)])

DATA_FILE = os.path.join(VAULT_PATH, "PAOS", "data", "handoffs.json")

def _load() -> list:
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def _save(data: list) -> None:
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

class HandoffCreate(BaseModel):
    from_agent: str
    to_agent: str
    task_id: str
    summary: str
    context: Optional[dict] = None
    status: Optional[str] = "pending"

class HandoffPatch(BaseModel):
    status: Optional[str] = None
    summary: Optional[str] = None
    context: Optional[dict] = None

@router.get("/handoffs")
def list_handoffs(limit: int = 20, status: Optional[str] = None):
    data = _load()
    if status:
        data = [h for h in data if h.get("status") == status]
    return data[-limit:]

@router.post("/handoffs", status_code=201)
def create_handoff(req: HandoffCreate):
    data = _load()
    entry = {
        "id": f"hoff-{len(data)+1:04d}",
        "from_agent": req.from_agent,
        "to_agent": req.to_agent,
        "task_id": req.task_id,
        "summary": req.summary,
        "context": req.context or {},
        "status": req.status,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    data.append(entry)
    _save(data)
    return entry

@router.patch("/handoffs/{handoff_id}")
def patch_handoff(handoff_id: str, req: HandoffPatch):
    data = _load()
    for entry in data:
        if entry["id"] == handoff_id:
            if req.status is not None:
                entry["status"] = req.status
            if req.summary is not None:
                entry["summary"] = req.summary
            if req.context is not None:
                entry["context"] = req.context
            entry["updated_at"] = datetime.now(timezone.utc).isoformat()
            _save(data)
            return entry
    raise HTTPException(status_code=404, detail=f"找不到 handoff: {handoff_id}")
