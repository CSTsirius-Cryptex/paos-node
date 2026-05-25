"""
panel_app.py — PAOS Node 控制台殼層
pystray（系統匣常駐）+ pywebview（視窗）

啟動方式：pythonw panel_app.py
排程工作：PAOS-Node-控制台（PT01M 延遲）
捷徑：launch-panel.vbs（雙擊即可，已有實例時叫出視窗，未有則啟動）
"""
import socket as _socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import webview
import pystray
from PIL import Image, ImageDraw

NODE_URL  = "http://localhost:3100"
PANEL_URL = f"{NODE_URL}/panel/index.html"
WIN_W, WIN_H = 960, 640
TITLE = "PAOS Node 控制台"

# 單一實例控制端口（本機 only）
_CTRL_PORT = 13100

# 全域視窗物件（None = 尚未建立）
_window: webview.Window | None = None
_window_lock = threading.Lock()


# ── Splash / Error 頁面（WO-01：Node 就緒前顯示）────────────────
_SPLASH_HTML = """<!DOCTYPE html>
<html lang="zh-TW"><head><meta charset="UTF-8">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{width:960px;height:640px;background:#140d2e;display:flex;
     align-items:center;justify-content:center;
     font-family:"Microsoft JhengHei UI",system-ui,sans-serif;color:#fff}
.wrap{display:flex;flex-direction:column;align-items:center;gap:22px}
.logo{font-size:34px;font-weight:800;letter-spacing:.08em;
      background:linear-gradient(135deg,#a78bfa,#7c3aed);
      -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.spinner{width:44px;height:44px;border:3px solid rgba(167,139,250,.25);
         border-top-color:#a78bfa;border-radius:50%;
         animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.msg{font-size:15px;color:rgba(255,255,255,.85)}
.sub{font-size:12px;color:rgba(255,255,255,.38)}
</style></head>
<body><div class="wrap">
  <div class="logo">PAOS</div>
  <div class="spinner"></div>
  <p class="msg">Node 啟動中…</p>
  <p class="sub">正在等待服務就緒，請稍候</p>
</div></body></html>"""

_ERROR_HTML = """<!DOCTYPE html>
<html lang="zh-TW"><head><meta charset="UTF-8">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{width:960px;height:640px;background:#140d2e;display:flex;
     align-items:center;justify-content:center;
     font-family:"Microsoft JhengHei UI",system-ui,sans-serif;color:#fff}
.wrap{display:flex;flex-direction:column;align-items:center;gap:18px;
      text-align:center;max-width:500px}
.logo{font-size:28px;font-weight:800;letter-spacing:.08em;color:#f87171}
.icon{font-size:40px}
.msg{font-size:15px;color:rgba(255,255,255,.9)}
.hint{font-size:13px;background:rgba(255,255,255,.06);border-radius:8px;
      padding:14px 22px;color:rgba(255,255,255,.55);line-height:1.9;text-align:left}
code{background:rgba(255,255,255,.1);padding:1px 6px;border-radius:3px;font-size:12px}
</style></head>
<body><div class="wrap">
  <div class="logo">PAOS</div>
  <div class="icon">&#9888;</div>
  <p class="msg">Node 啟動逾時（60 秒）</p>
  <div class="hint">
    可能的原因：<br>
    &bull; cloudflared 尚未安裝或網路不通<br>
    &bull; start.py 發生錯誤<br><br>
    解決方式：關閉視窗，重新雙擊桌面捷徑<br>
    或開啟 PowerShell 執行 <code>python start.py</code> 查看錯誤訊息
  </div>
</div></body></html>"""


# ── 單一實例機制 ──────────────────────────────────────────────────

_ctrl_server: _socket.socket | None = None

def _try_become_primary() -> bool:
    """嘗試綁定控制端口。成功 = 第一個實例，失敗 = 已有實例在執行。"""
    global _ctrl_server
    try:
        srv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        srv.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 0)
        srv.bind(("127.0.0.1", _CTRL_PORT))
        srv.listen(5)
        _ctrl_server = srv
        return True
    except OSError:
        return False


def _signal_existing_instance():
    """向已執行的實例發送 show 訊號，讓它把視窗叫出來。"""
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(("127.0.0.1", _CTRL_PORT))
        s.sendall(b"show")
        s.close()
    except Exception:
        pass


def _ctrl_server_loop():
    """背景執行緒：接受控制訊號（目前只有 show）。"""
    while True:
        try:
            conn, _ = _ctrl_server.accept()
            data = conn.recv(16)
            conn.close()
            if data.startswith(b"show"):
                show_window()
        except Exception:
            break


# ── 系統匣圖示 ────────────────────────────────────────────────────

