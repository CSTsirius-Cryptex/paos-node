# -*- mode: python ; coding: utf-8 -*-
"""
installer.spec — PAOS Node 安裝精靈 PyInstaller 打包配置 (v2)

打包指令（在 installer/ 目錄下執行）：
    cd D:\\Claude\\paos-node\\installer
    pyinstaller installer.spec

輸出：../paos-installer.exe（直接輸出到 paos-node 根目錄，與 start.py 同層）

frozen 行為：
  - sys.executable = paos-installer.exe 所在路徑
  - installer_logic.INSTALL_DIR = Path(sys.executable).parent  → paos-node 根目錄
  - 靜態資源解壓到 sys._MEIPASS/static/
  - pywebview 優先 edgechromium（Edge WebView2，Windows 10/11 內建）
    fallback：winforms（pythonnet + .NET）
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_all

# ── 路徑 ─────────────────────────────────────────────────────────────────────
HERE   = Path(SPECPATH)          # installer/ 目錄（spec 所在位置）
STATIC = HERE / "static"         # installer/static/  (HTML/CSS/JS)
DIST   = HERE.parent             # 輸出到 paos-node 根目錄

# ── 收集 pywebview 全部資產（templates、js bridge、多 backend 的附加檔案）────
webview_datas, webview_binaries, webview_hiddenimports = collect_all("webview")

# ── Analysis ─────────────────────────────────────────────────────────────────
a = Analysis(
    [str(HERE / "installer.py")],
    pathex=[str(HERE)],              # 讓 installer_logic 被找到
    binaries=webview_binaries,
    datas=[
        (str(STATIC), "static"),     # 安裝精靈 UI → _MEIPASS/static/
        *webview_datas,              # pywebview 內建資源
    ],
    hiddenimports=[
        # ── pywebview Windows backends ───────────────────────────────────
        "webview",
        "webview.platforms.edgechromium",   # 優先：Edge WebView2（無需額外 DLL）
        "webview.platforms.winforms",       # fallback：pythonnet + .NET
        "webview.platforms.mshtml",         # legacy fallback
        # ── pythonnet（winforms backend 依賴）───────────────────────────
        "clr",
        "clr_loader",
        # ── installer 本體 ───────────────────────────────────────────────
        "installer_logic",
        # ── HTTP ─────────────────────────────────────────────────────────
        "httpx",
        "httpx._transports.default",
        "httpcore",
        "httpcore._async.http11",
        "httpcore._sync.http11",
        *webview_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大型套件（縮小 exe 體積 & 加快啟動）
        "tkinter",
        "matplotlib",
        "numpy",
        "PIL",
        "pytest",
        "uvicorn",
        "fastapi",
        "sqlalchemy",
        "src",           # paos-node 後端，不需打入 installer
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
    # distpath 需在命令列指定：pyinstaller --distpath=.. installer.spec
    # 或 build 後執行：copy dist\paos-installer.exe ..\
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                   # 不壓縮：防止防毒誤判
    upx_exclude=[],
    console=False,               # GUI 模式：不顯示 cmd 黑視窗
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=str(STATIC / "icon.ico"),  # 若有圖示檔取消此行
    onefile=True,
)
