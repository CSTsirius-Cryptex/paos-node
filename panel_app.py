"""
panel_app.py — PAOS Node 控制台殼層
pystray（系統匣常駐）+ pywebview（視窗）

啟動方式：pythonw panel_app.py
排程工作：PAOS-Node-控制台（PT45S 延遲）
"""
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

# 全域視窗物件（None = 尚未建立）
_window: webview.Window | None = None
_window_lock = threading.Lock()


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
        pystray.MenuItem("開啟控制台", lambda: show_window()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("啟動 Node",  lambda: _run_node_cmd("start")),
        pystray.MenuItem("重啟 Node",  lambda: _run_node_cmd("restart")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("結束",       lambda: quit_app()),
    )
    return pystray.Icon("PAOS", _make_icon(), TITLE, menu)


# ── Node 控制（系統匣選單用）────────────────────────────────────────

def _run_node_cmd(action: str):
    """直接呼叫 schtasks 啟動 / 重啟 Node 排程工作。"""
    task = "PAOS-Node"
    if action == "start":
        subprocess.Popen(["schtasks", "/Run", "/TN", task],
                         creationflags=subprocess.CREATE_NO_WINDOW)
    elif action == "restart":
        subprocess.Popen(["schtasks", "/End", "/TN", task],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(1)
        subprocess.Popen(["schtasks", "/Run", "/TN", task],
                         creationflags=subprocess.CREATE_NO_WINDOW)


# ── 視窗管理 ──────────────────────────────────────────────────────

def _wait_for_node(timeout: int = 30) -> bool:
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


def create_window():
    """建立 pywebview 視窗（必須在主執行緒呼叫）。"""
    global _window
    with _window_lock:
        if _window is not None:
            return

        # 等 Node 就緒，避免 pywebview 載入空白頁
        if not _wait_for_node(30):
            print("[panel_app] 警告：Node 未就緒，仍嘗試開啟視窗")

        _window = webview.create_window(
            TITLE,
            PANEL_URL,
            width=WIN_W,
            height=WIN_H,
            resizable=False,
            min_size=(WIN_W, WIN_H),
            on_top=False,
        )

        def on_closing():
            """關閉按鈕 → 隱藏到系統匣，不退出。"""
            _window.hide()
            return False  # 取消預設關閉行為

        _window.events.closing += on_closing


def show_window():
    """顯示或建立視窗（可從任意執行緒呼叫）。"""
    global _window
    with _window_lock:
        if _window is None:
            # 視窗尚未建立：在主執行緒排程建立
            # pywebview 要求 create_window 在 start() 之前或同執行緒
            # 這裡用 webview.create_window 再 show
            threading.Thread(target=_create_and_show, daemon=True).start()
        else:
            try:
                _window.show()
            except Exception:
                pass


def _create_and_show():
    """在背景執行緒等待並顯示視窗（第一次開啟時）。"""
    global _window
    if not _wait_for_node(30):
        print("[panel_app] Node 未就緒，放棄開啟視窗")
        return
    # webview.create_window 只能在 start() 之前呼叫才能正確渲染
    # 此 fallback 適用於排程延遲啟動的情況
    with _window_lock:
        if _window is None:
            _window = webview.create_window(
                TITLE, PANEL_URL,
                width=WIN_W, height=WIN_H,
                resizable=False,
            )
            def on_closing():
                _window.hide()
                return False
            _window.events.closing += on_closing


# ── 結束 ─────────────────────────────────────────────────────────

_tray: pystray.Icon | None = None

def quit_app():
    """真正退出：停止系統匣，結束 process。"""
    global _tray
    if _tray:
        _tray.stop()
    sys.exit(0)


# ── 主程式 ────────────────────────────────────────────────────────

def main():
    global _tray

    # 建立系統匣（在背景執行緒跑）
    _tray = _create_tray()
    tray_thread = threading.Thread(target=_tray.run, daemon=True)
    tray_thread.start()

    # 等 Node 就緒後建立視窗物件（在 webview.start 之前）
    _wait_for_node(30)
    _window_obj = webview.create_window(
        TITLE, PANEL_URL,
        width=WIN_W, height=WIN_H,
        resizable=False,
        min_size=(WIN_W, WIN_H),
    )

    # 儲存到全域，讓 show_window() 可以控制
    global _window
    _window = _window_obj

    def on_closing():
        _window.hide()
        return False

    _window.events.closing += on_closing

    # 啟動 webview 事件迴圈（blocking，在主執行緒）
    webview.start(debug=False)


if __name__ == "__main__":
    main()
