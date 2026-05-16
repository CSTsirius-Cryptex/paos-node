import json, os
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
from src.auth import require_auth
from src.config import VAULT_PATH

router = APIRouter(dependencies=[Depends(require_auth)])

DATA_FILE = os.path.join(VAULT_PATH, "PAOS", "data", "todos.json")

def _load() -> list:
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def _save(data: list) -> None:
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

class TodoCreate(BaseModel):
    title: str
    body: Optional[str] = None
    status: Optional[str] = "todo"       # todo / in_progress / done
    priority: Optional[str] = "normal"   # low / normal / high
    assignee: Optional[str] = None       # email or agent name
    tags: Optional[list[str]] = []

class TodoPatch(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    tags: Optional[list[str]] = None

@router.get("/todos")
def list_todos(
    status: Optional[str] = Query(None),
    assignee: Optional[str] = Query(None),
    limit: int = Query(50),
):
    data = _load()
    if status:
        data = [t for t in data if t.get("status") == status]
    if assignee:
        data = [t for t in data if t.get("assignee") == assignee]
    return data[-limit:]

@router.post("/todos", status_code=201)
def create_todo(req: TodoCreate):
    data = _load()
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": f"todo-{len(data)+1:04d}",
        "title": req.title,
        "body": req.body or "",
        "status": req.status,
        "priority": req.priority,
        "assignee": req.assignee,
        "tags": req.tags or [],
        "created_at": now,
        "updated_at": now,
    }
    data.append(entry)
    _save(data)
    return entry

@router.patch("/todos/{todo_id}")
def patch_todo(todo_id: str, req: TodoPatch):
    data = _load()
    for entry in data:
        if entry["id"] == todo_id:
            if req.title is not None:
                entry["title"] = req.title
            if req.body is not None:
                entry["body"] = req.body
            if req.status is not None:
                entry["status"] = req.status
            if req.priority is not None:
                entry["priority"] = req.priority
            if req.assignee is not None:
                entry["assignee"] = req.assignee
            if req.tags is not None:
                entry["tags"] = req.tags
            entry["updated_at"] = datetime.now(timezone.utc).isoformat()
            _save(data)
            return entry
    raise HTTPException(status_code=404, detail=f"找不到 todo: {todo_id}")

@router.delete("/todos/{todo_id}", status_code=200)
def delete_todo(todo_id: str):
    data = _load()
    new_data = [t for t in data if t["id"] != todo_id]
    if len(new_data) == len(data):
        raise HTTPException(status_code=404, detail=f"找不到 todo: {todo_id}")
    _save(new_data)
    return {"ok": True, "deleted": todo_id}
