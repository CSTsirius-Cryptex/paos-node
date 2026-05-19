"""
panel.py — PAOS Node 控制台 API（CP-1 ~ CP-3）
所有 /panel/api/* 路由只接受本機連線（見 main.py middleware）。
"""
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.config import CENTRAL_URL, VAULT_PATH, NODE_PUBLIC_URL

router = APIRouter(prefix="/panel/api", tags=["panel"])

# ── 路徑常數 ──────────────────────────────────────────────────────
ENV_FILE        = Path(__file__).parent.parent.parent / ".env"
CP_CONFIG_FILE  = Path(__file__).parent.parent.parent / "cp_config.json"
LOG_FILE        = Path(__file__).parent.parent.parent / "logs" / "node.log"
TASK_NAME_NODE  = "PAOS-Node"

# ── 輔助函數 ──────────────────────────────────────────────────────

def _read_cp_config() -> dict:
    try:
        return json.loads(CP_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"refresh_interval_seconds": 30, "attachment_default_path": "PAOS/attachments"}

def _write_cp_config(data: dict):
    merged = _read_cp_config()
    merged.update(data)
    CP_CONFIG_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

def _read_env() -> dict:
    """讀 .env 為 key→value dict（不覆蓋現有 os.environ）。"""
    result = {}
    if not ENV_FILE.exists():
        return result
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result

def _write_env_key(key: str, value: str):
    """更新或新增 .env 中的單一 key。"""
    if not ENV_FILE.exists():
        return
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

def _get_scheduler_status(task_name: str) -> str:
    """查詢 Windows Task Scheduler 工作狀態，回傳 'running' 或 'stopped'。"""
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST"],
            capture_output=True, text=True, timeout=5
        )
        output = result.stdout + result.stderr
        # 狀態行格式：Status: Running / 就緒 / 已停用 etc.
        for line in output.splitlines():
            low = line.lower()
            if "status:" in low or "狀態:" in low:
                if "running" in low or "執行中" in low:
                    return "running"
        return "stopped"
    except Exception:
        return "stopped"

def _set_scheduler_enabled(task_name: str, enabled: bool) -> bool:
    """啟用或停用 Windows 排程工作。"""
    try:
        action = "/Enable" if enabled else "/Disable"
        result = subprocess.run(
            ["schtasks", "/Change", "/TN", task_name, action],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False

def _decode_jwt_exp(token: str) -> Optional[int]:
    """不驗簽章，只解析 JWT payload 拿 exp（Unix timestamp）。"""
    try:
        import base64
        parts = token.split(".")
        if len(parts) < 2:
            return None
        pad = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(pad))
        return payload.get("exp")
    except Exception:
        return None


# ── CP-1：GET /panel/api/status ───────────────────────────────────

