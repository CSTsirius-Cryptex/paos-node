"""
tests/test_safe_join.py
SEC-1 驗收測試：safe_join() 路徑穿越防護

執行方式：
    cd D:/Claude/paos-node
    python -m pytest tests/test_safe_join.py -v
"""
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch

# ── 讓 pytest 找得到 src/ ──────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

# 用假的 VAULT_PATH 執行測試（不依賴真實環境）
FAKE_VAULT = "C:/FakeVault"


def _get_safe_join():
    """動態 import 並套用假 vault，確保每次測試隔離。"""
    # patch config 的 VAULT_PATH，再 reload obsidian
    import importlib
    with patch.dict("os.environ", {"VAULT_PATH": FAKE_VAULT}):
        # patch src.config.VAULT_PATH
        import src.config as cfg
        original = cfg.VAULT_PATH
        cfg.VAULT_PATH = FAKE_VAULT

        import src.obsidian as obs
        # 重設模組層級的 _VAULT_ROOT
        obs._VAULT_ROOT = Path(FAKE_VAULT).resolve()

        yield obs.safe_join

        # 還原
        cfg.VAULT_PATH = original
        obs._VAULT_ROOT = Path(original).resolve()


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def safe_join():
    import src.config as cfg
    import src.obsidian as obs
    original_vault = cfg.VAULT_PATH
    original_root = obs._VAULT_ROOT

    cfg.VAULT_PATH = FAKE_VAULT
    obs._VAULT_ROOT = Path(FAKE_VAULT).resolve()

    yield obs.safe_join

    cfg.VAULT_PATH = original_vault
    obs._VAULT_ROOT = original_root


# ── 應拒絕的惡意路徑 ──────────────────────────────────────────────────────────

class TestRejectBadPaths:
    def test_dot_dot_simple(self, safe_join):
        """../outside.md 應被拒絕"""
        with pytest.raises(ValueError, match="'\\.\\.'"):
            safe_join("../outside.md")

    def test_dot_dot_nested(self, safe_join):
        """agents/序安/../../outside.md 應被拒絕"""
        with pytest.raises(ValueError, match="'\\.\\.'"):
            safe_join("agents/序安/../../outside.md")

    def test_windows_drive_c(self, safe_join):
        """C:/tmp/x.md 應被拒絕"""
        with pytest.raises(ValueError, match="絕對路徑"):
            safe_join("C:/tmp/x.md")

    def test_windows_drive_d(self, safe_join):
        """D:\\data\\x.md 應被拒絕"""
        with pytest.raises(ValueError, match="絕對路徑"):
            safe_join("D:\\data\\x.md")

    def test_unc_backslash(self, safe_join):
        """\\\\server\\share\\x.md 應被拒絕"""
        with pytest.raises(ValueError, match="UNC"):
            safe_join("\\\\server\\share\\x.md")

    def test_unc_forwardslash(self, safe_join):
        """//server/share/x.md 應被拒絕"""
        with pytest.raises(ValueError, match="UNC"):
            safe_join("//server/share/x.md")

    def test_unix_absolute(self, safe_join):
        """/etc/passwd 應被拒絕"""
        with pytest.raises(ValueError, match="絕對路徑"):
            safe_join("/etc/passwd")

    def test_backslash_root(self, safe_join):
        """\\etc\\passwd 應被拒絕"""
        with pytest.raises(ValueError, match="絕對路徑"):
            safe_join("\\etc\\passwd")

    def test_dot_dot_url_encoded_style(self, safe_join):
        """純字串 '..' 本身應被拒絕"""
        with pytest.raises(ValueError):
            safe_join("..")


# ── 應允許的合法路徑 ──────────────────────────────────────────────────────────

class TestAllowValidPaths:
    def test_empty_string_returns_vault_root(self, safe_join):
        """空字串 → vault root"""
        result = safe_join("")
        assert result == Path(FAKE_VAULT).resolve()

    def test_simple_filename(self, safe_join):
        """notes.md → vault/notes.md"""
        result = safe_join("notes.md")
        assert result.name == "notes.md"
        assert str(result).startswith(str(Path(FAKE_VAULT).resolve()))

    def test_nested_path(self, safe_join):
        """agents/序安/memory/test.md → vault 內"""
        result = safe_join("agents/序安/memory/test.md")
        vault_root = str(Path(FAKE_VAULT).resolve())
        assert str(result).startswith(vault_root)

    def test_legacy_paos_path(self, safe_join):
        """PAOS/workflow/宇恆/workflow-doc.md → vault 內（舊格式，safe_join 仍允許）"""
        result = safe_join("PAOS/workflow/宇恆/workflow-doc.md")
        vault_root = str(Path(FAKE_VAULT).resolve())
        assert str(result).startswith(vault_root)

    def test_v37_path(self, safe_join):
        """agents/宇恆/memory/work-log/2026-05-25.md → vault 內（v3.7 路徑）"""
        result = safe_join("agents/宇恆/memory/work-log/2026-05-25.md")
        vault_root = str(Path(FAKE_VAULT).resolve())
        assert str(result).startswith(vault_root)

    def test_filename_with_double_dot_in_name(self, safe_join):
        """file..txt（非路徑 ..）應允許"""
        result = safe_join("file..txt")
        assert result.name == "file..txt"

    def test_whitespace_stripped(self, safe_join):
        """前後空白應被 strip"""
        result = safe_join("  notes.md  ")
        assert result.name == "notes.md"


