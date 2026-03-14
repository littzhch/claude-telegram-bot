#!/usr/bin/env python3
"""Telegram Bot for Claude Code CLI."""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)

from claude_telegram_bot import config
from claude_telegram_bot.auth import require_auth, is_admin
from claude_telegram_bot.claude_runner import run_claude, run_claude_stream, ConfirmationRequest
from claude_telegram_bot.session_manager import SessionManager, init_db as init_session_db
from claude_telegram_bot.project_manager import (
    init_db as init_project_db,
    add_project,
    remove_project,
    list_projects,
    get_project_path,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# In-memory session managers per user
_user_sessions: dict[int, SessionManager] = {}

# Track pending confirmations: user_id -> {"message_id": int, "tool": str, "input": dict}
_pending_confirmations: dict[int, dict] = {}


def _get_session(user_id: int) -> SessionManager:
    if user_id not in _user_sessions:
        _user_sessions[user_id] = SessionManager(user_id)
    return _user_sessions[user_id]


# ── Commands ──

@require_auth
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Hello {user.first_name}! I'm your Claude Code bot.\n\n"
        "Send me any message and I'll run it through Claude Code CLI.\n\n"
        "Key commands:\n"
        "/new - Start a new conversation\n"
        "/sessions - List all sessions\n"
        "/history - View conversation history\n"
        "/projects - List configured projects\n"
        "/add_project <name> <path> - Add a project\n"
        "/use <project> - Switch to a project\n"
        "/status - Current status\n"
        "/help - Show help"
    )


