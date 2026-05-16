from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from src.auth import require_auth
from src import obsidian

router = APIRouter(dependencies=[Depends(require_auth)])

class NoteWrite(BaseModel):
    content: str

@router.get("/notes")
def list_notes(folder: str = Query("", description="子資料夾路徑，空字串代表全 vault")):
    return {"notes": obsidian.list_notes(folder)}

@router.get("/notes/{path:path}")
def get_note(path: str):
    try:
        content = obsidian.read_note(path)
        return {"path": path, "content": content}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.put("/notes/{path:path}", status_code=200)
def write_note(path: str, req: NoteWrite):
    obsidian.write_note(path, req.content)
    return {"ok": True, "path": path}

@router.post("/notes/{path:path}/append", status_code=200)
def append_note(path: str, req: NoteWrite):
    obsidian.append_note(path, req.content)
    return {"ok": True, "path": path}
