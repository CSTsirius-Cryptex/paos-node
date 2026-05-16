import os
import re
from datetime import datetime
from src.config import VAULT_PATH

def resolve_path(relative: str) -> str:
    return os.path.join(VAULT_PATH, relative.lstrip("/").replace("/", os.sep))

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
    base = resolve_path(folder) if folder else VAULT_PATH
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
    "work_log":       "PAOS/workflow/{agent}/workflow-doc.md",
    "project_memory": "PAOS/workflow/{agent}/project-memory.md",
    "perspective":    "agents/{agent}/perspectives/{slug}.md",
    "decision":       "agents/{agent}/decisions/{slug}.md",
    "insight":        "agents/{agent}/insights/{slug}.md",
    "knowledge":      "shared/knowledge/{slug}.md",
    "contact":        "shared/contacts/{slug}.md",
    "project_brief":  "PAOS/projects/{slug}/brief.md",
}

def resolve_memory_path(memory_type: str, params: dict) -> str:
    template = MEMORY_TYPE_PATHS.get(memory_type)
    if not template:
        raise ValueError(f"未知 memory_type: {memory_type}")
    agent = normalize_agent_name(params.get("agent_name", ""))
    slug = params.get("slug", datetime.now().strftime("%Y%m%d"))
    return template.format(agent=agent, slug=slug)
