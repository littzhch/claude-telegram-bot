"""Claude Runner using Claude Agent SDK."""

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

from claude_telegram_bot import config
from claude_telegram_bot.permission_manager import PermissionManager

logger = logging.getLogger(__name__)


@dataclass
class ConfirmationRequest:
    """Represents a confirmation request from Claude."""
    message: str
    tool_name: str
    tool_input: dict


# Global permission manager instance
_permission_manager: PermissionManager | None = None


def get_permission_manager() -> PermissionManager:
    """Get or create the global permission manager."""
    global _permission_manager
    if _permission_manager is None:
        _permission_manager = PermissionManager()
    return _permission_manager


def set_permission_manager(manager: PermissionManager):
    """Set the global permission manager (for testing)."""
    global _permission_manager
    _permission_manager = manager


async def run_claude(
    prompt: str,
    cwd: str | None = None,
    continue_session: bool = True,
    allowed_tools: list[str] | None = None,
    timeout: int | None = None,
    permission_manager: PermissionManager | None = None,
) -> str:
    """Call the Claude Agent SDK and return its output.

    Args:
        prompt: The prompt to send.
        cwd: Working directory for the Claude process.
        continue_session: Whether to continue the last conversation (handled by SDK).
        allowed_tools: Tools to allow (e.g. ["Bash", "Read"]).
        timeout: Not directly used - SDK handles its own timeout.
        permission_manager: Optional permission manager for tool access control.
    """
    # Use provided permission manager or get global one
    pm = permission_manager or get_permission_manager()

    options = ClaudeAgentOptions(
        cwd=cwd,
        max_turns=100,
    )

    if allowed_tools:
        options.allowed_tools = allowed_tools

    # Set permission mode to ensure callbacks are invoked
    options.permission_mode = "default"
    # Set permission callback - requires streaming mode
    options.can_use_tool = pm.check_permission

    output_parts = []

    try:
        # Use ClaudeSDKClient with streaming mode (required for can_use_tool)
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            output_parts.append(block.text)
                elif isinstance(message, ResultMessage):
                    # End of conversation
                    break
    except Exception as e:
        logger.error(f"Claude SDK error: {e}")
        return f"Claude SDK error: {e}"

    output = "".join(output_parts)
    return output if output else "(no output)"


async def run_claude_stream(
    prompt: str,
    cwd: str | None = None,
    continue_session: bool = True,
    allowed_tools: list[str] | None = None,
    timeout: int | None = None,
    permission_manager: PermissionManager | None = None,
) -> AsyncIterable[tuple[str, ConfirmationRequest | None]]:
    """Yield (output, confirmation_request) tuples from Claude Agent SDK.

    Note: The SDK uses permission system instead of confirmation requests.
    This implementation returns (output, None) tuples since permission
    handling is done via the permission_manager callback.

    Yields:
        tuples of (output_chunk, confirmation_request)
        confirmation_request is always None in this implementation
    """
    # Use provided permission manager or get global one
    pm = permission_manager or get_permission_manager()

    options = ClaudeAgentOptions(
        cwd=cwd,
        max_turns=100,
    )

    if allowed_tools:
        options.allowed_tools = allowed_tools

    # Set permission mode to ensure callbacks are invoked
    options.permission_mode = "default"
    # Set permission callback - requires streaming mode
    options.can_use_tool = pm.check_permission

    try:
        # Use ClaudeSDKClient with streaming mode
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            yield (block.text, None)
                elif isinstance(message, ResultMessage):
                    # End of conversation
                    break
    except Exception as e:
        logger.error(f"Claude SDK error: {e}")
        yield (f"Claude SDK error: {e}", None)
