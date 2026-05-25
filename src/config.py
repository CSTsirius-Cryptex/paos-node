import os
from dotenv import load_dotenv

load_dotenv(encoding="utf-8")

CENTRAL_URL     = os.getenv("CENTRAL_URL", "https://paos-central-production.up.railway.app")
NODE_PORT       = int(os.getenv("NODE_PORT", "3100"))
NODE_PUBLIC_URL = os.getenv("NODE_PUBLIC_URL", "")
VAULT_PATH      = os.getenv("VAULT_PATH", "C:/Users/User/SecondBrain")
PAOS_API_KEY    = os.getenv("PAOS_API_KEY", "paos-node-local-key")

# 逗號分隔的 agent 名稱清單；Node 啟動時自動初始化這些 agent 的 Vault 結構。
# 範例：INIT_AGENTS=宇恆,其他助理
# 空字串 = 不自動初始化（手動呼叫 POST /setup/init-agent）
INIT_AGENTS: list[str] = [
    a.strip() for a in os.getenv("INIT_AGENTS", "").split(",") if a.strip()
]
