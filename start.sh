#!/bin/bash
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "Error: .env file not found. Copy .env.example to .env and configure it."
    exit 1
fi

uv run -m claude_telegram_bot