@router.get("/status")
async def get_status():
    env = _read_env()
    central_url = env.get("CENTRAL_URL", CENTRAL_URL)
    tunnel_url  = env.get("NODE_PUBLIC_URL", NODE_PUBLIC_URL) or ""
    owner_token = env.get("CENTRAL_OWNER_TOKEN", "")

    result: dict = {}

    # 1. 排程工作
    sched_status = _get_scheduler_status(TASK_NAME_NODE)
    result["scheduler"] = {"status": sched_status}

    # 2. Node /health（自我檢測）
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://127.0.0.1:3100/health", timeout=3)
        latency = int((time.monotonic() - t0) * 1000)
        result["node"] = {"status": "ok" if resp.status_code == 200 else "error", "latency_ms": latency}
    except Exception:
        result["node"] = {"status": "error", "latency_ms": None}

    # 3. Vault 存取
    try:
        vault = Path(env.get("VAULT_PATH", VAULT_PATH))
        ok = vault.exists() and os.access(vault, os.R_OK | os.W_OK)
        result["vault"] = {"status": "ok" if ok else "error", "path": str(vault)}
    except Exception:
        result["vault"] = {"status": "error", "path": ""}

    # 4. Tunnel
    if tunnel_url:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.head(tunnel_url, timeout=5, follow_redirects=True)
            result["tunnel"] = {"status": "connected", "url": tunnel_url}
        except Exception:
            result["tunnel"] = {"status": "disconnected", "url": tunnel_url}
    else:
        result["tunnel"] = {"status": "disconnected", "url": ""}

    # 5. Central /health
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{central_url}/health", timeout=5)
        latency = int((time.monotonic() - t0) * 1000)
        result["central"] = {"status": "ok" if resp.status_code == 200 else "error", "latency_ms": latency}
    except Exception:
        result["central"] = {"status": "error", "latency_ms": None}

    # 6. 已向 Central 登錄（比對 tunnel_url）
    if owner_token and tunnel_url:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{central_url}/me/node",
                    headers={"Authorization": f"Bearer {owner_token}"},
                    timeout=5
                )
            if resp.status_code == 200:
                data = resp.json()
                registered_url = data.get("node_url", "")
                ok = registered_url == tunnel_url
                result["registered"] = {"status": "ok" if ok else "error", "node_url": registered_url}
            else:
                result["registered"] = {"status": "error", "node_url": ""}
        except Exception:
            result["registered"] = {"status": "error", "node_url": ""}
    else:
        result["registered"] = {"status": "error", "node_url": ""}

    return result


# ── CP-1：GET /panel/api/diagnose ─────────────────────────────────

@router.get("/diagnose")
async def run_diagnose():
    env = _read_env()
    central_url = env.get("CENTRAL_URL", CENTRAL_URL)
    tunnel_url  = env.get("NODE_PUBLIC_URL", NODE_PUBLIC_URL) or ""
    owner_token = env.get("CENTRAL_OWNER_TOKEN", "")
    vault_path  = env.get("VAULT_PATH", VAULT_PATH)

    steps = []
    all_ok = True

    def add(step, name, ok, **extra):
        nonlocal all_ok
        if not ok:
            all_ok = False
        entry = {"step": step, "name": name, "status": "ok" if ok else "error"}
        entry.update(extra)
        steps.append(entry)
        return ok

    # Step 1：排程工作
    sched_ok = _get_scheduler_status(TASK_NAME_NODE) == "running"
    prev_ok = add(1, "排程工作", sched_ok,
                  detail="PAOS-Node 執行中" if sched_ok else "排程工作未執行，請確認 Task Scheduler")

    # Step 2：Node /health
    if prev_ok:
        try:
            t0 = time.monotonic()
            async with httpx.AsyncClient() as client:
                resp = await client.get("http://127.0.0.1:3100/health", timeout=3)
            latency = int((time.monotonic() - t0) * 1000)
            ok = resp.status_code == 200
            prev_ok = add(2, "Node /health", ok, latency_ms=latency,
                          detail=f"回應 {latency}ms" if ok else f"HTTP {resp.status_code}")
        except Exception as e:
            prev_ok = add(2, "Node /health", False, detail=f"連線失敗：{e}")
    else:
        add(2, "Node /health", False, detail="上一步失敗，跳過")

    # Step 3：Vault 存取
    if prev_ok:
        try:
            vault = Path(vault_path)
            ok = vault.exists() and os.access(vault, os.R_OK | os.W_OK)
            prev_ok = add(3, "Vault 存取", ok,
                          detail="路徑存在且可讀寫" if ok else f"路徑不存在或無讀寫權限：{vault_path}")
        except Exception as e:
            prev_ok = add(3, "Vault 存取", False, detail=str(e))
    else:
        add(3, "Vault 存取", False, detail="上一步失敗，跳過")

    # Step 4：Tunnel 回應
    if prev_ok:
        if tunnel_url:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.head(tunnel_url, timeout=5, follow_redirects=True)
                ok = resp.status_code < 500
                prev_ok = add(4, "Tunnel 回應", ok,
                              url=tunnel_url,
                              detail=tunnel_url if ok else f"HTTP {resp.status_code}")
            except Exception as e:
                prev_ok = add(4, "Tunnel 回應", False, detail=f"連線失敗：{e}")
        else:
            prev_ok = add(4, "Tunnel 回應", False, detail="NODE_PUBLIC_URL 未設定")
    else:
        add(4, "Tunnel 回應", False, detail="上一步失敗，跳過")

    # Step 5：Central /health
    if prev_ok:
        try:
            t0 = time.monotonic()
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{central_url}/health", timeout=5)
            latency = int((time.monotonic() - t0) * 1000)
            ok = resp.status_code == 200
            prev_ok = add(5, "Central /health", ok,
                          latency_ms=latency,
                          detail=f"回應 {latency}ms" if ok else f"HTTP {resp.status_code}")
        except Exception as e:
            prev_ok = add(5, "Central /health", False, detail=f"連線逾時或失敗：{e}")
    else:
        add(5, "Central /health", False, detail="上一步失敗，跳過")

    # Step 6：Central 已登錄
    if prev_ok and owner_token:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{central_url}/me/node",
                    headers={"Authorization": f"Bearer {owner_token}"},
                    timeout=5
                )
            if resp.status_code == 200:
                data = resp.json()
                registered = data.get("node_url", "")
                ok = registered == tunnel_url
                add(6, "Central 已登錄", ok,
                    node_url=registered,
                    detail="登錄 URL 符合" if ok else f"登錄 URL 不符（Central: {registered}，本機: {tunnel_url}）")
            else:
                add(6, "Central 已登錄", False, detail=f"驗證失敗（HTTP {resp.status_code}），請更新 CENTRAL_OWNER_TOKEN")
        except Exception as e:
            add(6, "Central 已登錄", False, detail=str(e))
    else:
        add(6, "Central 已登錄", False,
            detail="上一步失敗，跳過" if not prev_ok else "CENTRAL_OWNER_TOKEN 未設定")

    return {"steps": steps, "all_ok": all_ok}


