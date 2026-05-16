import json, os
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
from src.auth import require_auth
from src.config import VAULT_PATH

router = APIRouter(dependencies=[Depends(require_auth)])

DATA_FILE = os.path.join(VAULT_PATH, "PAOS", "data", "jobs.json")

def _load() -> list:
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def _save(data: list) -> None:
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

class JobCreate(BaseModel):
    type: str
    payload: Optional[dict] = {}

class JobPatch(BaseModel):
    status: Optional[str] = None    # pending / running / done / failed
    result: Optional[dict] = None
    error: Optional[str] = None

@router.get("/jobs")
def list_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(20),
):
    data = _load()
    if status:
        data = [j for j in data if j.get("status") == status]
    return data[-limit:]

@router.get("/jobs/next")
def get_next_job():
    """取得下一個 pending job，並標記為 running"""
    data = _load()
    for job in data:
        if job.get("status") == "pending":
            job["status"] = "running"
            job["started_at"] = datetime.now(timezone.utc).isoformat()
            _save(data)
            return job
    raise HTTPException(status_code=404, detail="目前沒有待處理的 job")

@router.post("/jobs", status_code=201)
def create_job(req: JobCreate):
    data = _load()
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": f"job-{len(data)+1:04d}",
        "type": req.type,
        "status": "pending",
        "payload": req.payload or {},
        "result": None,
        "error": None,
        "created_at": now,
        "started_at": None,
        "done_at": None,
    }
    data.append(entry)
    _save(data)
    return entry

@router.patch("/jobs/{job_id}")
def patch_job(job_id: str, req: JobPatch):
    data = _load()
    for job in data:
        if job["id"] == job_id:
            if req.status is not None:
                job["status"] = req.status
                if req.status in ("done", "failed"):
                    job["done_at"] = datetime.now(timezone.utc).isoformat()
            if req.result is not None:
                job["result"] = req.result
            if req.error is not None:
                job["error"] = req.error
            _save(data)
            return job
    raise HTTPException(status_code=404, detail=f"找不到 job: {job_id}")
