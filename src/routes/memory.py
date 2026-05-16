from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from src.auth import require_api_key
from src.obsidian import write_note, append_note, resolve_memory_path

router = APIRouter(dependencies=[Depends(require_api_key)])

class MemoryRequest(BaseModel):
    memory_type: str
    agent_name: Optional[str] = None
    slug: Optional[str] = None
    l1_type: Optional[str] = None
    l1_summary: Optional[str] = None
    l1_tags: Optional[list[str]] = None
    l1_importance: Optional[int] = None
    l2_content: str
    l3_detail: Optional[str] = None
    append: Optional[bool] = False

@router.post("/memory")
@router.post("/paos/memory")
def write_memory(req: MemoryRequest):
    try:
        path = resolve_memory_path(req.memory_type, {
            "agent_name": req.agent_name or "",
            "slug": req.slug or "",
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    lines = []
    if req.l1_summary:
        tags_str = " ".join(f"#{t}" for t in (req.l1_tags or []))
        importance = f"{'★' * (req.l1_importance or 3)}"
        lines.append(f"## [{req.l1_type or req.memory_type}] {req.l1_summary} {importance}")
        if tags_str:
            lines.append(tags_str)
        lines.append("")
    lines.append(req.l2_content)
    if req.l3_detail:
        lines.append("")
        lines.append(f"### 詳細")
        lines.append(req.l3_detail)

    content = "\n".join(lines)

    if req.append or req.memory_type == "work_log":
        append_note(path, content)
    else:
        write_note(path, content)

    return {"ok": True, "path": path}
