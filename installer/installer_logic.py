"""
installer_logic.py — PAOS Node 安裝精靈後端邏輯
v3：自包含架構（INSTALL_DIR 使用者可選、打包 node 原始碼、venv 隔離、Obsidian 強制最新）
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

CENTRAL_URL = "https://paos-central-production.up.railway.app"
NODE_PORT   = 3100
CLOUDFLARED_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

# ── INSTALL_DIR（使用者在 Step 2 選定，預設 %LOCALAPPDATA%\PAOS-Node\）──────
# frozen 模式：預設 %LOCALAPPDATA%\PAOS-Node\（不再依賴 exe 位置）
# 開發模式：上層目錄（paos-node 根目錄），方便直接測試
if getattr(sys, "frozen", False):
    _DEFAULT_INSTALL = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PAOS-Node"
else:
    _DEFAULT_INSTALL = Path(__file__).parent.parent.resolve()

INSTALL_DIR: Path = _DEFAULT_INSTALL
ENV_FILE:    Path = INSTALL_DIR / ".env"


def get_default_install_dir() -> str:
    return str(_DEFAULT_INSTALL)


def set_install_dir(path: str) -> dict:
    """Step 2 使用者確認後呼叫，之後所有操作都用此路徑。"""
    global INSTALL_DIR, ENV_FILE
    INSTALL_DIR = Path(path).resolve()
    ENV_FILE    = INSTALL_DIR / ".env"
    return {"ok": True, "path": str(INSTALL_DIR)}


def validate_install_dir(path: str) -> dict:
    try:
        p = Path(path).resolve()
        p.mkdir(parents=True, exist_ok=True)
        if not os.access(p, os.W_OK):
            return {"ok": False, "note": "目錄無寫入權限"}
        return {"ok": True, "path": str(p)}
    except Exception as e:
        return {"ok": False, "note": str(e)}


# ── GitHub Releases API 輔助（cloudflared / Obsidian 共用）──────────────────

def _get_latest_github_release(owner: str, repo: str) -> dict:
    """查詢 GitHub Releases API，回傳最新版本號與資產清單。"""
    try:
        r = httpx.get(
            f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
            timeout=10,
            headers={"Accept": "application/vnd.github.v3+json"},
            follow_redirects=True,
        )
        if r.status_code != 200:
            return {"ok": False, "note": f"GitHub API {r.status_code}"}
        data = r.json()
        return {
            "ok": True,
            "version": data.get("tag_name", "").lstrip("v"),
            "tag": data.get("tag_name", ""),
            "assets": [
                {"name": a["name"], "url": a["browser_download_url"]}
                for a in data.get("assets", [])
            ],
        }
    except Exception as e:
        return {"ok": False, "note": str(e)}


def _download_with_progress(url: str, dest: Path, progress_cb, pct_start: int, pct_end: int):
    """下載 url 到 dest，透過 progress_cb 回報進度（pct_start..pct_end）。"""
    import urllib.request
    span = pct_end - pct_start

    def _hook(b, bs, ts):
        if ts > 0 and progress_cb:
            pct = min(int(b * bs / ts * span) + pct_start, pct_end)
            progress_cb(pct, f"下載中… {b * bs / 1_048_576:.1f} MB")

    urllib.request.urlretrieve(url, dest, reporthook=_hook)


# ── I-2：環境偵測 ──────────────────────────────────────────────────────────

def check_environment() -> dict:
    """偵測 Python / cloudflared / Obsidian / Port 3100。"""
    result = {}

    # ── Python ──
    if getattr(sys, "frozen", False):
        found = shutil.which("pythonw") or shutil.which("python") or shutil.which("python3")
        if found:
            try:
                r = subprocess.run(
                    [found, "--version"], capture_output=True, text=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                ver = (r.stdout.strip() or r.stderr.strip()).replace("Python ", "")
                result["python"] = {"ok": True, "version": ver}
            except Exception as e:
                result["python"] = {"ok": False, "note": f"執行失敗：{e}"}
        else:
            result["python"] = {"ok": False, "note": "未偵測到 Python，請安裝 3.10 以上版本"}
    else:
        result["python"] = {
            "ok": True,
            "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        }

    # ── cloudflared ──
    try:
        r = subprocess.run(
            ["cloudflared", "--version"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        ver = r.stdout.strip() or r.stderr.strip()
        result["cloudflared"] = {"ok": r.returncode == 0, "version": ver}
    except FileNotFoundError:
        result["cloudflared"] = {"ok": False, "version": "", "note": "未安裝"}
    except Exception as e:
        result["cloudflared"] = {"ok": False, "version": "", "note": str(e)}

    # ── Obsidian：必要，且必須是最新版 ──
    try:
        installed = _get_obsidian_installed_version()
        latest_info = _get_latest_github_release("obsidianmd", "obsidian-releases")
        latest = latest_info.get("version") if latest_info["ok"] else None

        if not installed:
            result["obsidian"] = {
                "ok": False, "installed": None, "latest": latest,
                "note": "尚未安裝 Obsidian",
            }
        elif latest and installed != latest:
            result["obsidian"] = {
                "ok": False, "installed": installed, "latest": latest,
                "note": f"版本過舊（{installed}），需更新至 {latest}",
            }
        else:
            result["obsidian"] = {
                "ok": True, "installed": installed, "latest": latest,
                "note": f"Obsidian {installed}（最新）",
            }
    except Exception as e:
        result["obsidian"] = {"ok": False, "note": str(e)}

    # ── Port 3100 ──
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", NODE_PORT))
        s.close()
        result["port"] = {"ok": True, "note": f"Port {NODE_PORT} 可用"}
    except OSError:
        result["port"] = {"ok": False, "note": f"Port {NODE_PORT} 已被佔用"}

    result["all_ok"] = all(
        v["ok"] for v in result.values() if isinstance(v, dict) and "ok" in v
    )
    return result


# ── Obsidian 偵測與安裝 ───────────────────────────────────────────────────

def _get_obsidian_installed_version() -> str | None:
    """從 Windows 登錄檔取得已安裝的 Obsidian 版本號。"""
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for sub in (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Obsidian",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Obsidian",
            ):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        v, _ = winreg.QueryValueEx(k, "DisplayVersion")
                        return str(v)
                except FileNotFoundError:
                    continue
    except Exception:
        pass
    return None


def download_obsidian(progress_cb=None) -> dict:
    """從 GitHub Releases 下載並安裝最新版 Obsidian（NSIS 靜默安裝）。"""
    if progress_cb:
        progress_cb(5, "查詢 Obsidian 最新版本…")

    release = _get_latest_github_release("obsidianmd", "obsidian-releases")
    if not release["ok"]:
        return {"ok": False, "note": f"無法取得版本資訊：{release['note']}"}

    # 找 Windows .exe 安裝檔
    win_asset = next(
        (a for a in release["assets"]
         if a["name"].lower().endswith(".exe") and "arm" not in a["name"].lower()),
        None,
    )
    if not win_asset:
        return {"ok": False, "note": "找不到 Windows 安裝檔"}

    if progress_cb:
        progress_cb(10, f"下載 Obsidian {release['version']}…")

    tmp = Path(tempfile.mktemp(suffix=".exe"))
    try:
        _download_with_progress(win_asset["url"], tmp, progress_cb, 10, 85)

        if progress_cb:
            progress_cb(87, "安裝 Obsidian（靜默模式）…")

        r = subprocess.run([str(tmp), "/S"], capture_output=True, timeout=180)
        if r.returncode != 0:
            return {"ok": False, "note": f"安裝程式回傳 {r.returncode}"}

        if progress_cb:
            progress_cb(100, f"Obsidian {release['version']} 安裝完成！")
        return {"ok": True, "version": release["version"]}
    except Exception as e:
        return {"ok": False, "note": str(e)}
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


# ── Python 自動安裝（winget）──────────────────────────────────────────────

def download_python(progress_cb=None) -> dict:
    """透過 winget 靜默安裝最新 Python 3.x。"""
    wg = shutil.which("winget")
    if not wg:
        return {"ok": False, "note": "系統不支援 winget（需 Windows 10 1809+），請手動安裝 Python"}

    if progress_cb:
        progress_cb(5, "透過 winget 安裝 Python…（約 1–3 分鐘）")

    try:
        r = subprocess.run(
            [wg, "install", "Python.Python.3",
             "--silent", "--accept-package-agreements", "--accept-source-agreements"],
            capture_output=True, timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = (r.stdout + r.stderr).decode("mbcs", errors="replace").strip()
        if r.returncode not in (0, -1978335189):
            return {"ok": False, "note": f"winget 回傳 {r.returncode}：{out[:200]}"}

        if progress_cb:
            progress_cb(95, "重新整理 PATH…")
        _refresh_path_from_registry()

        if progress_cb:
            progress_cb(100, "Python 安裝完成！")
        return {"ok": True}
    except subprocess.TimeoutExpired:
        return {"ok": False, "note": "安裝逾時（>5 分鐘），請手動安裝 Python"}
    except Exception as e:
        return {"ok": False, "note": str(e)}


def _refresh_path_from_registry():
    """把系統 PATH + 使用者 PATH 從登錄檔重新載入到目前進程。"""
    try:
        import winreg

        def _reg(hive, sub):
            try:
                with winreg.OpenKey(hive, sub) as k:
                    v, _ = winreg.QueryValueEx(k, "Path")
                    return os.path.expandvars(v)
            except Exception:
                return ""

        sys_p = _reg(winreg.HKEY_LOCAL_MACHINE,
                     r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")
        usr_p = _reg(winreg.HKEY_CURRENT_USER, "Environment")
        os.environ["PATH"] = sys_p + ";" + usr_p + ";" + os.environ.get("PATH", "")
    except Exception:
        pass


# ── cloudflared 自動安裝（GitHub Releases 最新版）────────────────────────

def _add_to_user_path(new_dir: str) -> dict:
    try:
        import winreg, ctypes
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment",
                            0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                cur, _ = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                cur = ""
            dirs = [d for d in cur.split(";") if d.strip()]
            nd = new_dir.rstrip("\\")
            if nd not in [d.rstrip("\\") for d in dirs]:
                dirs.append(nd)
                winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, ";".join(dirs))
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 2, 5000, None)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "note": str(e)}


def download_cloudflared(progress_cb=None) -> dict:
    """從 GitHub Releases 下載最新版 cloudflared 到 %LOCALAPPDATA%\\cloudflared\\。"""
    if progress_cb:
        progress_cb(5, "查詢 cloudflared 最新版本…")

    release = _get_latest_github_release("cloudflare", "cloudflared")
    if not release["ok"]:
        return {"ok": False, "note": f"無法取得版本資訊：{release['note']}"}

    asset = next(
        (a for a in release["assets"]
         if a["name"].lower() == "cloudflared-windows-amd64.exe"),
        None,
    )
    if not asset:
        return {"ok": False, "note": "找不到 cloudflared-windows-amd64.exe"}

    if progress_cb:
        progress_cb(10, f"下載 cloudflared {release['version']}…")

    cf_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "cloudflared"
    cf_dir.mkdir(parents=True, exist_ok=True)
    target = cf_dir / "cloudflared.exe"

    try:
        _download_with_progress(asset["url"], target, progress_cb, 10, 88)
    except Exception as e:
        return {"ok": False, "note": f"下載失敗：{e}"}

    if progress_cb:
        progress_cb(92, "寫入使用者 PATH…")
    _add_to_user_path(str(cf_dir))
    os.environ["PATH"] = str(cf_dir) + ";" + os.environ.get("PATH", "")

    if progress_cb:
        progress_cb(100, f"cloudflared {release['version']} 安裝完成！")
    return {"ok": True, "version": release["version"], "path": str(target)}


# ── I-3：Vault 路徑 ──────────────────────────────────────────────────────

def validate_vault_path(path: str) -> dict:
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


# ── I-4：OTP 登入 ──────────────────────────────────────────────────────────

def request_otp(email: str, name: str = "") -> dict:
    payload: dict = {"email": email}
    if name:
        payload["name"] = name
    try:
        r = httpx.post(f"{CENTRAL_URL}/auth/request-otp", json=payload, timeout=10)
        if r.status_code == 200:
            return {"ok": True}
        return {"ok": False, "note": f"Central 回應 {r.status_code}：{r.text[:100]}"}
    except Exception as e:
        return {"ok": False, "note": f"連線失敗：{e}"}


def verify_otp(email: str, otp: str) -> dict:
    try:
        r = httpx.post(
            f"{CENTRAL_URL}/auth/verify-otp",
            json={"email": email, "otp": otp}, timeout=10,
        )
        if r.status_code != 200:
            return {"ok": False, "note": f"驗證失敗（{r.status_code}）"}
        data = r.json()
        token = data.get("token") or data.get("access_token")
        if not token:
            return {"ok": False, "note": "Central 未回傳 token"}

        # 取完整 GPT 清單（名稱 + 數量）
        gpt_names: list[str] = []
        try:
            gr = httpx.get(
                f"{CENTRAL_URL}/portal/account/me/gpts",
                headers={"Authorization": f"Bearer {token}"}, timeout=10,
            )
            if gr.status_code == 200:
                gpts = gr.json()
                gpt_names = [
                    g.get("name") or g.get("id") or f"GPT-{i}"
                    for i, g in enumerate(gpts)
                ]
        except Exception:
            pass

        return {
            "ok": True,
            "token": token,
            "email": email,
            "gpt_count": len(gpt_names),
            "gpt_names": gpt_names,
        }
    except Exception as e:
        return {"ok": False, "note": f"連線失敗：{e}"}


# ── I-5：cloudflared Tunnel + 向 Central 登錄 ────────────────────────────

_tunnel_proc = None
_tunnel_url  = None


def start_tunnel_and_register(token: str) -> dict:
    global _tunnel_proc, _tunnel_url
    url = None
    proc = None
    try:
        proc = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{NODE_PORT}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
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
            return {"ok": False, "note": "等待 cloudflared URL 超時"}

        _tunnel_proc = proc
        _tunnel_url  = url

        r = httpx.put(
            f"{CENTRAL_URL}/me/node",
            json={"node_url": url},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code not in (200, 201, 204):
            return {"ok": False, "url": url, "note": f"Tunnel 已建立但登錄 Central 失敗（{r.status_code}）"}

        return {"ok": True, "url": url}
    except Exception as e:
        if proc:
            proc.terminate()
        return {"ok": False, "note": str(e)}


# ── I-6：部署 Node 檔 + venv + Vault 初始化 + 排程 + 捷徑 ───────────────

def deploy_node_files() -> dict:
    """
    把 exe 內打包的 node/ 資源解壓到 INSTALL_DIR。
    開發模式直接跳過（原始碼已在正確位置）。
    """
    if not getattr(sys, "frozen", False):
        return {"ok": True, "note": "開發模式，跳過部署"}

    node_src = Path(sys._MEIPASS) / "node"  # type: ignore[attr-defined]
    if not node_src.exists():
        return {"ok": False, "note": f"找不到打包資源 {node_src}"}

    try:
        INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        for item in node_src.rglob("*"):
            # 跳過快取與編譯產物
            if "__pycache__" in item.parts:
                continue
            if item.suffix == ".pyc":
                continue
            rel  = item.relative_to(node_src)
            dest = INSTALL_DIR / rel
            if item.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "note": str(e)}


def install_requirements_venv(progress_cb=None) -> dict:
    """在 INSTALL_DIR/venv/ 建立 Python venv 並安裝套件。"""
    venv_dir = INSTALL_DIR / "venv"
    req_file = INSTALL_DIR / "requirements.txt"

    if not req_file.exists():
        return {"ok": False, "note": f"找不到 {req_file}，請先完成 Node 檔案部署"}

    found = shutil.which("python") or shutil.which("python3")
    if not found:
        return {"ok": False, "note": "找不到 Python，請先安裝"}

    if progress_cb:
        progress_cb(5, "建立 Python 虛擬環境（venv）…")

    try:
        r = subprocess.run(
            [found, "-m", "venv", str(venv_dir)],
            capture_output=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            out = (r.stdout + r.stderr).decode("mbcs", errors="replace")
            return {"ok": False, "note": f"venv 建立失敗：{out[:200]}"}
    except Exception as e:
        return {"ok": False, "note": str(e)}

    if progress_cb:
        progress_cb(20, "安裝 Python 套件（約 2–4 分鐘）…")

    pip = venv_dir / "Scripts" / "pip.exe"
    try:
        r = subprocess.run(
            [str(pip), "install", "-r", str(req_file), "--quiet"],
            capture_output=True, timeout=600,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = (r.stdout + r.stderr).decode("mbcs", errors="replace")
        if r.returncode != 0:
            return {"ok": False, "note": f"套件安裝失敗：{out[:300]}"}
    except Exception as e:
        return {"ok": False, "note": str(e)}

    if progress_cb:
        progress_cb(100, "套件安裝完成！")
    return {"ok": True, "venv": str(venv_dir)}


# ── Agent Vault 初始化（同步 src/routes/setup.py 邏輯）──────────────────

_AGENT_FOLDERS = [
    "agents/{a}/memory/work-log",
    "agents/{a}/memory/projects",
    "agents/{a}/memory/insights",
]
_SHARED_FOLDERS = ["shared/projects", "shared/knowledge", "shared/contacts"]

_PROFILE_TMPL = """\
---
agent: {a}
initialized: {date}
status: fresh
---

