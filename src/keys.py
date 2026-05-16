import httpx
from src.config import CENTRAL_URL

_cached_public_key: str | None = None

async def fetch_public_key() -> str:
    global _cached_public_key
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{CENTRAL_URL}/oauth/public-key", timeout=10)
        r.raise_for_status()
        _cached_public_key = r.json()["public_key"]
    return _cached_public_key

def get_cached_public_key() -> str | None:
    return _cached_public_key
