import httpx, os
from src.config import CENTRAL_URL, NODE_PUBLIC_URL

async def register_node() -> bool:
    """向 Central 登錄本機 Node URL。需要 NODE_PUBLIC_URL 環境變數。"""
    bearer = os.getenv("CENTRAL_OWNER_TOKEN", "")
    if not bearer or not NODE_PUBLIC_URL:
        print("[Central] 跳過 node 登錄：CENTRAL_OWNER_TOKEN 或 NODE_PUBLIC_URL 未設定")
        return False
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{CENTRAL_URL}/me/node",
                headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"},
                json={"node_url": NODE_PUBLIC_URL},
                timeout=10,
            )
        if resp.status_code == 200:
            print(f"[Central] Node 已登錄：{NODE_PUBLIC_URL}")
            return True
        print(f"[Central] Node 登錄失敗：{resp.status_code} {resp.text}")
        return False
    except Exception as e:
        print(f"[Central] Node 登錄例外：{e}")
        return False
