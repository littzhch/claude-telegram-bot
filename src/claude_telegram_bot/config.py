import argparse
import os
import sys
from pathlib import Path
from typing import Optional

# Default config file path
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "claude-tg-bot.toml"
DEFAULT_DATA_DIR = Path.home() / ".cache" / "claude-tg-bot"


def load_toml_config(config_path: Path) -> dict:
    """Load configuration from TOML file."""
    if not config_path.exists():
        return {}

    try:
        import tomllib
    except ImportError:
        # Python < 3.11
        try:
            import tomli as tomllib
        except ImportError:
            return {}

    with open(config_path, "rb") as f:
        return tomllib.load(f)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Claude Telegram Bot",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Telegram options
    parser.add_argument(
        "--bot-token", "-t",
        type=str,
        help="Telegram bot token",
    )
    parser.add_argument(
        "--admin-user-id", "-a",
        type=int,
        help="Admin user ID",
    )
    parser.add_argument(
        "--allowed-user-ids",
        type=str,
        help="Comma-separated list of allowed user IDs",
    )

    # Claude options
    parser.add_argument(
        "--claude-path",
        type=str,
        help="Path to Claude CLI executable",
    )
    parser.add_argument(
        "--claude-timeout",
        type=int,
        help="Timeout for Claude CLI commands (seconds)",
    )
    parser.add_argument(
        "--max-history-messages",
        type=int,
        help="Maximum number of history messages to keep",
    )

    # Data options
    parser.add_argument(
        "--data-dir",
        type=str,
        help="Directory for storing bot data",
    )

    # Config file
    parser.add_argument(
        "--config", "-c",
        type=str,
        help="Path to config file (default: ~/.config/claude-tg-bot.toml)",
    )

    # Version
    parser.add_argument(
        "--version", "-v",
        action="version",
        version="%(prog)s 1.0.0",
    )

    return parser.parse_args()


def get_config() -> dict:
    """
    Get configuration with priority: CLI > ENV > config file > defaults
    """
    # Load config file first (lowest priority)
    args = parse_args()

    # Determine config file path
    config_file = Path(args.config) if args.config else DEFAULT_CONFIG_PATH
    file_config = load_toml_config(config_file)

    # Build final config with priority: CLI > ENV > file > defaults
    config = {}

    # Telegram settings
    config["bot_token"] = (
        args.bot_token
        or os.getenv("BOT_TOKEN")
        or file_config.get("telegram", {}).get("bot_token", "")
    )

    admin_user_id = (
        args.admin_user_id
        or os.getenv("ADMIN_USER_ID")
        or file_config.get("telegram", {}).get("admin_user_id")
    )
    config["admin_user_id"] = int(admin_user_id) if admin_user_id else 0

    # Allowed user IDs
    allowed_users_arg = args.allowed_user_ids or os.getenv("ALLOWED_USER_IDS") or ""
    file_allowed = file_config.get("telegram", {}).get("allowed_user_ids", [])
    if isinstance(file_allowed, list):
        file_allowed = ",".join(map(str, file_allowed))

    allowed_users = allowed_users_arg or file_allowed or ""
    config["allowed_user_ids"] = [
        int(uid.strip())
        for uid in allowed_users.split(",")
        if uid.strip()
    ]

    # Claude settings
    config["claude_path"] = (
        args.claude_path
        or os.getenv("CLAUDE_PATH")
        or file_config.get("claude", {}).get("path", "/home/zhangchi/.local/bin/claude")
    )

    config["claude_timeout"] = (
        args.claude_timeout
        or int(os.getenv("CLAUDE_TIMEOUT") or 0)
        or file_config.get("claude", {}).get("timeout", 120)
    )

    config["max_history_messages"] = (
        args.max_history_messages
        or int(os.getenv("MAX_HISTORY_MESSAGES") or 0)
        or file_config.get("claude", {}).get("max_history_messages", 40)
    )

    # Data directory
    data_dir_arg = args.data_dir or os.getenv("DATA_DIR") or ""
    config["data_dir"] = (
        data_dir_arg
        or file_config.get("data", {}).get("dir", str(DEFAULT_DATA_DIR))
    )

    # Validate required config
    if not config["bot_token"]:
        print("Error: BOT_TOKEN is required.", file=sys.stderr)
        print(f"Set it via: --bot-token, env var BOT_TOKEN, or config file", file=sys.stderr)
        sys.exit(1)

    if config["admin_user_id"] == 0:
        print("Warning: ADMIN_USER_ID not set. Using default 0.", file=sys.stderr)

    # Ensure data directory exists
    Path(config["data_dir"]).mkdir(parents=True, exist_ok=True)

    return config


# Global config instance
CONFIG = get_config()

# Convenience accessors
BOT_TOKEN = CONFIG["bot_token"]
ADMIN_USER_ID = CONFIG["admin_user_id"]
ALLOWED_USER_IDS = CONFIG["allowed_user_ids"]
CLAUDE_PATH = CONFIG["claude_path"]
CLAUDE_TIMEOUT = CONFIG["claude_timeout"]
MAX_HISTORY_MESSAGES = CONFIG["max_history_messages"]
DATA_DIR = CONFIG["data_dir"]
DB_PATH = os.path.join(DATA_DIR, "bot.db")
