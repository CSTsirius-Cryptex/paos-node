import os
import re
from pathlib import Path
from datetime import datetime
from src.config import VAULT_PATH

# vault root（resolve 後的絕對 Path，用於邊界驗證）
_VAULT_ROOT: Path = Path(VAULT_PATH).resolve()


def safe_join(user_path: str) -> Path:
    """
    將 user_path 解析為 Vault 子路徑，確保結果嚴格在 vault root 之內。

    允許：空字串（回傳 vault root）、合法的 vault-relative 相對路徑。

    拒絕（raise ValueError，呼叫端 routes 應轉為 HTTP 400）：
    - Windows drive prefix（C:、D: 等）
    - UNC 路徑（\\\\server\\share 或 //server/share）
    - 以 / 或 \\ 開頭的絕對路徑
    - 包含 .. 區段的路徑
    - 解析後越出 vault root 的路徑
    """
    if not user_path or not user_path.strip():
        return _VAULT_ROOT

    p = user_path.strip()

    # Windows drive prefix（e.g. C: D:）
    if len(p) >= 2 and p[1] == ':':
        raise ValueError(f"拒絕絕對路徑：{user_path!r}")
    # UNC 路徑（\\\\ 或 //）
    if p.startswith('\\\\') or p.startswith('//'):
        raise ValueError(f"拒絕 UNC 路徑：{user_path!r}")
    # Unix / Windows root
    if p.startswith('/') or p.startswith('\\'):
        raise ValueError(f"拒絕絕對路徑：{user_path!r}")
    # .. 區段
    if '..' in p.replace('\\', '/').split('/'):
        raise ValueError(f"拒絕包含 '..' 的路徑：{user_path!r}")

    resolved = (_VAULT_ROOT / p).resolve()
    try:
        resolved.relative_to(_VAULT_ROOT)
    except ValueError:
        raise ValueError(f"路徑越界 vault root：{user_path!r}")

    return resolved


def resolve_path(relative: str) -> str:
    """向後相容包裝，內部改用 safe_join 確保路徑安全。"""
    return str(safe_join(relative))


def read_note(path: str) -> str:
    full = resolve_path(path)
    if not os.path.exists(full):
        raise FileNotFoundError(f"找不到筆記：{path}")
    with open(full, "r", encoding="utf-8") as f:
        return f.read()

def write_note(path: str, content: str) -> None:
    full = resolve_path(path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)

def append_note(path: str, content: str) -> None:
    full = resolve_path(path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "a", encoding="utf-8") as f:
        f.write("\n" + content)

def list_notes(folder: str = "") -> list[str]:
    base = safe_join(folder)   # "" → _VAULT_ROOT；非法路徑 → ValueError
    result = []
    for root, _, files in os.walk(base):
        for f in files:
            if f.endswith(".md"):
                full = os.path.join(root, f)
                result.append(os.path.relpath(full, VAULT_PATH).replace(os.sep, "/"))
    return result

def normalize_agent_name(raw: str) -> str:
    return re.split(r"[｜|（(]", raw)[0].strip()

MEMORY_TYPE_PATHS = {
    # ── agent 專屬記憶 ─────────────────────────────────────────────
    # work_log: slug 預設 YYYY-MM-DD（每天一檔），也可指定日期字串
    "work_log":       "agents/{agent}/memory/work-log/{slug}.md",
    # project_memory: slug = project_slug
    "project_memory": "agents/{agent}/memory/projects/{slug}.md",
    # insight: slug = topic 關鍵字
    "insight":        "agents/{agent}/memory/insights/{slug}.md",

    # ── 跨 agent 專案協作 ──────────────────────────────────────────
    # perspective / project_brief: slug = project_slug
    "perspective":    "shared/projects/{slug}/perspectives/{agent}-view.md",
    "project_brief":  "shared/projects/{slug}/00-brief.md",
    # decision: slug = "project_slug/decisions/YYYY-MM-DD-title"
    #   慣例：GPT 在 slug 帶入完整子路徑，例：
    #   slug="paos/decisions/2026-05-25-oauth-fix"
    #   → shared/projects/paos/decisions/2026-05-25-oauth-fix.md
    "decision":       "shared/projects/{slug}.md",

    # ── 共用知識 ───────────────────────────────────────────────────
    # knowledge: slug 可含 / 分隔 topic 層，例：slug="oauth/token-refresh"
    #   → shared/knowledge/oauth/token-refresh.md
    "knowledge":      "shared/knowledge/{slug}.md",
    "contact":        "shared/contacts/{slug}.md",
}

def resolve_memory_path(memory_type: str, params: dict) -> str:
    template = MEMORY_TYPE_PATHS.get(memory_type)
    if not template:
        raise ValueError(f"未知 memory_type: {memory_type}")
    agent = normalize_agent_name(params.get("agent_name", ""))
    # 預設 slug 使用 YYYY-MM-DD（ISO 格式，對應 work_log 每日歸檔）
    slug = params.get("slug", datetime.now().strftime("%Y-%m-%d"))
    return template.format(agent=agent, slug=slug)