def _make_icon(size: int = 64) -> Image.Image:
    """暫用純色紫色圓點，等 Claude Design 提供正式圖示後替換。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = size // 8
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(110, 68, 200, 255)   # PAOS 紫色
    )
    return img


def _create_tray() -> pystray.Icon:
    menu = pystray.Menu(
        pystray.MenuItem("開啟控制台",   lambda: show_window()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("啟動 Node",   lambda: _run_node_cmd("start")),
        pystray.MenuItem("重啟 Node",   lambda: _run_node_cmd("restart")),
        pystray.MenuItem("強制重啟 Node", lambda: _run_node_cmd("force-restart")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("結束",        lambda: quit_app()),
    )
    return pystray.Icon("PAOS", _make_icon(), TITLE, menu)


# ── Node 控制（系統匣選單用）──────────────────────────────────────

_py_dir  = Path(sys.executable).parent
_PYTHONW = _py_dir / "pythonw.exe"
if not _PYTHONW.exists():
    _PYTHONW = Path(sys.executable)
_NODE_DIR = Path(__file__).parent
_START_PY = _NODE_DIR / "start.py"

def _detached_restart_node(pre_delay_ms: int = 500, also_kill_port: bool = False):
    """
    在獨立的 PowerShell 進程中殺掉舊 Node 並重啟。
    also_kill_port=True  → 強制重啟：同時殺掉監聽 port 3100 的進程（保證舊 uvicorn 被砍掉）
    also_kill_port=False → 一般重啟：只殺 cloudflared，讓 Node 自然重啟
    """
    pythonw  = str(_PYTHONW).replace("'", "''")
    start_py = str(_START_PY).replace("'", "''")
    node_dir = str(_NODE_DIR).replace("'", "''")

    kill_port_block = (
        "$lines = netstat -ano | Select-String ':3100\\s.*LISTENING'; "
        "foreach ($l in $lines) { $pid = ($l.ToString() -split '\\s+')[-1].Trim(); "
        "  if ($pid -match '^[1-9][0-9]*$') { taskkill /F /PID $pid 2>$null } }; "
    ) if also_kill_port else ""

    ps_script = (
        f"Start-Sleep -Milliseconds {pre_delay_ms}; "
        "try { taskkill /F /IM cloudflared.exe 2>$null } catch {}; "
        + kill_port_block +
        "Start-Sleep -Seconds 3; "
        f"Start-Process -FilePath '{pythonw}' "
        f"-ArgumentList '\"{start_py}\"' "
        f"-WorkingDirectory '{node_dir}' "
        f"-WindowStyle Hidden"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _run_node_cmd(action: str):
    """直接用 pythonw 啟動 / 重啟 Node（繞過 schtasks PATH 問題）。"""
    if action == "start":
        subprocess.Popen(
            [str(_PYTHONW), str(_START_PY)],
            cwd=str(_NODE_DIR),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    elif action == "restart":
        # 一般重啟：殺 cloudflared，讓 start.py 重新跑
        _detached_restart_node(pre_delay_ms=500, also_kill_port=False)
    elif action == "force-restart":
        # 強制重啟：同時殺 port 3100 的進程（舊 uvicorn），確保新程式碼被載入
        _detached_restart_node(pre_delay_ms=500, also_kill_port=True)


# ── 視窗管理 ──────────────────────────────────────────────────────

def _wait_for_node(timeout: int = 60) -> bool:
    """等待 Node HTTP server 就緒（最多 timeout 秒）。"""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{NODE_URL}/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def _wait_and_navigate():
    """WO-01：背景等 Node 就緒後跳轉到 panel URL，否則顯示錯誤頁。
    splash 至少顯示 3 秒，避免 Node 已在跑時畫面閃過看不到。
    """
    t_start = time.time()
    ok = _wait_for_node(60)
    # 確保 splash 至少顯示 3 秒（給 WebView2 初始化 + 使用者感知時間）
    elapsed = time.time() - t_start
    if elapsed < 3:
        time.sleep(3 - elapsed)
    with _window_lock:
        if _window is None:
            return
        try:
            if ok:
                _window.load_url(PANEL_URL)
            else:
                _window.load_html(_ERROR_HTML)
        except Exception:
            pass


def show_window():
    """顯示視窗（可從任意執行緒呼叫）。"""
    global _window
    with _window_lock:
        if _window is not None:
            try:
                _window.show()
            except Exception:
                pass


# ── 結束 ─────────────────────────────────────────────────────────

_tray: pystray.Icon | None = None

def quit_app():
    """真正退出：關閉控制 socket、停止系統匣，結束 process。"""
    global _tray, _ctrl_server
    if _ctrl_server:
        try:
            _ctrl_server.close()
        except Exception:
            pass
    if _tray:
        _tray.stop()
    sys.exit(0)


# ── JavaScript API（JS → Python 橋接）────────────────────────────

class JsApi:
    """
    透過 window.pywebview.api 從頁面 JS 呼叫的 Python 方法。
    對話框由 pywebview 視窗自己生成，天然置頂，不需要處理 Z-order。
    """

    def pick_folder(self, initial: str = "") -> str:
        """開啟原生資料夾選擇對話框，回傳使用者選擇的路徑（取消時回傳空字串）。"""
        with _window_lock:
            win = _window
        if win is None:
            return ""
        try:
            result = win.create_file_dialog(
                webview.FOLDER_DIALOG,
                allow_multiple=False,
                directory=initial if initial else "",
            )
            return result[0] if result else ""
        except Exception:
            return ""


# ── 主程式 ────────────────────────────────────────────────────────

def main():
    global _tray, _window

    # ── 單一實例檢查 ──
    if not _try_become_primary():
        _signal_existing_instance()
        sys.exit(0)

    # 啟動控制端口監聽執行緒
    threading.Thread(target=_ctrl_server_loop, daemon=True).start()

    # 建立系統匣（背景執行緒）
    _tray = _create_tray()
    threading.Thread(target=_tray.run, daemon=True).start()

    # WO-01：立刻建立視窗，顯示 splash，不再 blocking 等 Node
    _window_obj = webview.create_window(
        TITLE,
        html=_SPLASH_HTML,          # 先顯示啟動中畫面
        js_api=JsApi(),             # 暴露 Python API 給 JS（pick_folder 等）
        width=WIN_W, height=WIN_H,
        resizable=False,
        min_size=(WIN_W, WIN_H),
    )
    _window = _window_obj

    def on_closing():
        _window.hide()
        return False

    _window.events.closing += on_closing

    # 背景等 Node 就緒後自動跳轉（不 blocking 主執行緒）
    threading.Thread(target=_wait_and_navigate, daemon=True).start()

    # 啟動 webview 事件迴圈（blocking，在主執行緒）
    webview.start(debug=False)


if __name__ == "__main__":
    main()
