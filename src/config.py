import os
from dotenv import load_dotenv

load_dotenv()

CENTRAL_URL    = os.getenv("CENTRAL_URL", "https://paos-central-production.up.railway.app")
NODE_PORT      = int(os.getenv("NODE_PORT", "3100"))
NODE_PUBLIC_URL = os.getenv("NODE_PUBLIC_URL", "")
VAULT_PATH     = os.getenv("VAULT_PATH", "C:/Users/User/SecondBrain")
PAOS_API_KEY   = os.getenv("PAOS_API_KEY", "paos-node-local-key")
