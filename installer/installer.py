"""
installer.py — PAOS Node 安裝精靈主程式
pywebview 視窗 + JS Bridge 呼叫 installer_logic
啟動：python installer.py
打包：pyinstaller installer.spec --distpath=..
"""
import sys
import threading
from pathlib import Path

import webview
import installer_logic as logic

WIN_W, WIN_H = 720, 700
TITLE = "PAOS Node 安裝精靈"

# frozen（PyInstaller）模式：靜態檔案解壓在 sys._MEIPASS/static
if getattr(sys, "frozen", False):
    STATIC_DIR = Path(sys._MEIPASS) / "static"  # type: ignore[attr-defined]
else:
    STATIC_DIR = Path(__file__).parent / "static"


class InstallerAPI:
    """暴露給 JavaScript 的 Python API（透過 pywebview JS Bridge）。"""

    # ── Step 1：環境偵測 ──
    def check_environment(self):
        return logic.check_environment()

    # ── Step 2：安裝目錄 ──
    def get_default_install_dir(self):
        return logic.get_default_install_dir()

    def validate_install_dir(self, path: str):
        return logic.validate_install_dir(path)

    def set_install_dir(self, path: str):
        return logic.set_install_dir(path)

    def browse_install_dir(self):
        """開啟資料夾選擇對話框（安裝目錄）。"""
        result = window.create_file_dialog(
            webview.FOLDER_DIALOG,
            directory=logic.get_default_install_dir(),
            allow_multiple=False,
        )
        if result:
            return result[0].replace("\\", "/")
        return None

    # ── Step 3：Vault 路徑 ──
    def browse_folder(self):
        """開啟資料夾選擇對話框（Vault 根目錄）。"""
        result = window.create_file_dialog(
            webview.FOLDER_DIALOG,
            directory="C:/Users",
            allow_multiple=False,
        )
        if result:
            return result[0].replace("\\", "/")
        return None

    def validate_vault(self, path: str):
        return logic.validate_vault_path(path)

    # ── Python 自動安裝 ──
    def download_python(self):
        """透過 winget 安裝最新版 Python。"""
        result_holder = {}
        done = threading.Event()

        def run():
            result_holder["result"] = logic.download_python()
            done.set()

        threading.Thread(target=run, daemon=True).start()
        done.wait(timeout=360)
        return result_holder.get("result", {"ok": False, "note": "安裝逾時"})

    # ── cloudflared 自動下載 ──
    def download_cloudflared(self):
        """從 GitHub Releases 下載並安裝最新版 cloudflared。"""
        result_holder = {}
        done = threading.Event()

        def run():
            result_holder["result"] = logic.download_cloudflared()
            done.set()

        threading.Thread(target=run, daemon=True).start()
        done.wait(timeout=120)
        return result_holder.get("result", {"ok": False, "note": "下載逾時"})

    # ── Obsidian 自動下載 ──
    def download_obsidian(self):
        """從 GitHub Releases 下載並安裝最新版 Obsidian。"""
        result_holder = {}
        done = threading.Event()

        def run():
            result_holder["result"] = logic.download_obsidian()
            done.set()

        threading.Thread(target=run, daemon=True).start()
        done.wait(timeout=300)  # ~100 MB，最多 5 分鐘
        return result_holder.get("result", {"ok": False, "note": "下載逾時"})

    # ── Step 4：OTP 登入 ──
    def request_otp(self, email: str, name: str = ""):
        return logic.request_otp(email, name)

    def verify_otp(self, email: str, otp: str):
        return logic.verify_otp(email, otp)

    # ── Step 5：Tunnel ──
    def start_tunnel(self, token: str):
        result_holder = {}
        done = threading.Event()

        def run():
            result_holder["result"] = logic.start_tunnel_and_register(token)
            done.set()

        threading.Thread(target=run, daemon=True).start()
        done.wait(timeout=90)
        return result_holder.get("result", {"ok": False, "note": "逾時"})

    # ── Step 6：完整安裝 ──
    def run_setup(self, vault_path: str, token: str, email: str,
                  gpt_names=None):
        return logic.run_full_setup(
            vault_path, token, email,
            gpt_names=list(gpt_names) if gpt_names else None,
        )

    # ── 通用 ──
    def open_url(self, url: str):
        """在系統預設瀏覽器開啟外部連結。"""
        import webbrowser
        webbrowser.open(url)
        return {"ok": True}

    def get_install_dir(self):
        return str(logic.INSTALL_DIR).replace("\\", "/")

    def launch_panel(self):
        """啟動控制台 VBS 並關閉安裝視窗。"""
        import subprocess
        vbs = logic.INSTALL_DIR / "launch-panel.vbs"
        if vbs.exists():
            subprocess.Popen(
                ["wscript.exe", str(vbs)],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        window.destroy()


def main():
    global window

    api    = InstallerAPI()
    window = webview.create_window(
        TITLE,
        str(STATIC_DIR / "installer.html"),
        width=WIN_W,
        height=WIN_H,
        resizable=False,
        js_api=api,
    )
    webview.start(debug=False)


if __name__ == "__main__":
    main()
