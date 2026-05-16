from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter()

@router.get("/health")
def health():
    return {"ok": True, "service": "paos-node", "time": datetime.now(timezone.utc).isoformat()}
