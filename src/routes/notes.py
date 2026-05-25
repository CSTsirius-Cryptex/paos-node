from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from src.auth import require_auth, require_memory_write
from src import obsidian

router = APIRouter(dependencies=[Depends(require_auth)])

class NoteWrite(BaseModel):
    content: str

@router.get("/notes")
def list_notes(folder: str = Query("", description="子資料夾路徑，空字串代表全 vault")):
    try:
        return {"notes": obsidian.list_notes(folder)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/notes/{path:path}")
def get_note(path: str):
    try:
        content = obsidian.read_note(path)
        return {"path": path, "content": content}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/notes/{path:path}", status_code=200, dependencies=[Depends(require_memory_write)])
def write_note(path: str, req: NoteWrite):
    try:
        obsidian.write_note(path, req.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "path": path}

@router.post("/notes/{path:path}/append", status_code=200, dependencies=[Depends(require_memory_write)])
def append_note(path: str, req: NoteWrite):
    try:
        obsidian.append_note(path, req.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "path": path}
