import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
ALLOWED_USER_IDS = [
    int(uid.strip())
    for uid in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
]

# Claude Code CLI
CLAUDE_PATH = os.getenv("CLAUDE_PATH", "/home/zhangchi/.local/bin/claude")
CLAUDE_TIMEOUT = int(os.getenv("CLAUDE_TIMEOUT", "120"))
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "40"))

# Database — defaults to ./data/bot.db relative to project root (CWD)
DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.getcwd(), "data"))
DB_PATH = os.path.join(DATA_DIR, "bot.db")