# ── CP-2：GET /panel/api/gpts ─────────────────────────────────────

@router.get("/gpts")
async def get_gpts():
    env = _read_env()
    central_url = env.get("CENTRAL_URL", CENTRAL_URL)
    owner_token = env.get("CENTRAL_OWNER_TOKEN", "")

    if not owner_token:
        return {"gpts": [], "note": "CENTRAL_OWNER_TOKEN 未設定，請在設定頁重新登入"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{central_url}/portal/account/me/gpts",
                headers={"Authorization": f"Bearer {owner_token}"},
                timeout=10
            )
        if resp.status_code == 200:
            return {"gpts": resp.json()}
        if resp.status_code == 401:
            return {"gpts": [], "note": "Token 已失效，請在設定頁重新登入"}
        return {"gpts": [], "note": f"Central 回應 {resp.status_code}"}
    except Exception as e:
        return {"gpts": [], "note": f"連線失敗：{e}"}


# ── CP-3：GET /panel/api/settings ────────────────────────────────

@router.get("/settings")
async def get_settings():
    env = _read_env()
    cfg = _read_cp_config()

    # Token 有效期解析
    owner_token = env.get("CENTRAL_OWNER_TOKEN", "")
    token_expires_at = None
    token_days_remaining = None
    if owner_token:
        exp = _decode_jwt_exp(owner_token)
        if exp:
            token_expires_at = exp
            token_days_remaining = max(0, int((exp - time.time()) / 86400))

    # auto_start：查詢排程工作是否啟用
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME_NODE, "/FO", "LIST"],
            capture_output=True, text=True, timeout=5
        )
        output = result.stdout + result.stderr
        auto_start = not any(
            kw in output.lower() for kw in ["disabled", "已停用"]
        )
    except Exception:
        auto_start = False

    return {
        "vault_path":              env.get("VAULT_PATH", VAULT_PATH),
        "auto_start":              auto_start,
        "tunnel_url":              env.get("NODE_PUBLIC_URL", ""),
        "refresh_interval_seconds": cfg.get("refresh_interval_seconds", 30),
        "attachment_default_path": cfg.get("attachment_default_path", "PAOS/attachments"),
        "token_expires_at":        token_expires_at,
        "token_days_remaining":    token_days_remaining,
        "owner_email":             env.get("OWNER_EMAIL", ""),
    }