# ── 邊界確認 ──────────────────────────────────────────────────────────────────

class TestBoundaryCheck:
    def test_resolve_stays_inside_vault(self, safe_join):
        """解析後路徑必須是 vault root 的子路徑"""
        result = safe_join("PAOS/data/projects.json")
        vault_root = Path(FAKE_VAULT).resolve()
        # relative_to 不 raise → 說明在 vault 內
        result.relative_to(vault_root)  # 不應 raise

    def test_return_type_is_path(self, safe_join):
        """safe_join 回傳 pathlib.Path"""
        result = safe_join("test.md")
        assert isinstance(result, Path)


# ── resolve_memory_path：v3.7 路徑架構 8 種 memory_type ──────────────────────

@pytest.fixture
def resolve_mp():
    """expose resolve_memory_path（不需要真實 Vault）。"""
    from src.obsidian import resolve_memory_path
    return resolve_memory_path


class TestResolveMemoryPath:
    """
    v3.7 路徑架構驗收測試。
    涵蓋所有 8 種 memory_type + 邊界條件。
    """

    # ── agent 專屬記憶 ────────────────────────────────────────────────

    def test_work_log(self, resolve_mp):
        """work_log → agents/{agent}/memory/work-log/{slug}.md"""
        result = resolve_mp("work_log", {"agent_name": "宇恆", "slug": "2026-05-25"})
        assert result == "agents/宇恆/memory/work-log/2026-05-25.md"

    def test_project_memory(self, resolve_mp):
        """project_memory → agents/{agent}/memory/projects/{slug}.md"""
        result = resolve_mp("project_memory", {"agent_name": "宇翔", "slug": "paos"})
        assert result == "agents/宇翔/memory/projects/paos.md"

    def test_insight(self, resolve_mp):
        """insight → agents/{agent}/memory/insights/{slug}.md"""
        result = resolve_mp("insight", {"agent_name": "知衡", "slug": "oauth-design"})
        assert result == "agents/知衡/memory/insights/oauth-design.md"

    # ── 跨 agent 專案協作 ─────────────────────────────────────────────

    def test_perspective(self, resolve_mp):
        """perspective → shared/projects/{slug}/perspectives/{agent}-view.md"""
        result = resolve_mp("perspective", {"agent_name": "宇恆", "slug": "paos"})
        assert result == "shared/projects/paos/perspectives/宇恆-view.md"

    def test_project_brief(self, resolve_mp):
        """project_brief → shared/projects/{slug}/00-brief.md"""
        result = resolve_mp("project_brief", {"agent_name": "宇恆", "slug": "paos"})
        assert result == "shared/projects/paos/00-brief.md"

    def test_decision_nested_slug(self, resolve_mp):
        """decision：slug 可含 / 構成子路徑（如 project/decisions/date-title）。"""
        result = resolve_mp("decision", {
            "agent_name": "宇恆",
            "slug": "paos/decisions/2026-05-25-oauth-fix",
        })
        assert result == "shared/projects/paos/decisions/2026-05-25-oauth-fix.md"

    # ── 共用知識 ──────────────────────────────────────────────────────

    def test_knowledge_simple(self, resolve_mp):
        """knowledge → shared/knowledge/{slug}.md"""
        result = resolve_mp("knowledge", {"agent_name": "宇恆", "slug": "cloudflare-tunnel"})
        assert result == "shared/knowledge/cloudflare-tunnel.md"

    def test_knowledge_nested_slug(self, resolve_mp):
        """knowledge：slug 可含 / 做多層分類。"""
        result = resolve_mp("knowledge", {
            "agent_name": "宇恆",
            "slug": "oauth/token-refresh",
        })
        assert result == "shared/knowledge/oauth/token-refresh.md"

    def test_contact(self, resolve_mp):
        """contact → shared/contacts/{slug}.md"""
        result = resolve_mp("contact", {"agent_name": "宇恆", "slug": "kevin"})
        assert result == "shared/contacts/kevin.md"

    # ── 邊界條件 ──────────────────────────────────────────────────────

    def test_unknown_type_raises(self, resolve_mp):
        """未知 memory_type 應 raise ValueError（含提示文字）。"""
        with pytest.raises(ValueError, match="未知 memory_type"):
            resolve_mp("invalid_type", {"agent_name": "宇恆", "slug": "x"})

    def test_agent_name_normalize_pipe(self, resolve_mp):
        """agent_name 帶全形管道符后綴（｜角色）應截斷。"""
        result = resolve_mp("work_log", {"agent_name": "宇恆｜特助", "slug": "2026-05-25"})
        assert result == "agents/宇恆/memory/work-log/2026-05-25.md"

    def test_agent_name_normalize_paren(self, resolve_mp):
        """agent_name 帶括號后綴（（Beta））應截斷。"""
        result = resolve_mp("insight", {"agent_name": "知衡（Beta）", "slug": "test"})
        assert result == "agents/知衡/memory/insights/test.md"

    def test_default_slug_is_today_iso(self, resolve_mp):
        """不給 slug 時，預設為 YYYY-MM-DD 格式的今天日期。"""
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        result = resolve_mp("work_log", {"agent_name": "宇恆"})
        assert result == f"agents/宇恆/memory/work-log/{today}.md"
