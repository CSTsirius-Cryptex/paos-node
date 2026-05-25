"""
installer.py — PAOS Node 安裝精靈主程式
pywebview 視窗 + JS Bridge 呼叫 installer_logic
啟動：python installer.py
打包：pyinstaller installer.spec
"""
import sys
import threading
from pathlib import Path

import webview
import installer_logic as logic

WIN_W, WIN_H = 720, 540
TITLE = "PAOS Node 安裝精靈"

# frozen（PyInstaller）模式：靜態檔案解壓在 sys._MEIPASS/static
if getattr(sys, "frozen", False):
    STATIC_DIR = Path(sys._MEIPASS) / "static"  # type: ignore[attr-defined]
else:
    STATIC_DIR = Path(__file__).parent / "static"


class InstallerAPI:
    """暴露給 JavaScript 的 Python API（透過 pywebview JS Bridge）。"""

    # ── I-2：環境偵測 ──
    def check_environment(self):
        return logic.check_environment()

    # ── I-3：Vault 路徑 ──
    def browse_folder(self):
        """開啟資料夾選擇對話框，回傳選擇的路徑。"""
        result = window.create_file_dialog(
            webview.FOLDER_DIALOG,
            directory="C:/Users",
            allow_multiple=False
        )
        if result:
            return result[0].replace("\\", "/")
        return None

    def validate_vault(self, path: str):
        return logic.validate_vault_path(path)

    # ── I-4：OTP 登入 ──
    def request_otp(self, email: str):
        return logic.request_otp(email)

    def verify_otp(self, email: str, otp: str):
        return logic.verify_otp(email, otp)

    # ── I-5：Tunnel ──
    def start_tunnel(self, token: str):
        # 在背景執行緒跑（避免阻塞 JS Bridge）
        result_holder = {}
        done = threading.Event()

        def run():
            result_holder["result"] = logic.start_tunnel_and_register(token)
            done.set()

        threading.Thread(target=run, daemon=True).start()
        done.wait(timeout=90)
        return result_holder.get("result", {"ok": False, "note": "逾時"})

    # ── I-6：完整安裝 ──
    def run_setup(self, vault_path: str, token: str, email: str):
        return logic.run_full_setup(vault_path, token, email)

    # ── 通用 ──
    def get_install_dir(self):
        return str(logic.INSTALL_DIR).replace("\\", "/")

    def launch_panel(self):
        """啟動控制台 VBS 並關閉安裝視窗。"""
        import subprocess
        vbs = logic.INSTALL_DIR / "launch-panel.vbs"
        if vbs.exists():
            subprocess.Popen(["wscript.exe", str(vbs)],
                             creationflags=subprocess.CREATE_NO_WINDOW)
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