# ── CP-3：PUT /panel/api/settings ────────────────────────────────

class SettingsUpdate(BaseModel):
    vault_path:               Optional[str]  = None
    auto_start:               Optional[bool] = None
    refresh_interval_seconds: Optional[int]  = None
    attachment_default_path:  Optional[str]  = None

@router.put("/settings")
async def update_settings(body: SettingsUpdate):
    restart_required = False
    cfg_updated = {}

    if body.vault_path is not None:
        _write_env_key("VAULT_PATH", body.vault_path)
        restart_required = True

    if body.auto_start is not None:
        _set_scheduler_enabled(TASK_NAME_NODE, body.auto_start)

    if body.refresh_interval_seconds is not None:
        cfg_updated["refresh_interval_seconds"] = body.refresh_interval_seconds

    if body.attachment_default_path is not None:
        cfg_updated["attachment_default_path"] = body.attachment_default_path

    if cfg_updated:
        _write_cp_config(cfg_updated)

    return {"ok": True, "restart_required": restart_required}


# ── CP-4：GET /panel/api/logs ─────────────────────────────────────

@router.get("/logs")
async def get_logs(lines: int = 200):
    lines = min(lines, 500)
    if not LOG_FILE.exists():
        return {"lines": [], "total_lines": 0}
    try:
        all_lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        total = len(all_lines)
        return {"lines": all_lines[-lines:], "total_lines": total}
    except Exception as e:
        return {"lines": [f"[錯誤] 無法讀取 log：{e}"], "total_lines": 0}


# ── CP-3：POST /panel/api/reauth/request ─────────────────────────

class ReauthRequestBody(BaseModel):
    email: str

@router.post("/reauth/request")
async def reauth_request(body: ReauthRequestBody):
    env = _read_env()
    central_url = env.get("CENTRAL_URL", CENTRAL_URL)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{central_url}/auth/request-otp",
                json={"email": body.email},
                timeout=10
            )
        if resp.status_code == 200:
            return {"ok": True}
        return JSONResponse(status_code=resp.status_code,
                            content={"ok": False, "detail": resp.text})
    except Exception as e:
        return JSONResponse(status_code=503, content={"ok": False, "detail": str(e)})


# ── CP-3：POST /panel/api/reauth/verify ──────────────────────────

class ReauthVerifyBody(BaseModel):
    email: str
    otp:   str

@router.post("/reauth/verify")
async def reauth_verify(body: ReauthVerifyBody):
    env = _read_env()
    central_url = env.get("CENTRAL_URL", CENTRAL_URL)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{central_url}/auth/verify-otp",
                json={"email": body.email, "otp": body.otp},
                timeout=10
            )
        if resp.status_code != 200:
            return JSONResponse(status_code=resp.status_code,
                                content={"ok": False, "detail": resp.text})

        data = resp.json()
        token = data.get("token") or data.get("access_token")
        if not token:
            return JSONResponse(status_code=500,
                                content={"ok": False, "detail": "Central 未回傳 token"})

        # 寫回 .env
        _write_env_key("CENTRAL_OWNER_TOKEN", token)
        # 更新當前 process 環境（讓後續 status/gpts 即時生效）
        os.environ["CENTRAL_OWNER_TOKEN"] = token

        exp = _decode_jwt_exp(token)
        days = max(0, int((exp - time.time()) / 86400)) if exp else None
        return {"ok": True, "token_days_remaining": days}
    except Exception as e:
        return JSONResponse(status_code=503, content={"ok": False, "detail": str(e)})
