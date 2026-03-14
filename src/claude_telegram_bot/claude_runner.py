import asyncio
import json
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Generator

from claude_telegram_bot import config

logger = logging.getLogger(__name__)


@dataclass
class ConfirmationRequest:
    """Represents a confirmation request from Claude."""
    message: str
    tool_name: str
    tool_input: dict


async def run_claude(
    prompt: str,
    cwd: str | None = None,
    continue_session: bool = True,
    allowed_tools: list[str] | None = None,
    timeout: int | None = None,
) -> str:
    """Call the Claude Code CLI and return its output.

    Args:
        prompt: The prompt to send.
        cwd: Working directory for the CLI process.
        continue_session: Whether to continue the last conversation (-c flag).
        allowed_tools: Tools to allow (e.g. ["Bash", "Read"]).
        timeout: Override timeout in seconds.
    """
    timeout = timeout or config.CLAUDE_TIMEOUT
    cmd = [config.CLAUDE_PATH, "--print"]

    if continue_session:
        cmd.append("-c")

    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

    cmd.append(prompt)

    cwd = cwd or str(Path.home())

    logger.debug("Running: %s (cwd=%s)", cmd, cwd)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"Claude CLI timed out after {timeout}s."

    output = stdout.decode(errors="replace").strip()
    err = stderr.decode(errors="replace").strip()

    if proc.returncode != 0 and not output:
        return f"Claude CLI failed (exit {proc.returncode}):\n{err[:500]}"

    if err and not output:
        return f"Claude CLI error:\n{err[:500]}"

    return output if output else "(no output)"


async def run_claude_stream(
    prompt: str,
    cwd: str | None = None,
    continue_session: bool = True,
    allowed_tools: list[str] | None = None,
    timeout: int | None = None,
) -> Generator[tuple[str, ConfirmationRequest | None], None, None]:
    """Yield (output, confirmation_request) tuples from Claude Code CLI.

    Yields:
        tuples of (output_chunk, confirmation_request)
        confirmation_request is None unless Claude is asking for confirmation
    """
    timeout = timeout or config.CLAUDE_TIMEOUT
    cmd = [config.CLAUDE_PATH, "--print", "--output-format", "stream-json"]

    if continue_session:
        cmd.append("-c")

    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

    cmd.append(prompt)

    cwd = cwd or str(Path.home())

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )

    try:
        async for line in proc.stdout:
            line = line.decode(errors="replace").strip()
            if not line:
                continue

            # Try to parse as JSON
            try:
                data = json.loads(line)
                # Check for confirmation request
                if data.get("type") == "confirm":
                    confirmation = ConfirmationRequest(
                        message=data.get("message", "Please confirm this action"),
                        tool_name=data.get("confirmation", {}).get("type", "unknown"),
                        tool_input=data.get("confirmation", {}).get("input", {}),
                    )
                    yield ("", confirmation)
                else:
                    # Regular output
                    content = data.get("content", "")
                    if isinstance(content, list):
                        for item in content:
                            if item.get("type") == "text":
                                yield (item.get("text", ""), None)
                    elif content:
                        yield (str(content), None)
            except json.JSONDecodeError:
                # Not JSON, yield as-is
                yield (line, None)
    except asyncio.TimeoutError:
        proc.kill()

    await proc.wait()
