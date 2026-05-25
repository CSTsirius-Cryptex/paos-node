"""
panel.py — PAOS Node 控制台 API（CP-1 ~ CP-3）
所有 /panel/api/* 路由只接受本機連線（見 main.py middleware）。
"""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.config import CENTRAL_URL, VAULT_PATH, NODE_PUBLIC_URL, NODE_PORT

router = APIRouter(prefix="/panel/api", tags=["panel"])

# ── 路徑常數 ──────────────────────────────────────────────────────
ENV_FILE        = Path(__file__).parent.parent.parent / ".env"
CP_CONFIG_FILE  = Path(__file__).parent.parent.parent / "cp_config.json"
LOG_FILE        = Path(__file__).parent.parent.parent / "logs" / "node.log"
TASK_NAME_NODE  = "PAOS-Node"

# ── Python / Node 路徑（直接啟動，繞過 schtasks PATH 問題）──────────
_NODE_DIR = Path(__file__).parent.parent.parent          # D:\Claude\paos-node
_START_PY = _NODE_DIR / "start.py"
_py_dir   = Path(sys.executable).parent
_PYTHONW  = _py_dir / "pythonw.exe"
if not _PYTHONW.exists():                                # fallback
    _PYTHONW = Path(sys.executable)

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

def _schtasks_output(*args, timeout: int = 5) -> str:
    """執行 schtasks 並回傳輸出（自動處理繁中 Windows CP950/MBCS 編碼）。"""
    result = subprocess.run(
        ["schtasks"] + list(args),
        capture_output=True, timeout=timeout
    )
    raw = (result.stdout or b"") + (result.stderr or b"")
    try:
        return raw.decode("mbcs", errors="replace")
    except Exception:
        return raw.decode("utf-8", errors="replace")


def _is_task_registered(task_name: str) -> bool:
    """WO-02：查詢排程工作是否已登錄且未停用（不管目前是否在跑）。"""
    try:
        output = _schtasks_output("/Query", "/TN", task_name, "/FO", "LIST")
        if not output.strip():
            return False
        # 已停用的排程工作回傳 disabled / 已停用
        return not any(kw in output.lower() for kw in ["disabled", "已停用"])
    except Exception:
        return False


