"""Permission Manager for handling tool permission requests."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING

from claude_agent_sdk import (
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

if TYPE_CHECKING:
    from telegram import Bot

logger = logging.getLogger(__name__)


@dataclass
class PendingPermission:
    """Represents a pending permission request."""
    user_id: int
    tool_name: str
    tool_input: dict
    context: ToolPermissionContext
    event: asyncio.Event = field(default_factory=asyncio.Event)
    result: PermissionResult | None = None


class PermissionManager:
    """
    Manages tool permission requests with user confirmation via Telegram.

    Uses asyncio.Event to wait for user confirmation before returning
    the permission result to Claude SDK.
    """

    def __init__(self, confirmation_callback: Callable[[int, str, dict], bool] | None = None):
        """
        Initialize PermissionManager.

        Args:
            confirmation_callback: Optional sync callback for auto-confirmation.
                                 Args: (user_id, tool_name, tool_input)
                                 Returns True to allow, False to deny.
        """
        self._pending: PendingPermission | None = None
        self._confirmation_callback = confirmation_callback
        self._waiting_user_id: int | None = None
        self._telegram_bot: "Bot | None" = None

    def set_telegram_bot(self, bot: "Bot"):
        """Set the Telegram bot instance for sending messages."""
        self._telegram_bot = bot

    async def check_permission(
        self,
        tool_name: str,
        tool_input: dict,
        context: ToolPermissionContext,
    ) -> PermissionResult:
        """
        Check if a tool should be allowed to run.

        This method is called by the SDK before each tool execution.
        If there's a pending confirmation, it waits for user response.

        Args:
            tool_name: Name of the tool to check
            tool_input: Input arguments for the tool
            context: Permission context with additional info

        Returns:
            PermissionResultAllow to allow, PermissionResultDeny to deny
        """
        # If there's already a pending request, deny to prevent concurrent requests
        if self._pending is not None:
            logger.warning("Concurrent permission request denied")
            return PermissionResultDeny(message="Another permission request is pending")

        # If we have a sync callback (for testing), use it directly
        if self._confirmation_callback and self._waiting_user_id is not None:
            try:
                if self._confirmation_callback(self._waiting_user_id, tool_name, tool_input):
                    result = PermissionResultAllow()
                else:
                    result = PermissionResultDeny(message="Permission denied by callback")
            except Exception as e:
                result = PermissionResultDeny(message=f"Error in callback: {e}")
            return result

        # Return default allow if no user is waiting (shouldn't happen in normal flow)
        if self._waiting_user_id is None:
            logger.warning(f"No user waiting for permission for tool {tool_name}, defaulting to allow")
            return PermissionResultAllow()

        logger.info(f"Permission request for {tool_name} from user {self._waiting_user_id}")

        # Create pending permission request
        self._pending = PendingPermission(
            user_id=self._waiting_user_id,
            tool_name=tool_name,
            tool_input=tool_input,
            context=context,
        )

        # Send confirmation message to user immediately
        if self._telegram_bot and self._waiting_user_id:
            try:
                tool_info = f"Tool: {tool_name}"
                if "path" in tool_input:
                    tool_info += f"\nPath: {tool_input.get('path')}"
                elif "file_path" in tool_input:
                    tool_info += f"\nFile: {tool_input.get('file_path')}"
                elif "command" in tool_input:
                    tool_info += f"\nCommand: {tool_input.get('command')[:100]}"

                confirmation_text = (
                    f"⚠️ *Permission Request*\n\n"
                    f"Claude wants to run: *{tool_name}*\n\n"
                    f"_{tool_info}_"
                )

                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Allow", callback_data="confirm_yes"),
                        InlineKeyboardButton("❌ Deny", callback_data="confirm_no"),
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await self._telegram_bot.send_message(
                    chat_id=self._waiting_user_id,
                    text=confirmation_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown",
                )
                logger.info(f"Confirmation message sent to user {self._waiting_user_id}")
            except Exception as e:
                logger.error(f"Failed to send confirmation message: {e}")

        # Wait for user confirmation (with timeout)
        try:
            # Wait for up to 60 seconds for user response
            await asyncio.wait_for(
                self._pending.event.wait(),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            logger.warning(f"Permission request for {tool_name} timed out")
            result = PermissionResultDeny(message="Permission request timed out")
            self._pending = None
            self._waiting_user_id = None
            return result

        # Get the result set by user response handler
        result = self._pending.result
        self._pending = None
        self._waiting_user_id = None

        if result is None:
            return PermissionResultDeny(message="No confirmation received")

        return result

    def set_waiting_user(self, user_id: int):
        """Set the user who is currently waiting for a response."""
        logger.info(f"Setting waiting user: {user_id}")
        self._waiting_user_id = user_id

    def clear_waiting_user(self):
        """Clear the waiting user."""
        self._waiting_user_id = None

    def get_pending_confirmation(self) -> tuple[int, str, dict] | None:
        """
        Get the pending confirmation request for displaying to user.

        Returns:
            Tuple of (user_id, tool_name, tool_input) if there's a pending request, None otherwise
        """
        if self._pending is None:
            return None
        return (self._pending.user_id, self._pending.tool_name, self._pending.tool_input)

    def confirm(self) -> bool:
        """
        Confirm the pending permission request.

        Called when user clicks "Confirm" button in Telegram.

        Returns:
            True if confirmation was processed, False if no pending request
        """
        if self._pending is None:
            return False

        self._pending.result = PermissionResultAllow()
        self._pending.event.set()
        return True

    def deny(self, message: str = "User denied permission") -> bool:
        """
        Deny the pending permission request.

        Called when user clicks "Deny" button in Telegram.

        Args:
            message: Optional denial message

        Returns:
            True if denial was processed, False if no pending request
        """
        if self._pending is None:
            return False

        self._pending.result = PermissionResultDeny(message=message)
        self._pending.event.set()
        return True

    def has_pending(self) -> bool:
        """Check if there's a pending confirmation request."""
        return self._pending is not None
