"""
PAOS Node 啟動腳本

執行順序：
1. 啟動 cloudflared quick tunnel，等待取得公開 URL
2. 將 URL 寫回 .env（NODE_PUBLIC_URL）
3. 啟動 uvicorn，FastAPI lifespan 會自動向 Central 登錄新 URL
"""
import subprocess
import threading
import re
import os
import sys
import time
import socket
from pathlib import Path

CLOUDFLARED_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
ENV_FILE = Path(__file__).parent / ".env"
NODE_PORT = int(os.getenv("NODE_PORT", "3100"))
TUNNEL_TIMEOUT = 60  # seconds to wait for cloudflared URL
NETWORK_TIMEOUT = 60  # seconds to wait for network ready


def wait_for_network(timeout: int = NETWORK_TIMEOUT):
    """等待網路就緒（能連到 Cloudflare DNS 1.1.1.1:443）。"""
    print(f"[start] 等待網路就緒（最多 {timeout} 秒）...")
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            with socket.create_connection(("1.1.1.1", 443), timeout=3):
                print(f"[start] 網路就緒（第 {attempt} 次嘗試）")
                return
        except OSError:
            time.sleep(2)
    print("[start] 警告：等待網路逾時，仍繼續嘗試啟動...")


def update_env_file(url: str):
    """將 NODE_PUBLIC_URL 更新到 .env 檔案中。"""
    if not ENV_FILE.exists():
        return
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith("NODE_PUBLIC_URL="):
            new_lines.append(f"NODE_PUBLIC_URL={url}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"NODE_PUBLIC_URL={url}")
    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"[start] .env 已更新：NODE_PUBLIC_URL={url}")


def drain_pipe(pipe, prefix: str):
    """持續讀取 pipe 並印出，避免 buffer 塞住。"""
    try:
        for line in pipe:
            print(f"[{prefix}] {line.decode('utf-8', errors='replace').rstrip()}")
    except Exception:
        pass


def start_cloudflared() -> str:
    """啟動 cloudflared quick tunnel，回傳公開 URL。"""
    print(f"[start] 啟動 cloudflared tunnel → http://localhost:{NODE_PORT}")
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{NODE_PORT}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    url = None
    deadline = time.time() + TUNNEL_TIMEOUT

    # cloudflared 把 URL 印在 stderr
    def read_stderr():
        nonlocal url
        for raw in proc.stderr:
            line = raw.decode("utf-8", errors="replace").rstrip()
            print(f"[cloudflared] {line}")
            if url is None:
                m = CLOUDFLARED_PATTERN.search(line)
                if m:
                    url = m.group(0)

    t = threading.Thread(target=read_stderr, daemon=True)
    t.start()

    # 等待 URL 出現
    while url is None and time.time() < deadline:
        time.sleep(0.5)

    if url is None:
        proc.terminate()
        print("[start] 錯誤：等待 cloudflared URL 超時，請確認 cloudflared 已安裝且網路正常")
        sys.exit(1)

    # stdout drain（背景）
    threading.Thread(target=drain_pipe, args=(proc.stdout, "cloudflared-out"), daemon=True).start()

    # CP-5：監控 cloudflared 崩潰，主動退出讓排程工作重啟整個 Node
    def watch_cloudflared(p: subprocess.Popen):
        p.wait()
        code = p.returncode
        # returncode = None 代表還在跑（正常不會走到這），
        # code = 0 代表正常結束（使用者主動關閉），不視為崩潰
        if code is not None and code != 0:
            import logging as _log
            _log.critical(
                f"[FATAL] cloudflared 異常退出 (exit={code})，"
                "主動退出 Node，等待排程工作自動重啟..."
            )
            sys.exit(1)
        else:
            print(f"[cloudflared] 已結束 (exit={code})")

    threading.Thread(target=watch_cloudflared, args=(proc,), daemon=True).start()

    return url


def main():
    wait_for_network()
    url = start_cloudflared()
    print(f"[start] Tunnel URL：{url}")

    # 更新 .env 並設進當前 process 環境
    update_env_file(url)
    os.environ["NODE_PUBLIC_URL"] = url

    # 啟動 uvicorn（blocking）
    import uvicorn
    print(f"[start] 啟動 PAOS Node on port {NODE_PORT}")
    uvicorn.run("src.main:app", host="0.0.0.0", port=NODE_PORT, reload=False)


if __name__ == "__main__":
    main()