def _is_port_listening(port: int) -> bool:
    """WO-02：用 socket 偵測本機 port 是否有人在監聽。"""
    import socket as _sock
    try:
        with _sock.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _set_scheduler_enabled(task_name: str, enabled: bool) -> bool:
    """啟用或停用 Windows 排程工作。"""
    try:
        action = "/Enable" if enabled else "/Disable"
        result = subprocess.run(
            ["schtasks", "/Change", "/TN", task_name, action],
            capture_output=True, timeout=5
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

    # 1. 排程工作（WO-02：只看是否已登錄啟用，不看是否正在跑）
    task_ok = _is_task_registered(TASK_NAME_NODE)
    result["scheduler"] = {"status": "ok" if task_ok else "error"}

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

    # 6. 已向 Central 登錄
    # register_node() 在每次 Node 啟動時自動執行，用本機 JWT 解碼判斷：
    # Token 未過期 + tunnel_url 已設定 = 視為已成功登錄
    if owner_token and tunnel_url:
        exp = _decode_jwt_exp(owner_token)
        if exp and exp > time.time():
            result["registered"] = {"status": "ok", "node_url": tunnel_url}
        else:
            result["registered"] = {"status": "error", "node_url": "",
                                     "detail": "Token 已過期，請至設定 > 帳號 > 重新登入"}
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

    # Step 1：排程工作（WO-02：判斷是否已登錄啟用，不中斷後續診斷）
    sched_ok = _is_task_registered(TASK_NAME_NODE)
    add(1, "排程工作", sched_ok,
        detail="已登錄並啟用（開機自動啟動）" if sched_ok
               else "排程工作未登錄或已停用，開機不會自動啟動（不影響手動執行）")
    prev_ok = True  # 排程工作狀態不中斷後續診斷

    # Step 2：Node /health
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

    # Step 6：Central 已登錄（本機 JWT 解碼 + tunnel URL 已設定）
    if owner_token and tunnel_url:
        exp = _decode_jwt_exp(owner_token)
        if exp and exp > time.time():
            add(6, "Central 已登錄", True, detail=f"Token 有效，Node URL：{tunnel_url}")
        else:
            add(6, "Central 已登錄", False, detail="Token 已過期，請至設定 > 帳號 > 重新登入")
    else:
        add(6, "Central 已登錄", False,
            detail="CENTRAL_OWNER_TOKEN 未設定或 Tunnel URL 未取得")

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

    # auto_start：排程工作是否已登錄啟用
    auto_start = _is_task_registered(TASK_NAME_NODE)

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


# ── CP-3b：POST /panel/api/settings/pick-vault ────────────────────

def _open_folder_dialog(initial_path: str = "") -> str:
    """
    使用 tkinter.filedialog 開啟原生資料夾選擇視窗。
    以 attributes('-topmost', True) 確保對話框浮在 pywebview 視窗前面。
    tkinter 是 Python 內建模組，不需要 PowerShell。
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()                                    # 隱藏 tkinter 主視窗
        root.attributes("-topmost", True)                  # 對話框置頂
        root.update()
        start_dir = initial_path if initial_path and Path(initial_path).exists() else None
        path = filedialog.askdirectory(
            parent=root,
            title="選擇 Obsidian Vault 資料夾（VAULT_PATH）",
            initialdir=start_dir,
            mustexist=False,
        )
        root.destroy()
        return path or ""
    except Exception:
        return ""

@router.post("/settings/pick-vault")
async def pick_vault_folder():
    """開啟原生 Windows 資料夾選擇對話框，回傳使用者選擇的路徑。"""
    import asyncio
    env = _read_env()
    initial = env.get("VAULT_PATH", "")
    loop = asyncio.get_running_loop()
    path = await loop.run_in_executor(None, _open_folder_dialog, initial)
    if not path:
        return {"ok": False, "path": None}
    return {"ok": True, "path": path}


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


# ── Node 控制 endpoints ───────────────────────────────────────────

def _start_node():
    """直接用 pythonw 啟動 start.py（不等待結果）。"""
    subprocess.Popen(
        [str(_PYTHONW), str(_START_PY)],
        cwd=str(_NODE_DIR),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _detached_restart(pre_delay_ms: int = 2000, also_kill_port: bool = True):
    """
    在完全獨立的 PowerShell 進程中執行「殺舊 Node → 重新啟動」流程。

    關鍵設計：
    - 不能在 uvicorn 的 daemon thread 裡做 taskkill /PID（殺自己的進程會連 thread 一起死）
    - PowerShell 進程獨立於 uvicorn，即使 uvicorn 被殺掉，它仍會繼續跑完重啟流程
    - pre_delay_ms：等 HTTP response 發出後再動手（避免 browser 收到 connection reset）
    """
    # 路徑中若含單引號需跳脫
    pythonw  = str(_PYTHONW).replace("'", "''")
    start_py = str(_START_PY).replace("'", "''")
    node_dir = str(_NODE_DIR).replace("'", "''")
    port     = NODE_PORT

    kill_port_block = (
        # 找出監聽 port 的所有 PID 並殺掉
        f"$lines = netstat -ano | Select-String ':{port}\\s.*LISTENING'; "
        f"foreach ($l in $lines) {{"
        f"  $pid = ($l.ToString() -split '\\s+')[-1].Trim(); "
        f"  if ($pid -match '^[1-9][0-9]*$') {{ taskkill /F /PID $pid 2>$null }} "
        f"}}; "
    ) if also_kill_port else ""

    ps_script = (
        f"Start-Sleep -Milliseconds {pre_delay_ms}; "
        # Step 1: 殺 cloudflared
        "try { taskkill /F /IM cloudflared.exe 2>$null } catch {}; "
        # Step 2: 殺監聽 port 的進程（通常是 uvicorn/start.py）
        + kill_port_block +
        # Step 3: 等 port 釋放
        "Start-Sleep -Seconds 3; "
        # Step 4: 重啟 Node
        f"Start-Process -FilePath '{pythonw}' "
        f"-ArgumentList '\"{start_py}\"' "
        f"-WorkingDirectory '{node_dir}' "
        f"-WindowStyle Hidden"
    )

    subprocess.Popen(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


@router.post("/node/start")
async def node_start():
    """直接用 pythonw 啟動 start.py（繞過 schtasks PATH 問題）。"""
    try:
        _start_node()
        return {"ok": True, "note": "已傳送啟動指令，約 20 秒後生效"}
    except Exception as e:
        return {"ok": False, "note": str(e)}


@router.post("/node/restart")
async def node_restart():
    """
    正常重啟：先殺 cloudflared，再殺 port 3100 的進程，然後重新啟動。
    使用 detached PowerShell 確保即使 uvicorn 被殺掉，重啟邏輯仍會繼續執行。
    """
    _detached_restart(pre_delay_ms=1500, also_kill_port=True)
    return {"ok": True, "note": "重啟指令已送出，約 30 秒後生效"}


@router.post("/node/repair")
async def node_repair():
    """
    強制修復：與 restart 相同流程但等待時間更短，適合 Node 無回應時使用。
    使用 detached PowerShell 確保即使 uvicorn 被殺掉，重啟邏輯仍會繼續執行。
    """
    _detached_restart(pre_delay_ms=1000, also_kill_port=True)
    return {"ok": True, "note": "強制修復指令已送出，約 30 秒後生效"}


@router.post("/node/renew-tunnel")
async def node_renew_tunnel():
    """
    重新建立 Tunnel：殺掉 cloudflared + 整個 Node，重啟後 start.py 會自動
    取得新的 Quick Tunnel URL 並重新向 Central 登錄。
    與 restart 流程相同，但語意上強調「取得新 URL」。
    """
    _detached_restart(pre_delay_ms=1500, also_kill_port=True)
    return {"ok": True, "note": "Tunnel 重建指令已送出，約 30 秒後取得新 URL"}


# ── CP-3：POST /panel/api/logout ─────────────────────────────────

@router.post("/logout")
async def logout():
    """
    登出：清除 .env 中的 CENTRAL_OWNER_TOKEN，並從當前 process 環境移除。
    下次啟動 Node 時，lifespan 的 register_node() 將因無 token 而無法向 Central 登錄。
    """
    _write_env_key("CENTRAL_OWNER_TOKEN", "")
    os.environ.pop("CENTRAL_OWNER_TOKEN", None)
    return {"ok": True}


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
