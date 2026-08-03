from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from install_local_fallback import INSTALLER_LABEL


CommandRunner = Callable[[Sequence[str]], int]
LAUNCHCTL_SERVICE_NOT_FOUND = 3


class UninstallError(RuntimeError):
    """The launch agent could not be safely confirmed as unloaded."""


def _run_silently(command: Sequence[str]) -> int:
    try:
        return subprocess.run(
            list(command),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
    except OSError:
        return 127


def _launch_agent_is_loaded(context: "UninstallContext") -> bool:
    try:
        returncode = context.runner(
            [
                "/bin/launchctl",
                "print",
                f"gui/{context.uid}/{INSTALLER_LABEL}",
            ]
        )
    except OSError as error:
        raise UninstallError("launch_agent_status_failed") from error
    if returncode == 0:
        return True
    if returncode == LAUNCHCTL_SERVICE_NOT_FOUND:
        return False
    raise UninstallError("launch_agent_status_failed")


@dataclass(frozen=True)
class UninstallContext:
    home: Path
    runner: CommandRunner = _run_silently
    uid: int = 0

    @property
    def runtime_root(self) -> Path:
        return self.home / "Library/Application Support/Baic-AI-Message-Bot"

    @property
    def logs_root(self) -> Path:
        return self.home / "Library/Logs/Baic-AI-Message-Bot"

    @property
    def model_root(self) -> Path:
        return self.home / ".ollama/models"

    @property
    def launch_agent_path(self) -> Path:
        return self.home / "Library/LaunchAgents" / f"{INSTALLER_LABEL}.plist"

    @property
    def run_now_path(self) -> Path:
        return self.home / "Desktop/立即运行 Plan 2.command"

    @property
    def view_logs_path(self) -> Path:
        return self.home / "Desktop/查看 Plan 2 日志.command"


def uninstall_local_fallback(
    context: UninstallContext,
    output: Callable[[str], None] = print,
) -> str:
    """Unload only the agent and exact Desktop controls; preserve all diagnostics."""
    try:
        loaded = _launch_agent_is_loaded(context)
    except UninstallError as error:
        output(str(error))
        raise
    if loaded:
        bootout_command = [
            "/bin/launchctl",
            "bootout",
            f"gui/{context.uid}/{INSTALLER_LABEL}",
        ]
        try:
            bootout_returncode = context.runner(bootout_command)
        except OSError:
            bootout_returncode = 127
        try:
            still_loaded = _launch_agent_is_loaded(context)
        except UninstallError as error:
            if bootout_returncode != 0:
                reason = "launch_agent_bootout_failed"
                output(reason)
                raise UninstallError(reason) from error
            output(str(error))
            raise
        if bootout_returncode != 0:
            reason = "launch_agent_bootout_failed"
            output(reason)
            raise UninstallError(reason)
        if still_loaded:
            reason = "launch_agent_still_loaded"
            output(reason)
            raise UninstallError(reason)
    if context.launch_agent_path.exists():
        context.launch_agent_path.unlink()
    for path in (context.run_now_path, context.view_logs_path):
        if path.exists():
            path.unlink()
    summary = (
        "Preserved runtime/state/environment: "
        f"{context.runtime_root}\nPreserved logs: {context.logs_root}\n"
        f"Preserved Ollama model data: {context.model_root}"
    )
    output(summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remove local fallback controls")
    parser.add_argument("--home", type=Path, default=Path.home())
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        uninstall_local_fallback(
            UninstallContext(home=args.home, uid=os.getuid()),
            output=lambda _: None,
        )
    except UninstallError as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