# {a} 的記憶空間

這個記憶空間剛剛建立，尚無歷史記憶。
第一次對話完成後，`status` 會自動更新為 `active`。
"""

_INDEX_TMPL = """\
# {a} 知識索引
最後更新：{date}

## 專案

## 洞察

## 共用知識（我貢獻的）

## 重要聯絡人
"""

_LOG_TMPL = """\
# {a} 操作日誌

<!-- append-only，永不刪除條目 -->
<!-- 格式：## [YYYY-MM-DD] {操作類型} | {說明} [[相關頁面路徑]] -->

"""


def initialize_agent_vaults(vault_path: str, gpt_names: list) -> dict:
    """為每個 GPT 助理在 Vault 建立標準記憶資料夾結構。"""
    from datetime import datetime, timezone
    vault    = Path(vault_path).resolve()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    created, errors = [], []

    # 共用資料夾（所有 agent 共用）
    for rel in _SHARED_FOLDERS:
        try:
            (vault / rel).mkdir(parents=True, exist_ok=True)
            if rel not in created:
                created.append(rel)
        except Exception as e:
            errors.append(f"{rel}: {e}")

    for name in gpt_names:
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()
        if not safe:
            continue
        try:
            for tpl in _AGENT_FOLDERS:
                p = vault / tpl.format(a=safe)
                p.mkdir(parents=True, exist_ok=True)
                created.append(str(p.relative_to(vault)))

            def _wif(rel, content):
                p = vault / rel
                if not p.exists():
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(content, encoding="utf-8")

            _wif(f"agents/{safe}/profile.md",
                 _PROFILE_TMPL.format(a=safe, date=date_str))
            _wif(f"agents/{safe}/memory/index.md",
                 _INDEX_TMPL.format(a=safe, date=date_str))
            _wif(f"agents/{safe}/memory/work-log/work-log.md",
                 _LOG_TMPL.format(a=safe))
        except Exception as e:
            errors.append(f"{name}: {e}")

    return {"ok": len(errors) == 0, "created": len(created), "errors": errors}


# ── 寫 .env ──────────────────────────────────────────────────────────────

def write_env(vault_path: str, token: str, email: str, init_agents: str = "") -> dict:
    try:
        INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        content = (
            f"CENTRAL_URL={CENTRAL_URL}\n"
            f"NODE_PORT={NODE_PORT}\n"
            f"VAULT_PATH={vault_path}\n"
            f"CENTRAL_OWNER_TOKEN={token}\n"
            f"OWNER_EMAIL={email}\n"
            f"NODE_PUBLIC_URL={_tunnel_url or ''}\n"
            f"INIT_AGENTS={init_agents}\n"
        )
        ENV_FILE.write_text(content, encoding="utf-8")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "note": str(e)}


# ── 排程工作（PowerShell Register-ScheduledTask）──────────────────────────

def install_scheduled_tasks() -> dict:
    # 優先序：venv pythonw → shutil.which → 開發模式 sys.executable
    venv_pw = INSTALL_DIR / "venv" / "Scripts" / "pythonw.exe"
    if venv_pw.exists():
        pythonw: Path | None = venv_pw
    elif getattr(sys, "frozen", False):
        found = shutil.which("pythonw") or shutil.which("python")
        pythonw = Path(found) if found else None
    else:
        py_dir  = Path(sys.executable).parent
        pythonw = py_dir / "pythonw.exe"
        if not pythonw.exists():
            pythonw = Path(sys.executable)

    if not pythonw or not pythonw.is_absolute():
        msg = f"找不到 Python 執行檔（{pythonw}）"
        return {"ok": False, "tasks": {
            "PAOS-Node": {"ok": False, "note": msg},
            "PAOS-Node-控制台": {"ok": False, "note": msg},
        }}

    tasks_def = [
        ("PAOS-Node",        INSTALL_DIR / "start.py",    "00:00:30"),
        ("PAOS-Node-控制台", INSTALL_DIR / "panel_app.py", "00:01:00"),
    ]
    results = {}
    for task_name, script, delay in tasks_def:
        tmp_ps1 = None
        try:
            ps = (
                f"$exe  = '{str(pythonw)}'\n"
                f"$scr  = '{str(script)}'\n"
                f"$wdir = '{str(INSTALL_DIR)}'\n"
                "$act  = New-ScheduledTaskAction -Execute $exe -Argument $scr -WorkingDirectory $wdir\n"
                "$trg  = New-ScheduledTaskTrigger -AtLogOn\n"
                f"$trg.Delay = 'PT{delay.replace(':','H',1).replace(':','M')}S'\n"
                "$set  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 "
                    "-MultipleInstances IgnoreNew "
                    "-RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)\n"
                f"Register-ScheduledTask -TaskName '{task_name}' "
                    "-Action $act -Trigger $trg -Settings $set -RunLevel Limited -Force\n"
            )
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".ps1", encoding="utf-8-sig", delete=False
            ) as f:
                f.write(ps)
                tmp_ps1 = f.name

            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp_ps1],
                capture_output=True, timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            out = (r.stdout + r.stderr).decode("mbcs", errors="replace").strip()
            results[task_name] = {"ok": r.returncode == 0, "note": out[:200]}
        except Exception as e:
            results[task_name] = {"ok": False, "note": str(e)}
        finally:
            if tmp_ps1:
                try:
                    Path(tmp_ps1).unlink(missing_ok=True)
                except Exception:
                    pass

    return {"ok": all(v["ok"] for v in results.values()), "tasks": results}


# ── 桌面捷徑 ──────────────────────────────────────────────────────────────

def _get_desktop_path() -> Path:
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            raw, _ = winreg.QueryValueEx(key, "Desktop")
            p = Path(os.path.expandvars(raw))
            if p.exists():
                return p
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            out = r.stdout.decode("mbcs", errors="replace").strip()
            if out:
                return Path(out)
    except Exception:
        pass
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def create_desktop_shortcut() -> dict:
    tmp_ps1 = None
    try:
        vbs_path = INSTALL_DIR / "launch-panel.vbs"
        lnk_path = _get_desktop_path() / "PAOS Node 控制台.lnk"
        ps = (
            "$ws = New-Object -ComObject WScript.Shell\n"
            f"$sc = $ws.CreateShortcut('{lnk_path}')\n"
            "$sc.TargetPath  = 'wscript.exe'\n"
            f'$sc.Arguments   = \'"{vbs_path}"\'\n'
            "$sc.IconLocation = 'shell32.dll,25'\n"
            "$sc.Description  = 'PAOS Node 控制台'\n"
            "$sc.Save()\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ps1", encoding="utf-8-sig", delete=False
        ) as f:
            f.write(ps)
            tmp_ps1 = f.name
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp_ps1],
            capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = (r.stdout + r.stderr).decode("mbcs", errors="replace").strip()
        return {"ok": r.returncode == 0, "note": out[:200]}
    except Exception as e:
        return {"ok": False, "note": str(e)}
    finally:
        if tmp_ps1:
            try:
                Path(tmp_ps1).unlink(missing_ok=True)
            except Exception:
                pass


# ── launch-panel.vbs ──────────────────────────────────────────────────────

def write_launch_panel_vbs() -> dict:
    try:
        venv_pw = INSTALL_DIR / "venv" / "Scripts" / "pythonw.exe"
        if venv_pw.exists():
            pythonw = venv_pw
        elif not getattr(sys, "frozen", False):
            py_dir  = Path(sys.executable).parent
            pythonw = py_dir / "pythonw.exe"
            if not pythonw.exists():
                pythonw = Path(sys.executable)
        else:
            found = shutil.which("pythonw") or shutil.which("python")
            pythonw = Path(found) if found else Path("pythonw.exe")

        node_dir = str(INSTALL_DIR)
        lines = [
            'Dim oShell, pythonw, nodeDir, q',
            'Set oShell = WScript.CreateObject("WScript.Shell")',
            '',
            f'pythonw = "{str(pythonw)}"',
            f'nodeDir = "{node_dir}"',
            'q       = Chr(34)',
            '',
            "' Step 1: Check if Node is running on port 3100",
            'Dim nodeRunning, oExec, sOut',
            'nodeRunning = False',
            'On Error Resume Next',
            'Set oExec = oShell.Exec("cmd /c netstat -ano | findstr :3100")',
            'If Err.Number = 0 Then',
            '    sOut = oExec.StdOut.ReadAll()',
            '    If InStr(sOut, "LISTENING") > 0 Or InStr(sOut, "127.0.0.1:3100") > 0 Then',
            '        nodeRunning = True',
            '    End If',
            'End If',
            'On Error GoTo 0',
            '',
            "' Step 2: Start Node if not running",
            'If Not nodeRunning Then',
            '    oShell.CurrentDirectory = nodeDir',
            r'    oShell.Run q & pythonw & q & " " & q & nodeDir & "\start.py" & q, 0, False',
            'End If',
            '',
            "' Step 3: Launch panel",
            r'oShell.Run q & pythonw & q & " " & q & nodeDir & "\panel_app.py" & q, 0, False',
        ]
        vbs_path = INSTALL_DIR / "launch-panel.vbs"
        vbs_path.write_text("\n".join(lines) + "\n", encoding="utf-16")
        return {"ok": True, "path": str(vbs_path)}
    except Exception as e:
        return {"ok": False, "note": str(e)}


# ── I-6：完整安裝流程 ────────────────────────────────────────────────────

def run_full_setup(vault_path: str, token: str, email: str,
                   gpt_names: list | None = None) -> dict:
    """
    完整安裝流程：
      1. 部署 Node 檔案（解壓至 INSTALL_DIR）
      2. 建立 venv + pip install
      3. 初始化 Agent Vault 資料夾
      4. 寫 .env
      5. 寫 launch-panel.vbs
      6. 安裝排程工作
      7. 建立桌面捷徑
    """
    steps: dict = {}

    steps["deploy"]     = deploy_node_files()
    steps["venv"]       = install_requirements_venv()
    steps["vault_init"] = (
        initialize_agent_vaults(vault_path, gpt_names)
        if gpt_names else {"ok": True, "note": "無 GPT 設定，跳過"}
    )
    steps["env"]        = write_env(vault_path, token, email,
                                    init_agents=",".join(gpt_names or []))
    steps["vbs"]        = write_launch_panel_vbs()
    steps["tasks"]      = install_scheduled_tasks()
    steps["shortcut"]   = create_desktop_shortcut()

    all_ok = all(v["ok"] for v in steps.values())
    return {"ok": all_ok, "steps": steps}
