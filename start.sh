#!/bin/bash
cd "$(dirname "$0")"

# Check if bot token is provided via any config source
# Configuration priority: CLI args > env vars > config file (~/.config/claude-tg-bot.toml)

if [ -z "$BOT_TOKEN" ] && [ ! -f "$HOME/.config/claude-tg-bot.toml" ]; then
    echo "Error: No configuration found."
    echo ""
    echo "Please either:"
    echo "  1. Set BOT_TOKEN environment variable:"
    echo "     BOT_TOKEN=your-token ./start.sh"
    echo ""
    echo "  2. Create config file at ~/.config/claude-tg-bot.toml"
    echo "     (see config.example.toml for reference)"
    echo ""
    echo "  3. Use CLI arguments:"
    echo "     uv run -m claude_telegram_bot --bot-token your-token"
    exit 1
fi

uv run -m claude_telegram_bot "$@"
