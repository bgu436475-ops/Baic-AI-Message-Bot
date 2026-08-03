from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandStatus:
    """Minimal command outcome needed to classify launchctl's absent service."""

    returncode: int
    stderr: str = ""


def command_status(value: object) -> CommandStatus:
    """Normalize test runners and the real runner without exposing stderr."""
    if isinstance(value, int) and not isinstance(value, bool):
        return CommandStatus(value)
    returncode = getattr(value, "returncode", None)
    stderr = getattr(value, "stderr", "")
    if not isinstance(returncode, int) or isinstance(returncode, bool):
        raise ValueError("invalid_command_status")
    if not isinstance(stderr, str):
        raise ValueError("invalid_command_status")
    return CommandStatus(returncode, stderr)


def _is_service_absent(returncode: int, stderr: str) -> bool:
    """Accept only known macOS absent-service forms; all others are ambiguous."""
    if returncode == 3:
        return True
    if returncode != 113:
        return False
    sanitized = " ".join(stderr.casefold().split())
    return any(
        marker in sanitized
        for marker in (
            "could not find specified service",
            "could not find service",
            "service not found",
        )
    )
