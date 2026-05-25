# -*- mode: python ; coding: utf-8 -*-
# installer.spec — PAOS Node 安裝精靈 PyInstaller 打包設定
#
# 使用方式（在 installer/ 目錄下執行）：
#   cd D:\Claude\paos-node\installer
#   pyinstaller installer.spec
#
# 輸出：dist/paos-installer.exe（單檔，無 cmd 視窗）
# 打包完後，將 paos-installer.exe 複製到 paos-node 根目錄再發布。

from pathlib import Path

# ── 路徑 ────────────────────────────────────────────────────────────────────
HERE      = Path(SPECPATH)          # installer/ 目錄（spec 檔所在位置）
ROOT      = HERE.parent             # paos-node 根目錄
STATIC    = HERE / "static"         # installer/static/

# ── Analysis ────────────────────────────────────────────────────────────────
a = Analysis(
    [str(HERE / "installer.py")],
    pathex=[str(HERE)],
    binaries=[],
    datas=[
        # 靜態 UI 資源（html / css / js）→ 解壓後在 _MEIPASS/static/
        (str(STATIC), "static"),
    ],
    hiddenimports=[
        # pywebview Windows 後端
        "webview",
        "webview.platforms.winforms",
        # installer 本體
        "installer_logic",
        # HTTP 用戶端
        "httpx",
        "httpx._transports.default",
        "httpcore",
        # pythonnet（pywebview winforms 依賴）
        "clr",
        "clr_loader",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 不需要的大型套件
        "tkinter",
        "matplotlib",
        "numpy",
        "PIL",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="paos-installer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                # 不壓縮（避免防毒誤報）
    upx_exclude=[],
    console=False,            # 不顯示 cmd 黑視窗（GUI 模式）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="static/icon.ico",  # 備用：若有圖示檔可取消註解
    onefile=True,
)
