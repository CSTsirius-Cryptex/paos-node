"""
installer_logic.py — PAOS Node 安裝精靈後端邏輯
I-2：環境偵測 / I-3：Vault 設定 / I-4：OTP 登入 / I-5：Tunnel + 登錄 / I-6：排程 + 捷徑
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

CENTRAL_URL = "https://paos-central-production.up.railway.app"
NODE_PORT   = 3100
CLOUDFLARED_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

# 安裝目標目錄（installer.py 同層，即 paos-node 根目錄）
INSTALL_DIR = Path(__file__).parent.parent.resolve()
ENV_FILE    = INSTALL_DIR / ".env"


# ── I-2：環境偵測 ──────────────────────────────────────────────────

def check_environment() -> dict:
    """偵測 Python、cloudflared、port 3100 可用性。"""
    result = {}

    # Python（一定有，我們在跑）
    result["python"] = {
        "ok": True,
        "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    }

    # cloudflared
    try:
        r = subprocess.run(
            ["cloudflared", "--version"],
            capture_output=True, text=True, timeout=5
        )
        ver = r.stdout.strip() or r.stderr.strip()
        result["cloudflared"] = {"ok": r.returncode == 0, "version": ver}
    except FileNotFoundError:
        result["cloudflared"] = {"ok": False, "version": "", "note": "未安裝，需手動安裝後重試"}
    except Exception as e:
        result["cloudflared"] = {"ok": False, "version": "", "note": str(e)}

    # Port 3100
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", NODE_PORT))
        s.close()
        result["port"] = {"ok": True, "note": f"Port {NODE_PORT} 可用"}
    except OSError:
        result["port"] = {"ok": False, "note": f"Port {NODE_PORT} 已被佔用，請確認沒有其他程式在使用"}

    # 安裝目錄可寫
    try:
        ok = os.access(INSTALL_DIR, os.W_OK)
        result["install_dir"] = {"ok": ok, "path": str(INSTALL_DIR)}
    except Exception as e:
        result["install_dir"] = {"ok": False, "path": str(INSTALL_DIR), "note": str(e)}

    result["all_ok"] = all(v["ok"] for v in result.values() if isinstance(v, dict) and "ok" in v)
    return result


# ── I-3：Vault 路徑 ────────────────────────────────────────────────

def validate_vault_path(path: str) -> dict:
    """驗證 Vault 路徑是否存在且可讀寫。"""
    try:
        p = Path(path)
        if not p.exists():
            return {"ok": False, "note": "路徑不存在"}
        if not p.is_dir():
            return {"ok": False, "note": "路徑不是資料夾"}
        if not os.access(p, os.R_OK | os.W_OK):
            return {"ok": False, "note": "無讀寫權限"}
        return {"ok": True, "path": str(p)}
    except Exception as e:
        return {"ok": False, "note": str(e)}


# ── I-4：OTP 登入 ──────────────────────────────────────────────────

def request_otp(email: str) -> dict:
    try:
        r = httpx.post(
            f"{CENTRAL_URL}/auth/request-otp",
            json={"email": email}, timeout=10
        )
        if r.status_code == 200:
            return {"ok": True}
        return {"ok": False, "note": f"Central 回應 {r.status_code}：{r.text[:100]}"}
    except Exception as e:
        return {"ok": False, "note": f"連線失敗：{e}"}


def verify_otp(email: str, otp: str) -> dict:
    try:
        r = httpx.post(
            f"{CENTRAL_URL}/auth/verify-otp",
            json={"email": email, "otp": otp}, timeout=10
        )
        if r.status_code != 200:
            return {"ok": False, "note": f"驗證失敗（{r.status_code}）"}
        data = r.json()
        token = data.get("token") or data.get("access_token")
        if not token:
            return {"ok": False, "note": "Central 未回傳 token"}

        # 取 GPT 清單預覽
        gpt_count = 0
        try:
            gr = httpx.get(
                f"{CENTRAL_URL}/portal/account/me/gpts",
                headers={"Authorization": f"Bearer {token}"}, timeout=10
            )
            if gr.status_code == 200:
                gpt_count = len(gr.json())
        except Exception:
            pass

        return {"ok": True, "token": token, "email": email, "gpt_count": gpt_count}
    except Exception as e:
        return {"ok": False, "note": f"連線失敗：{e}"}


# ── I-5：cloudflared Tunnel + 向 Central 登錄 ──────────────────────

_tunnel_proc = None
_tunnel_url  = None

def start_tunnel_and_register(token: str) -> dict:
    """啟動 cloudflared quick tunnel，取得 URL 後向 Central 登錄。"""
    global _tunnel_proc, _tunnel_url

    url  = None
    proc = None
    try:
        proc = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{NODE_PORT}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        # 從 stderr 掃 URL
        deadline = time.time() + 60
        url_found = threading.Event()

        def read_stderr():
            nonlocal url
            for raw in proc.stderr:
                line = raw.decode("utf-8", errors="replace").rstrip()
                m = CLOUDFLARED_PATTERN.search(line)
                if m and not url:
                    url = m.group(0)
                    url_found.set()

        threading.Thread(target=read_stderr, daemon=True).start()
        url_found.wait(timeout=60)

        if not url:
            proc.terminate()
            return {"ok": False, "note": "等待 cloudflared URL 超時，請確認 cloudflared 已安裝且網路正常"}

        _tunnel_proc = proc
        _tunnel_url  = url

        # 向 Central 登錄
        r = httpx.put(
            f"{CENTRAL_URL}/me/node",
            json={"node_url": url},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        if r.status_code not in (200, 201, 204):
            return {"ok": False, "url": url, "note": f"Tunnel 已建立但登錄 Central 失敗（{r.status_code}）"}

        return {"ok": True, "url": url}

    except Exception as e:
        if proc:
            proc.terminate()
        return {"ok": False, "note": str(e)}


# ── I-6：寫 .env + 安裝排程工作 + 建立捷徑 ────────────────────────

def write_env(vault_path: str, token: str, email: str, init_agents: str = "") -> dict:
    """將設定寫入 .env 檔案。"""
    try:
        env_content = (
            f"CENTRAL_URL={CENTRAL_URL}\n"
            f"NODE_PORT={NODE_PORT}\n"
            f"VAULT_PATH={vault_path}\n"
            f"CENTRAL_OWNER_TOKEN={token}\n"
            f"OWNER_EMAIL={email}\n"
            f"NODE_PUBLIC_URL={_tunnel_url or ''}\n"
            f"# 逗號分隔：Node 啟動時自動初始化這些 agent 的 Vault 資料夾結構\n"
            f"INIT_AGENTS={init_agents}\n"
        )
        ENV_FILE.write_text(env_content, encoding="utf-8")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "note": str(e)}


def _make_task_xml(description: str, command: str, arguments: str,
                   working_dir: str, delay: str = "PT30S") -> str:
    """動態產生 Task Scheduler XML（使用完整 Python 路徑，避免系統 PATH 問題）。"""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{description}</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>{delay}</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{working_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""


def install_scheduled_tasks() -> dict:
    """安裝 PAOS-Node 和 PAOS-Node-控制台 排程工作（動態產生 XML，使用完整 Python 路徑）。"""
    import tempfile

    # 用目前執行中的 Python 路徑推導 pythonw.exe
    py_dir   = Path(sys.executable).parent
    pythonw  = py_dir / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable)  # fallback

    tasks_def = [
        (
            "PAOS-Node",
            "PAOS Node（cloudflared tunnel + FastAPI server）",
            str(pythonw),
            f'"{INSTALL_DIR / "start.py"}"',
            str(INSTALL_DIR),
            "PT30S",
        ),
        (
            "PAOS-Node-控制台",
            "PAOS Node 控制台（pystray + pywebview）",
            str(pythonw),
            f'"{INSTALL_DIR / "panel_app.py"}"',
            str(INSTALL_DIR),
            "PT01M00S",
        ),
    ]

    results = {}
    for task_name, desc, cmd, args, wdir, delay in tasks_def:
        try:
            xml_content = _make_task_xml(desc, cmd, args, wdir, delay)
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".xml", encoding="utf-16", delete=False
            ) as f:
                f.write(xml_content)
                tmp_path = f.name

            r = subprocess.run(
                ["schtasks", "/Create", "/TN", task_name, "/XML", tmp_path, "/F"],
                capture_output=True, timeout=15
            )
            ok = r.returncode == 0
            out = (r.stdout + r.stderr).decode("mbcs", errors="replace")
            results[task_name] = {"ok": ok, "note": out.strip()[:120]}
        except Exception as e:
            results[task_name] = {"ok": False, "note": str(e)}
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    all_ok = all(v["ok"] for v in results.values())
    return {"ok": all_ok, "tasks": results}


def create_desktop_shortcut() -> dict:
    """在桌面建立 PAOS Node 控制台捷徑。"""
    try:
        vbs_path = INSTALL_DIR / "launch-panel.vbs"
        desktop  = Path(os.environ.get("USERPROFILE", "~")) / "Desktop"
        lnk_path = desktop / "PAOS Node 控制台.lnk"

        ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{lnk_path}')
$sc.TargetPath  = 'wscript.exe'
$sc.Arguments   = '"{vbs_path}"'
$sc.IconLocation = 'shell32.dll,25'
$sc.Description  = '開啟 PAOS Node 控制台'
$sc.Save()
"""
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, timeout=15
        )
        return {"ok": r.returncode == 0}
    except Exception as e:
        return {"ok": False, "note": str(e)}


def run_full_setup(vault_path: str, token: str, email: str) -> dict:
    """I-6 完整安裝流程：寫 .env → 排程工作 → 捷徑。"""
    steps = {}

    steps["env"]      = write_env(vault_path, token, email)
    steps["tasks"]    = install_scheduled_tasks()
    steps["shortcut"] = create_desktop_shortcut()

    all_ok = all(v["ok"] for v in steps.values())
    return {"ok": all_ok, "steps": steps}
