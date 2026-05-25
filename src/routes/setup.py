"""
setup.py — PAOS Node 初始化工具
POST /setup/init-agent  → 為指定 agent 建立標準 Vault 資料夾結構
GET  /setup/status      → 回傳各 agent 的初始化狀態

首次連線邏輯：
  1. Node 啟動時，若 .env 設有 INIT_AGENTS=宇恆,其他助理，自動初始化
  2. GPT 可在首次使用時呼叫 POST /setup/init-agent（冪等，多次呼叫安全）
  3. GPT 應將 GET /notes/agents/{name}/profile.md 回 404 視為「全新用戶」，
     呼叫此端點初始化後再繼續
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from src.auth import require_auth, require_memory_write
from src.obsidian import safe_join, _VAULT_ROOT, VAULT_PATH

router = APIRouter(dependencies=[Depends(require_auth)])

# ── 標準資料夾模板 ────────────────────────────────────────────────────

# ── v3.7 對齊的資料夾結構 ──────────────────────────────────────────

AGENT_FOLDERS = [
    # work_log 日誌目錄
    "agents/{agent}/memory/work-log",
    # 專案記憶目錄
    "agents/{agent}/memory/projects",
    # 洞察目錄
    "agents/{agent}/memory/insights",
]

SHARED_FOLDERS = [
    "shared/projects",
    "shared/knowledge",
    "shared/contacts",
]

# ── 初始檔案範本 ────────────────────────────────────────────────────

PROFILE_TEMPLATE = """\
---
agent: {agent}
initialized: {date}
status: fresh
---

# {agent} 的記憶空間

這個記憶空間剛剛建立，尚無歷史記憶。
第一次對話完成後，`status` 會自動更新為 `active`。
"""

INDEX_TEMPLATE = """\
# {agent} 知識索引
最後更新：{date}

## 專案

## 洞察

## 共用知識（我貢獻的）

## 重要聯絡人
"""

LOG_TEMPLATE = """\
# {agent} 操作日誌

<!-- append-only，永不刪除條目 -->
<!-- 格式：## [YYYY-MM-DD] {{操作類型}} | {{說明}} [[相關頁面路徑]] -->
<!-- 操作類型：ingest / query / decision / update / lint -->

"""


class InitAgentRequest(BaseModel):
    agent_name: str
    force: Optional[bool] = False  # True = 即使 profile 已存在也重建


# ── 工具函式 ──────────────────────────────────────────────────────────

def _ensure_dir(vault_root: Path, rel_path: str) -> Path:
    """在 Vault 內建立資料夾（含所有上層），回傳絕對路徑。"""
    full = (vault_root / rel_path).resolve()
    # 安全驗證：確保不越出 vault root
    try:
        full.relative_to(vault_root)
    except ValueError:
        raise ValueError(f"路徑越界：{rel_path}")
    full.mkdir(parents=True, exist_ok=True)
    return full


def _write_if_not_exists(full_path: Path, content: str):
    """若檔案不存在則寫入；已存在則跳過（不覆蓋）。"""
    if not full_path.exists():
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")


def _write_always(full_path: Path, content: str):
    """無條件寫入（force 模式用）。"""
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")


def init_agent_vault(agent_name: str, force: bool = False) -> dict:
    """
    為 agent_name 建立標準資料夾結構，回傳建立結果。
    冪等：重複呼叫不會覆蓋已有的 profile（除非 force=True）。
    """
    vault = Path(VAULT_PATH).resolve()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    created = []
    skipped = []

    # 1. agent 專屬資料夾
    for folder_tpl in AGENT_FOLDERS:
        rel = folder_tpl.format(agent=agent_name)
        try:
            _ensure_dir(vault, rel)
            created.append(rel)
        except Exception as e:
            skipped.append({"path": rel, "reason": str(e)})

    # 2. 共用資料夾（所有 agent 共用，只建一次）
    for rel in SHARED_FOLDERS:
        try:
            _ensure_dir(vault, rel)
            if rel not in created:
                created.append(rel)
        except Exception as e:
            skipped.append({"path": rel, "reason": str(e)})

    # 3. profile.md（首次建立標記，供 GET /setup/status 判斷 fresh/active）
    profile_path = vault / "agents" / agent_name / "profile.md"
    profile_content = PROFILE_TEMPLATE.format(agent=agent_name, date=date_str)
    if force:
        _write_always(profile_path, profile_content)
        created.append(f"agents/{agent_name}/profile.md")
    else:
        if not profile_path.exists():
            _write_if_not_exists(profile_path, profile_content)
            created.append(f"agents/{agent_name}/profile.md")
        else:
            skipped.append({"path": f"agents/{agent_name}/profile.md", "reason": "已存在，略過（force=False）"})

    # 4. index.md（v3.7 知識索引導航檔）
    index_path = vault / "agents" / agent_name / "index.md"
    index_content = INDEX_TEMPLATE.format(agent=agent_name, date=date_str)
    if force:
        _write_always(index_path, index_content)
        created.append(f"agents/{agent_name}/index.md")
    else:
        if not index_path.exists():
            _write_if_not_exists(index_path, index_content)
            created.append(f"agents/{agent_name}/index.md")
        else:
            skipped.append({"path": f"agents/{agent_name}/index.md", "reason": "已存在，略過"})

    # 5. log.md（v3.7 操作日誌，append-only）
    log_path = vault / "agents" / agent_name / "log.md"
    log_content = LOG_TEMPLATE.format(agent=agent_name)
    if force:
        _write_always(log_path, log_content)
        created.append(f"agents/{agent_name}/log.md")
    else:
        if not log_path.exists():
            _write_if_not_exists(log_path, log_content)
            created.append(f"agents/{agent_name}/log.md")
        else:
            skipped.append({"path": f"agents/{agent_name}/log.md", "reason": "已存在，略過"})

    return {
        "ok": True,
        "agent": agent_name,
        "created": created,
        "skipped": skipped,
    }


# ── 路由 ──────────────────────────────────────────────────────────────

@router.post("/setup/init-agent", dependencies=[Depends(require_memory_write)])
def api_init_agent(req: InitAgentRequest):
    """
    為指定助理初始化 Vault 資料夾結構。

    - 冪等：重複呼叫安全，不會覆蓋已有筆記（除非 force=true）
    - 建立：agents/{name}/{perspectives,decisions,insights}/、PAOS/workflow/{name}/、shared/
    - 建立：agents/{name}/profile.md（首次使用標記）
    - 適合 GPT 在首次對話時呼叫
    """
    try:
        result = init_agent_vault(req.agent_name, req.force or False)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"初始化失敗：{e}")


@router.get("/setup/status")
def api_setup_status():
    """
    回傳 Vault 內各已初始化 agent 的狀態。
    讀取 agents/ 下的所有 profile.md，解析 status 欄位。
    """
    vault = Path(VAULT_PATH).resolve()
    agents_dir = vault / "agents"
    result = []

    if not agents_dir.exists():
        return {"initialized": False, "agents": []}

    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        profile = agent_dir / "profile.md"
        status = "no_profile"
        if profile.exists():
            text = profile.read_text(encoding="utf-8")
            # 從 frontmatter 取 status
            for line in text.splitlines():
                if line.startswith("status:"):
                    status = line.split(":", 1)[1].strip()
                    break
        result.append({
            "agent": agent_dir.name,
            "profile_exists": profile.exists(),
            "status": status,
        })

    return {"initialized": len(result) > 0, "agents": result}
