import os
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://yunwu.ai/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")
LLM_FALLBACK_MODELS = [
    m.strip() for m in os.environ.get(
        "LLM_FALLBACK_MODELS",
        "claude-sonnet-4-6,claude-opus-4-6,Minimax-M2.5,gpt-5.3-chat-2026-03-03",
    ).split(",")
    if m.strip()
]

TASKS_DIR = os.path.join(ROOT, "tasks")
RUNS_DIR = os.path.join(ROOT, "runs")
CYBERGYM_META = os.path.join(ROOT, "data", "raw", "cybergym_100.json")
