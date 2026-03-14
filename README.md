# Claude Telegram Bot

Telegram bot for interacting with Claude Code CLI

## Installation

```bash
pip install claude-telegram-bot
```

## Configuration

Configuration priority: CLI > ENV > config file > defaults

### Config File

Create `~/.config/claude-tg-bot.toml`:

```toml
[telegram]
bot_token = "your-telegram-bot-token"
admin_user_id = 123456789
allowed_user_ids = [123456789]

[claude]
path = "/home/zhangchi/.local/bin/claude"
timeout = 120

[data]
dir = "~/.cache/claude-tg-bot"
```

### Environment Variables

- `BOT_TOKEN`: Telegram bot token
- `ADMIN_USER_ID`: Admin user ID
- `ALLOWED_USER_IDS`: Comma-separated user IDs
- `CLAUDE_PATH`: Path to Claude CLI
- `CLAUDE_TIMEOUT`: Command timeout in seconds
- `DATA_DIR`: Data directory

### CLI Arguments

```bash
claude-tg-bot --help
```

## Usage

```bash
claude-tg-bot --bot-token YOUR_TOKEN
```