@require_auth
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*Claude Code Telegram Bot*\n\n"
        "*Conversation*\n"
        "/new - Start new conversation\n"
        "/sessions - List all sessions\n"
        "/switch <id> - Switch session\n"
        "/history - Show recent history\n\n"
        "*Projects*\n"
        "/projects - List projects\n"
        "/add_project <name> <path> - Add project\n"
        "/remove_project <name> - Remove project\n"
        "/use <name> - Switch active project\n\n"
        "*Status*\n"
        "/status - Current status\n"
        "/help - This message\n\n"
        "*Files*\n"
        "Send a document to attach it to the conversation.\n"
        "The file path will be included in the prompt to Claude."
    )
    if is_admin(update.effective_user.id):
        text += (
            "\n\n*Admin*\n"
            "/admin add <user_id> - Add user\n"
            "/admin remove <user_id> - Remove user\n"
            "/admin list - List allowed users"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


@require_auth
async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sm = _get_session(update.effective_user.id)
    sm.new_session()
    await update.message.reply_text("New conversation started.")


@require_auth
async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sm = _get_session(update.effective_user.id)
    sessions = sm.list_sessions()
    if not sessions:
        await update.message.reply_text("No sessions yet. Send a message to start one.")
        return

    lines = []
    active_id = sm.active_session_id
    for s in sessions:
        marker = " *" if s["id"] == active_id else ""
        lines.append(f"{s['id']}. {s['name']} (updated: {s['updated_at'][:16]}){marker}")
    await update.message.reply_text(
        "Sessions (active marked with *):\n" + "\n".join(lines)
    )


@require_auth
async def cmd_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /switch <session_id>")
        return
    try:
        sid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid session ID.")
        return
    sm = _get_session(update.effective_user.id)
    if sm.switch_session(sid):
        await update.message.reply_text(f"Switched to session {sid}.")
    else:
        await update.message.reply_text(f"Session {sid} not found.")


@require_auth
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sm = _get_session(update.effective_user.id)
    history = sm.get_history(limit=20)
    if not history:
        await update.message.reply_text("No history in current session.")
        return

    lines = []
    for msg in history:
        role = "You" if msg["role"] == "user" else "Claude"
        content = msg["content"][:200]
        if len(msg["content"]) > 200:
            content += "..."
        lines.append(f"*{role}:* {content}")

    text = "\n\n".join(lines)
    # Telegram message limit
    if len(text) > 4000:
        text = text[:4000] + "\n... (truncated)"
    await update.message.reply_text(text, parse_mode="Markdown")


@require_auth
async def cmd_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    projects = list_projects(user_id)
    if not projects:
        await update.message.reply_text(
            "No projects configured. Use /add_project <name> <path> to add one."
        )
        return

    sm = _get_session(user_id)
    active_cwd = sm.get_active_cwd()
    lines = []
    for p in projects:
        active = " *" if p["path"] == active_cwd else ""
        lines.append(f"• {p['name']}: {p['path']}{active}")
    await update.message.reply_text(
        "Projects (active marked with *):\n" + "\n".join(lines)
    )


@require_auth
async def cmd_add_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /add_project <name> <path>")
        return
    name = context.args[0]
    path = " ".join(context.args[1:])
    user_id = update.effective_user.id
    ok, msg = add_project(user_id, name, path)
    await update.message.reply_text(msg)


@require_auth
async def cmd_remove_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /remove_project <name>")
        return
    name = context.args[0]
    user_id = update.effective_user.id
    ok, msg = remove_project(user_id, name)
    await update.message.reply_text(msg)


@require_auth
async def cmd_use(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /use <project_name>")
        return
    name = context.args[0]
    user_id = update.effective_user.id
    path = get_project_path(user_id, name)
    if path is None:
        await update.message.reply_text(f"Project '{name}' not found. Use /projects to list.")
        return
    sm = _get_session(user_id)
    sm.set_cwd(path)
    await update.message.reply_text(f"Switched to project '{name}' ({path}).")


@require_auth
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sm = _get_session(user_id)
    active_cwd = sm.get_active_cwd() or "(default: home)"
    sessions = sm.list_sessions()
    active_sid = sm.active_session_id
    projects = list_projects(user_id)

    text = (
        f"*Status*\n"
        f"User ID: {user_id}\n"
        f"Admin: {'Yes' if is_admin(user_id) else 'No'}\n"
        f"Active session: {active_sid or 'None'}\n"
        f"Working directory: {active_cwd}\n"
        f"Sessions: {len(sessions)}\n"
        f"Projects: {len(projects)}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ── Admin ──

@require_auth
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("Admin only.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage:\n/admin add <user_id>\n/admin remove <user_id>\n/admin list"
        )
        return

    action = context.args[0].lower()

    if action == "list":
        ids = ", ".join(str(uid) for uid in config.ALLOWED_USER_IDS)
        await update.message.reply_text(f"Allowed user IDs:\n{ids}")
        return

    if action == "add" and len(context.args) >= 2:
        try:
            new_id = int(context.args[1])
        except ValueError:
            await update.message.reply_text("Invalid user ID.")
            return
        if new_id not in config.ALLOWED_USER_IDS:
            config.ALLOWED_USER_IDS.append(new_id)
        await update.message.reply_text(f"Added user {new_id}.")
        return

    if action == "remove" and len(context.args) >= 2:
        try:
            rem_id = int(context.args[1])
        except ValueError:
            await update.message.reply_text("Invalid user ID.")
            return
        if rem_id in config.ALLOWED_USER_IDS:
            config.ALLOWED_USER_IDS.remove(rem_id)
        await update.message.reply_text(f"Removed user {rem_id}.")
        return

    await update.message.reply_text("Unknown admin command.")


# ── File upload ──

@require_auth
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded documents - download and save to session's temp dir."""
    doc = update.message.document
    if not doc:
        return

    user_id = update.effective_user.id
    sm = _get_session(user_id)
    cwd = sm.get_active_cwd() or str(Path.home())

    file = await context.bot.get_file(doc.file_id)
    dest = os.path.join(cwd, doc.file_name or "uploaded_file")
    await file.download_to_drive(dest)

    sm.add_message("user", f"[Uploaded file: {dest}]")
    await update.message.reply_text(f"File saved to: {dest}")


# ── Confirmation handler ──

@require_auth
async def handle_confirmation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle confirmation button presses (Yes/No)."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    callback_data = query.data

    # Check if there's a pending confirmation for this user
    if user_id not in _pending_confirmations:
        await query.edit_message_text("No pending confirmation.")
        return

    confirmation = _pending_confirmations.pop(user_id)
    message_id = confirmation["message_id"]

    if callback_data == "confirm_yes":
        # User confirmed - send approval to Claude
        await query.edit_message_text(
            text=confirmation.get("description", "Action confirmed."),
            reply_markup=None,
        )
        # Note: Claude CLI in stream mode may not support stdin for confirmation
        # This is a simplified implementation - the action would need to be retried
        await context.bot.send_message(
            chat_id=user_id,
            text="Confirmed! (Note: Claude CLI confirmation flow may need retry)",
        )
    else:
        # User declined
        await query.edit_message_text(
            text="Action cancelled.",
            reply_markup=None,
        )


# ── Message handler ──

@require_auth
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages - forward to Claude Code CLI."""
    text = update.message.text
    if not text:
        return

    user_id = update.effective_user.id
    sm = _get_session(user_id)

    # Ensure we have a session
    if sm.active_session_id is None:
        sm.new_session()

    cwd = sm.get_active_cwd() or str(Path.home())

    # Build prompt with history
    prompt = sm.build_prompt(text)

    # Save user message
    sm.add_message("user", text)

    # Send "thinking" indicator
    thinking_msg = await update.message.reply_text("Claude is thinking...")

    try:
        # Use stream to detect confirmation requests
        output_parts = []
        confirmation_request = None

        async for output, confirm_req in run_claude_stream(
            prompt, cwd=cwd, continue_session=False
        ):
            if confirm_req:
                # Claude is asking for confirmation
                confirmation_request = confirm_req
                break
            if output:
                output_parts.append(output)

        output = "".join(output_parts)

        # If confirmation requested, show confirmation dialog
        if confirmation_request:
            await thinking_msg.delete()

            # Build confirmation message
            tool_info = f"Tool: {confirmation_request.tool_name}"
            if confirmation_request.tool_input:
                # Show relevant details based on tool type
                if "path" in confirmation_request.tool_input:
                    tool_info += f"\nPath: {confirmation_request.tool_input.get('path')}"
                elif "file_path" in confirmation_request.tool_input:
                    tool_info += f"\nFile: {confirmation_request.tool_input.get('file_path')}"

            confirmation_text = (
                f"⚠️ *Confirmation Required*\n\n"
                f"{confirmation_request.message}\n\n"
                f"_{tool_info}_"
            )

            keyboard = [
                [
                    InlineKeyboardButton("✅ Confirm", callback_data="confirm_yes"),
                    InlineKeyboardButton("❌ Cancel", callback_data="confirm_no"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            confirm_msg = await update.message.reply_text(
                confirmation_text,
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )

            # Store pending confirmation
            _pending_confirmations[user_id] = {
                "message_id": confirm_msg.message_id,
                "tool": confirmation_request.tool_name,
                "input": confirmation_request.tool_input,
                "description": confirmation_request.message,
            }

            # Don't save to history yet - wait for confirmation
            return

    except Exception as e:
        output = f"Error: {e}"

    # Save assistant response
    sm.add_message("assistant", output)

    # Send response (split if too long)
    await thinking_msg.delete()
    if len(output) <= 4000:
        await update.message.reply_text(output)
    else:
        # Split into chunks
        chunks = []
        while output:
            chunk = output[:4000]
            # Try to split at a newline boundary
            last_nl = chunk.rfind("\n")
            if last_nl > 2000:
                chunk = output[:last_nl]
                output = output[last_nl + 1:]
            else:
                output = output[4000:]
            chunks.append(chunk)
        for chunk in chunks:
            await update.message.reply_text(chunk)


# ── Main ──

async def post_init(app: Application):
    """Set bot commands for the Telegram UI."""
    commands = [
        BotCommand("start", "Start using the bot"),
        BotCommand("help", "Show help"),
        BotCommand("new", "New conversation"),
        BotCommand("sessions", "List sessions"),
        BotCommand("switch", "Switch session"),
        BotCommand("history", "Show history"),
        BotCommand("projects", "List projects"),
        BotCommand("add_project", "Add project"),
        BotCommand("remove_project", "Remove project"),
        BotCommand("use", "Switch project"),
        BotCommand("status", "Current status"),
    ]
    await app.bot.set_my_commands(commands)


def main():
    if not config.BOT_TOKEN:
        print("Error: BOT_TOKEN not set. Copy .env.example to .env and configure it.")
        return
    if not config.ALLOWED_USER_IDS:
        print("Warning: ALLOWED_USER_IDS is empty. Only admin can use the bot.")

    # Init databases
    init_session_db()
    init_project_db()

    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("sessions", cmd_sessions))
    app.add_handler(CommandHandler("switch", cmd_switch))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("projects", cmd_projects))
    app.add_handler(CommandHandler("add_project", cmd_add_project))
    app.add_handler(CommandHandler("remove_project", cmd_remove_project))
    app.add_handler(CommandHandler("use", cmd_use))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("admin", cmd_admin))

    # File uploads
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Confirmation callbacks (must be before MessageHandler)
    app.add_handler(CallbackQueryHandler(handle_confirmation_callback))

    # Text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting bot...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
